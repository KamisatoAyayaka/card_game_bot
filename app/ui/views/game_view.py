"""In-match interactive view: play card, pass, use leader, surrender."""
from __future__ import annotations

import discord
from discord import ui

from app.game.engine import Match, MatchError, MatchPhase
from app.services.match_service import MatchService
from app.ui.embeds.board_embed import build_board_embed, build_status_embed


class GameView(discord.ui.View):
    """Persistent-ish view attached to the live match message.

    All buttons are player-scoped: only the current player may interact.
    """

    def __init__(self, match: Match, message: discord.Message | None = None) -> None:
        super().__init__(timeout=600)  # 10 minutes idle timeout
        self.match = match
        self.message = message
        self._refresh_select()

    # ----------------------------------------------------- render
    async def render(self) -> discord.Embed:
        return build_board_embed(self.match)

    def _refresh_select(self) -> None:
        # Remove existing select then add a fresh one
        self.clear_items()
        self.add_item(CardPlaySelect(self))
        self.add_item(UseLeaderButton())
        self.add_item(PassButton())
        self.add_item(SurrenderButton())
        self.add_item(RefreshButton())

    # ----------------------------------------------------- refresh
    async def refresh(self, interaction: discord.Interaction) -> None:
        self._refresh_select()
        if self.message:
            await self.message.edit(embed=await self.render(), view=self)


# ---------------------------------------------------------------------------
# Card play select
# ---------------------------------------------------------------------------

class CardPlaySelect(ui.Select):
    def __init__(self, parent: GameView) -> None:
        self.parent = parent
        match = parent.match
        current = match.current_player

        options: list[discord.SelectOption] = []
        for ci in current.hand:
            label = ci.card.name
            desc_parts: list[str] = []
            if ci.card.is_unit:
                desc_parts.append(f"Сила {ci.card.base_strength}")
                if ci.card.row:
                    desc_parts.append(ci.card.row.value)
            if ci.card.hero:
                desc_parts.append("герой")
            desc = " · ".join(desc_parts) or ci.card.type.value
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=ci.instance_id,
                    description=desc[:100],
                    emoji="⭐" if ci.card.hero else None,
                )
            )
        if not options:
            options.append(
                discord.SelectOption(label="Рука пуста", value="__empty__")
            )

        super().__init__(
            placeholder=f"Ход: {current.display_name} — выберите карту",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="card_play_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        match = self.parent.match
        # Authorization
        if interaction.user.id != match.current_player.discord_id:
            await interaction.response.send_message(
                "Сейчас не ваш ход.", ephemeral=True
            )
            return
        if match.phase != MatchPhase.IN_PROGRESS:
            await interaction.response.send_message(
                "Матч не в активной фазе.", ephemeral=True
            )
            return

        chosen = self.values[0]
        if chosen == "__empty__":
            await interaction.response.send_message(
                "В руке нет карт — используйте «Пас».", ephemeral=True
            )
            return

        # Find the card instance
        player = match.current_player
        ci = next((c for c in player.hand if c.instance_id == chosen), None)
        if ci is None:
            await interaction.response.send_message(
                "Карта не найдена в руке.", ephemeral=True
            )
            return

        # If the card is AGILE or requires a row choice, prompt the user.
        from app.models.card import Row
        if ci.card.row == Row.AGILE:
            await interaction.response.send_message(
                "Выберите ряд для agile-карты (ближний/дальний):",
                view=AgileRowPicker(self.parent, ci.instance_id),
                ephemeral=True,
            )
            return

        # Otherwise play directly
        try:
            await match.play_card(player.discord_id, ci.instance_id)
        except MatchError as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=await self.parent.render(), view=self.parent
        )


class AgileRowPicker(discord.ui.View):
    def __init__(self, parent: GameView, instance_id: str) -> None:
        super().__init__(timeout=60)
        self.parent = parent
        self.instance_id = instance_id

    @discord.ui.button(label="Ближний бой", style=discord.ButtonStyle.primary, custom_id="agile_melee")
    async def melee(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._play(interaction, "melee")

    @discord.ui.button(label="Дальний бой", style=discord.ButtonStyle.primary, custom_id="agile_ranged")
    async def ranged(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._play(interaction, "ranged")

    async def _play(self, interaction: discord.Interaction, row: str) -> None:
        match = self.parent.match
        try:
            await match.play_card(interaction.user.id, self.instance_id, target_row=row)
        except MatchError as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
            return
        # Update the main match message
        if self.parent.message:
            await self.parent.message.edit(
                embed=await self.parent.render(), view=self.parent
            )
        await interaction.response.send_message(
            f"Карта разыграна в ряду «{row}».", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

class UseLeaderButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Способность лидера",
            style=discord.ButtonStyle.success,
            custom_id="btn_leader",
            emoji="👑",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: GameView = self.view  # type: ignore[assignment]
        match = view.match
        if interaction.user.id != match.current_player.discord_id:
            await interaction.response.send_message("Не ваш ход.", ephemeral=True)
            return
        try:
            await match.use_leader(interaction.user.id)
        except MatchError as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
            return
        await interaction.response.edit_message(embed=await view.render(), view=view)


class PassButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Пас",
            style=discord.ButtonStyle.secondary,
            custom_id="btn_pass",
            emoji="💤",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: GameView = self.view  # type: ignore[assignment]
        match = view.match
        if interaction.user.id != match.current_player.discord_id:
            await interaction.response.send_message("Не ваш ход.", ephemeral=True)
            return
        try:
            await match.pass_turn(interaction.user.id)
        except MatchError as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
            return
        if match.phase == MatchPhase.FINISHED:
            await interaction.response.edit_message(embed=await view.render(), view=None)
        else:
            await interaction.response.edit_message(embed=await view.render(), view=view)


class SurrenderButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Сдаться",
            style=discord.ButtonStyle.danger,
            custom_id="btn_surrender",
            emoji="🏳️",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: GameView = self.view  # type: ignore[assignment]
        match = view.match
        # Allow any participant to surrender
        if interaction.user.id not in {p.discord_id for p in match.players}:
            await interaction.response.send_message("Вы не участвуете в этом матче.", ephemeral=True)
            return
        try:
            await match.surrender(interaction.user.id)
        except MatchError as e:
            await interaction.response.send_message(f"Ошибка: {e}", ephemeral=True)
            return
        await interaction.response.edit_message(embed=await view.render(), view=None)


class RefreshButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="",
            style=discord.ButtonStyle.secondary,
            custom_id="btn_refresh",
            emoji="🔄",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: GameView = self.view  # type: ignore[assignment]
        await interaction.response.edit_message(embed=await view.render(), view=view)
