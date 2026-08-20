"""`/stats` and `/leaderboard` slash commands."""
from __future__ import annotations

import discord

from app.services.stats_service import StatsService
from app.ui.embeds.stats_embed import build_leaderboard_embed, build_stats_embed


def register_stats_commands(tree: discord.app_commands.CommandTree) -> None:
    @tree.command(name="stats", description="Ваша игровая статистика")
    async def stats(interaction: discord.Interaction) -> None:
        stats = await StatsService.get_or_create(
            interaction.user.id, interaction.user.display_name
        )
        await interaction.response.send_message(
            embed=build_stats_embed(stats), ephemeral=True
        )

    @tree.command(name="leaderboard", description="Таблица лидеров")
    async def leaderboard(interaction: discord.Interaction) -> None:
        top = await StatsService.leaderboard(limit=10)
        await interaction.response.send_message(embed=build_leaderboard_embed(top))
