"""Invite view — sent when a player challenges another to a match."""
from __future__ import annotations

import discord
from discord import ui

from app.services.match_service import MatchService


class InviteView(discord.ui.View):
    """Each challenged user gets Accept / Decline buttons."""

    def __init__(self, invite_id: str, challenged_ids: list[int]) -> None:
        super().__init__(timeout=120)
        self.invite_id = invite_id
        self.challenged_ids = challenged_ids
        self.accepted: set[int] = set()
        self.declined: set[int] = set()

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="invite_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id not in self.challenged_ids:
            await interaction.response.send_message(
                "Это приглашение направлено другому игроку.", ephemeral=True
            )
            return
        if interaction.user.id in self.accepted:
            await interaction.response.send_message(
                "Вы уже приняли приглашение.", ephemeral=True
            )
            return
        self.accepted.add(interaction.user.id)
        await interaction.response.send_message(
            f"{interaction.user.mention} принял вызов ({len(self.accepted)}/{len(self.challenged_ids)}).",
            ephemeral=False,
        )
        # If all have accepted, the orchestrator command will start the match
        if len(self.accepted) == len(self.challenged_ids):
            self.stop()

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="invite_decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id not in self.challenged_ids:
            await interaction.response.send_message(
                "Это приглашение направлено другому игроку.", ephemeral=True
            )
            return
        self.declined.add(interaction.user.id)
        await MatchService.cancel_invite(self.invite_id)
        await interaction.response.send_message(
            f"{interaction.user.mention} отклонил вызов. Матч отменён."
        )
        self.stop()
