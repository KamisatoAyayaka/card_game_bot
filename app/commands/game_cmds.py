"""`/gwent` slash command group — challenge, open, surrender, info."""
from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands

from app.config import CONFIG
from app.game.engine import Match, MatchPhase
from app.services.card_service import CardService
from app.services.match_service import MatchService
from app.services.stats_service import StatsService
from app.ui.embeds.board_embed import (
    build_board_embed,
    build_match_finished_embed,
    build_round_result_embed,
)
from app.ui.views.invite_view import InviteView
from app.web import tokens as web_tokens
from app.web import websocket as web_ws
from app.web.routes import notify_match_finished, notify_match_started


def register_gwent_commands(tree: app_commands.CommandTree, bot: "discord.Client") -> None:
    group = app_commands.Group(
        name="gwent",
        description="Команды карточной игры в стиле Гвинт",
    )

    # ------------------------------------------------------------ challenge
    @group.command(
        name="challenge",
        description="Вызвать другого игрока на матч (или запустить с пресет-колодой)",
    )
    @app_commands.describe(
        opponent="Первый соперник",
        opponent2="Второй соперник (для матчей 3+ игроков)",
        opponent3="Третий соперник (для матчей 4 игроков)",
        rounds="Количество раундов (1, 3 или 5)",
        preset="Использовать пресет-колоду вместо сохранённой",
    )
    @app_commands.choices(rounds=[
        app_commands.Choice(name="BO1", value=1),
        app_commands.Choice(name="BO3 (классический)", value=3),
        app_commands.Choice(name="BO5", value=5),
    ])
    async def challenge(
        interaction: discord.Interaction,
        opponent: discord.Member,
        opponent2: Optional[discord.Member] = None,
        opponent3: Optional[discord.Member] = None,
        rounds: Optional[app_commands.Choice[int]] = None,
        preset: Optional[str] = None,
    ) -> None:
        if interaction.channel is None:
            await interaction.response.send_message("Эту команду можно использовать только в канале.")
            return
        if isinstance(interaction.channel, (discord.Thread, discord.ForumChannel)):
            await interaction.response.send_message("Используйте эту команду в текстовом канале, а не в треде.")
            return

        challenged = [opponent]
        if opponent2:
            challenged.append(opponent2)
        if opponent3:
            challenged.append(opponent3)
        challenged_ids: list[int] = []
        for m in challenged:
            if m.id == interaction.user.id:
                await interaction.response.send_message("Нельзя вызвать самого себя.", ephemeral=True)
                return
            if m.id in challenged_ids:
                await interaction.response.send_message("Дубликаты соперников не допускаются.", ephemeral=True)
                return
            if m.bot:
                await interaction.response.send_message("Боты не могут играть в карты.", ephemeral=True)
                return
            challenged_ids.append(m.id)

        if await MatchService.is_channel_busy(interaction.channel.id):
            await interaction.response.send_message(
                "В этом канале уже идёт матч. Дождитесь его завершения или используйте `/gwent surrender`.",
                ephemeral=True,
            )
            return

        rounds_total = rounds.value if rounds else CONFIG.default_match_rounds
        invite = await MatchService.create_invite(
            challenger_id=interaction.user.id,
            challenged_ids=challenged_ids,
            channel_id=interaction.channel.id,
            rounds=rounds_total,
        )

        mentions = " ".join(f"<@{cid}>" for cid in challenged_ids)
        embed = discord.Embed(
            title="⚔️ Вызов на матч!",
            description=(
                f"{interaction.user.mention} вызывает {mentions} на матч в стиле Гвинт.\n"
                f"Формат: BO{rounds_total}. Принять вызов — нажмите **Принять** ниже.\n"
                f"Через 2 минуты приглашение истечёт."
            ),
            color=0xE67E22,
        )
        view = InviteView(invite.invite_id, challenged_ids)
        await interaction.response.send_message(
            content=mentions,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

        timeout_task = asyncio.create_task(asyncio.wait_for(view.wait(), timeout=120))
        try:
            await timeout_task
        except asyncio.TimeoutError:
            await MatchService.cancel_invite(invite.invite_id)
            await interaction.followup.send("Время приёма вызова истекло. Матч отменён.")
            return

        if view.declined:
            return

        # All accepted — start the match
        from app.services.deck_service import DeckService
        all_player_ids = [interaction.user.id] + challenged_ids
        participants_data: list[tuple[int, str, str, list[str], str | None]] = []

        for pid in all_player_ids:
            if preset:
                preset_data = DeckService.load_preset(preset)
                if not preset_data:
                    await interaction.followup.send(
                        f"Пресет «{preset}» не найден.", ephemeral=True
                    )
                    return
                participants_data.append(
                    (
                        pid,
                        f"<@{pid}>",
                        preset_data["faction_id"],
                        list(preset_data["card_ids"]),
                        preset_data.get("leader_card_id"),
                    )
                )
            else:
                decks = await DeckService.list_decks(pid)
                if not decks:
                    await interaction.followup.send(
                        f"У <@{pid}> нет сохранённых колод. Используйте `/deck build` "
                        f"или `/gwent challenge ... preset:<имя>`.",
                        ephemeral=False,
                    )
                    return
                deck = decks[-1]
                participants_data.append(
                    (
                        pid,
                        f"<@{pid}>",
                        deck.faction_id,
                        list(deck.card_ids),
                        deck.leader_card_id,
                    )
                )

        # Load cards
        all_card_ids: set[str] = set()
        for _, _, _, cids, _ in participants_data:
            all_card_ids.update(cids)
        for entry in participants_data:
            if entry[4]:
                all_card_ids.add(entry[4])
        all_cards = await CardService.get_many(list(all_card_ids))
        card_lookup = {c.id: c for c in all_cards}
        missing_leaders = [
            entry[4] for entry in participants_data
            if entry[4] and entry[4] not in card_lookup
        ]
        if missing_leaders:
            extra = await CardService.get_many(missing_leaders)
            for c in extra:
                card_lookup[c.id] = c

        match = Match.create(
            channel_id=interaction.channel.id,
            participants=participants_data,
            card_lookup=card_lookup,
            rounds_total=rounds_total,
        )

        # ---- Issue web access tokens for every participant ----
        for pid in all_player_ids:
            display_name = next(
                (m.display_name for m in [interaction.user, opponent, opponent2, opponent3] if m and m.id == pid),
                f"Player {pid}",
            )
            web_tokens.issue_token(match.match_id, pid, display_name)

        # ---- Event listener: WS broadcast + Discord notifications ----
        async def on_event(m: Match, event: str, payload: dict) -> None:
            # Broadcast to all WS clients (each gets personalized snapshot)
            await web_ws.WS_MANAGER.broadcast_match_state(m)
            if event == "round_ended":
                await interaction.followup.send(embed=build_round_result_embed(m, payload))
            elif event == "match_finished":
                await interaction.followup.send(embed=build_match_finished_embed(m, payload))
                winner_id = payload.get("winner_id")
                await StatsService.record_result(
                    winner_id=winner_id,
                    participant_ids=[p.discord_id for p in m.players],
                    draw=(winner_id is None),
                )
                await MatchService.end(m.channel_id, m.match_id)
                web_tokens.revoke_match(m.match_id)
                await notify_match_finished(m)

        match.add_listener(on_event)
        await MatchService.register(interaction.channel.id, match)
        await notify_match_started(match)
        await match.start_match()

        # ---- Send the launch message with per-user buttons ----
        base_url = CONFIG.public_base_url.rstrip("/") if CONFIG.public_base_url else ""

        # Defensive: detect misconfigured PUBLIC_BASE_URL before sending buttons
        from app.ui.views.launch_view import _is_valid_http_url
        url_ok = _is_valid_http_url(base_url) if base_url else False

        if not url_ok:
            # Misconfiguration — explain to the user instead of crashing
            error_embed = discord.Embed(
                title="⚠️ Матч начался, но веб-интерфейс недоступен",
                description=(
                    f"Матч `{match.match_id}` создан, но бот не может сгенерировать ссылки на "
                    f"игровое поле, потому что не задана переменная окружения `PUBLIC_BASE_URL`.\n\n"
                    f"**Что делать администратору:**\n"
                    f"1. Откройте сервис на render.com → вкладка **Environment**\n"
                    f"2. Добавьте/отредактируйте переменную `PUBLIC_BASE_URL`\n"
                    f"3. Укажите полный URL вашего сервиса, например:\n"
                    f"   `https://gwent-discord-bot.onrender.com`\n"
                    f"4. Сохраните — render.com перепубликует сервис\n\n"
                    f"После этого матчи будут автоматически получать рабочие кнопки."
                ),
                color=0xE74C3C,
            )
            await interaction.followup.send(
                content=" ".join(f"<@{pid}>" for pid in all_player_ids),
                embed=error_embed,
                allowed_mentions=discord.AllowedMentions(users=True),
            )
            return

        launch_embed = discord.Embed(
            title="🎮 Матч начался! Откройте игровое поле",
            description=(
                f"Каждый игрок должен открыть своё игровое поле в браузере — "
                f"там будут видны ваша рука и карты противника.\n\n"
                f"**Формат:** BO{rounds_total}\n"
                f"**Раунд:** 1 / {rounds_total}\n\n"
                f"Нажмите кнопку ниже с вашим именем, чтобы открыть поле. "
                f"Ссылка персональная — не передавайте её другим."
            ),
            color=0x2ECC71,
        )

        from app.ui.views.launch_view import LaunchView
        view = LaunchView(match, base_url)
        await interaction.followup.send(
            content=" ".join(f"<@{pid}>" for pid in all_player_ids),
            embed=launch_embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    # ------------------------------------------------------------ open
    @group.command(name="open", description="Получить персональную ссылку на игровое поле текущего матча")
    async def open_field(interaction: discord.Interaction) -> None:
        if interaction.channel is None:
            return
        match = await MatchService.get_for_channel(interaction.channel.id)
        if match is None:
            await interaction.response.send_message(
                "В этом канале нет активного матча.", ephemeral=True
            )
            return
        if interaction.user.id not in {p.discord_id for p in match.players}:
            await interaction.response.send_message(
                "Вы не участвуете в этом матче.", ephemeral=True
            )
            return
        # Issue (or re-issue) a token for this user
        tok = web_tokens.issue_token(match.match_id, interaction.user.id, interaction.user.display_name)
        base_url = (CONFIG.public_base_url or "").rstrip("/")

        from app.ui.views.launch_view import _is_valid_http_url
        if not _is_valid_http_url(base_url):
            await interaction.response.send_message(
                "⚠️ Бот не настроен: переменная окружения `PUBLIC_BASE_URL` не задана "
                "или не является корректным URL (должна начинаться с `http://` или `https://`). "
                "Обратитесь к администратору.",
                ephemeral=True,
            )
            return

        url = f"{base_url}/play/{match.match_id}?token={tok.token}"
        embed = discord.Embed(
            title="🎮 Ваше игровое поле",
            description=f"[Открыть поле]({url})\n\nСсылка действительна 6 часов. Не передавайте её другим игрокам.",
            color=0x2ECC71,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------ surrender
    @group.command(name="surrender", description="Сдаться в текущем матче")
    async def surrender(interaction: discord.Interaction) -> None:
        if interaction.channel is None:
            return
        match = await MatchService.get_for_channel(interaction.channel.id)
        if match is None:
            await interaction.response.send_message("В этом канале нет активного матча.", ephemeral=True)
            return
        if interaction.user.id not in {p.discord_id for p in match.players}:
            await interaction.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
            return
        try:
            await match.surrender(interaction.user.id)
        except Exception as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=build_match_finished_embed(match, {"winner_id": match.winner.discord_id if match.winner else None}),
        )

    # ------------------------------------------------------------ info
    @group.command(name="info", description="Показать текущее состояние матча (кратко)")
    async def info(interaction: discord.Interaction) -> None:
        if interaction.channel is None:
            return
        match = await MatchService.get_for_channel(interaction.channel.id)
        if match is None:
            await interaction.response.send_message("В этом канале нет активного матча.", ephemeral=True)
            return
        await interaction.response.send_message(embed=build_board_embed(match))

    # ------------------------------------------------------------ presets
    @group.command(name="presets", description="Список доступных пресет-колод")
    async def presets(interaction: discord.Interaction) -> None:
        from app.services.deck_service import DeckService
        names = DeckService.list_presets()
        if not names:
            await interaction.response.send_message("Пресетов нет.", ephemeral=True)
            return
        embed = discord.Embed(title="📚 Доступные пресеты", color=0x1ABC9C)
        for name in names:
            data = DeckService.load_preset(name)
            if data:
                faction = await CardService.get_faction(data.get("faction_id", ""))
                embed.add_field(
                    name=name,
                    value=f"Фракция: {faction.name if faction else data.get('faction_id')}\n"
                          f"Карт: {len(data.get('card_ids', []))}",
                    inline=False,
                )
        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------ version
    @group.command(name="version", description="Показать версию бота (для отладки деплоя)")
    async def version_cmd(interaction: discord.Interaction) -> None:
        from app import __version__
        import os
        import time
        from datetime import datetime, timezone
        # Force reload some modules to check what version is actually running
        try:
            from app.ui.views.deck_builder import LeaderSelect
            leader_min_values = "min_values=1 (FIXED)"
        except Exception as e:
            leader_min_values = f"error: {e}"

        # Check if engine.py has the snowflake fix
        import inspect
        from app.game.engine import Match
        src = inspect.getsource(Match.snapshot)
        has_str_fix = "str(p.discord_id)" in src
        snowflake_status = "✓ FIXED (str)" if has_str_fix else "✗ OLD (int)"

        # Check if routes.py has new logging
        from app.web import routes as _r
        routes_src = inspect.getsource(_r)
        has_ws_logging = "WS msg #" in routes_src
        ws_log_status = "✓ NEW" if has_ws_logging else "✗ OLD"

        embed = discord.Embed(
            title="🔍 Версия бота",
            color=0x3498DB,
        )
        embed.add_field(name="app.__version__", value=__version__, inline=False)
        embed.add_field(name="Snowflake fix (snapshot)", value=snowflake_status, inline=True)
        embed.add_field(name="WS logging", value=ws_log_status, inline=True)
        embed.add_field(name="LeaderSelect", value=leader_min_values, inline=True)
        embed.add_field(
            name="Deploy time",
            value=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            inline=False,
        )
        embed.add_field(
            name="Что делать если все строки '✗ OLD'",
            value=(
                "Значит на render.com работает устаревший код. "
                "1) Проверьте, что push в GitHub дошёл (git log в локальном репо). "
                "2) На render.com: Manual Deploy → Deploy latest commit. "
                "3) Дождитесь полного завершения деплоя (статус 'Live'). "
                "4) Перезапустите команду /gwent version."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    tree.add_command(group)
