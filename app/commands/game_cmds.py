"""`/gwent` slash command group — challenge, surrender, info."""
from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands

from app.config import CONFIG
from app.database import Database
from app.game.engine import Match, MatchPhase
from app.services.card_service import CardService
from app.services.match_service import MatchService
from app.services.stats_service import StatsService
from app.ui.embeds.board_embed import build_board_embed, build_match_finished_embed, build_round_result_embed
from app.ui.views.game_view import GameView
from app.ui.views.invite_view import InviteView


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
        # Validate
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
        # De-duplicate & exclude self
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

        # Channel must not already host a match
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

        # Render invite message
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
        original = await interaction.original_response()

        # Wait for all to accept (or for the view to time out)
        timeout_task = asyncio.create_task(asyncio.wait_for(view.wait(), timeout=120))
        try:
            await timeout_task
        except asyncio.TimeoutError:
            await MatchService.cancel_invite(invite.invite_id)
            await interaction.followup.send("Время приёма вызова истекло. Матч отменён.")
            return

        if view.declined:
            return  # decline path already handled cancellation

        # All accepted — start the match
        # Each participant must have an active deck or use the preset
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
                # Heuristic: pick the most recently saved deck
                if not decks:
                    await interaction.followup.send(
                        f"У <@{pid}> нет сохранённых колод. Используйте `/deck build` "
                        f"или `/gwent challenge ... preset:<имя>`.",
                        ephemeral=False,
                    )
                    return
                deck = decks[-1]  # simplest fallback
                participants_data.append(
                    (
                        pid,
                        f"<@{pid}>",
                        deck.faction_id,
                        list(deck.card_ids),
                        deck.leader_card_id,
                    )
                )

        # Load all cards into a lookup map
        all_card_ids: set[str] = set()
        for _, _, _, cids, _ in participants_data:
            all_card_ids.update(cids)
            # Leader not in card_ids
        for entry in participants_data:
            if entry[4]:
                all_card_ids.add(entry[4])
        all_cards = await CardService.get_many(list(all_card_ids))
        card_lookup = {c.id: c for c in all_cards}
        # Also ensure leaders are loaded
        missing_leaders = [
            entry[4] for entry in participants_data
            if entry[4] and entry[4] not in card_lookup
        ]
        if missing_leaders:
            extra = await CardService.get_many(missing_leaders)
            for c in extra:
                card_lookup[c.id] = c

        # Build match
        match = Match.create(
            channel_id=interaction.channel.id,
            participants=participants_data,
            card_lookup=card_lookup,
            rounds_total=rounds_total,
        )

        # Wire event listener -> updates the live message
        async def on_event(m: Match, event: str, payload: dict) -> None:
            if event == "round_ended":
                await interaction.followup.send(embed=build_round_result_embed(m, payload))
            elif event == "match_finished":
                await interaction.followup.send(embed=build_match_finished_embed(m, payload))
                # Update stats
                winner_id = payload.get("winner_id")
                await StatsService.record_result(
                    winner_id=winner_id,
                    participant_ids=[p.discord_id for p in m.players],
                    draw=(winner_id is None),
                )
                await MatchService.end(m.channel_id, m.match_id)

        match.add_listener(on_event)
        await MatchService.register(interaction.channel.id, match)
        await match.start_match()

        # Render the initial game view
        game_view = GameView(match)
        embed = build_board_embed(match)
        await interaction.followup.send(embed=embed, view=game_view)
        game_view.message = await interaction.original_response()

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
    @group.command(name="info", description="Показать текущее состояние матча")
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

    tree.add_command(group)
