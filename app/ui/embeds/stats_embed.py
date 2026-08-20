"""Stats embeds."""
from __future__ import annotations

import discord

from app.models.card import PlayerStats


def build_stats_embed(stats: PlayerStats) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊 Статистика игрока",
        description=stats.display_name or f"<@{stats.discord_id}>",
        color=0x9B59B6,
    )
    win_rate = (
        f"{(stats.wins / stats.matches_played * 100):.1f}%"
        if stats.matches_played
        else "—"
    )
    embed.add_field(name="Победы", value=str(stats.wins), inline=True)
    embed.add_field(name="Поражения", value=str(stats.losses), inline=True)
    embed.add_field(name="Ничьи", value=str(stats.draws), inline=True)
    embed.add_field(name="ELO", value=str(stats.elo), inline=True)
    embed.add_field(name="Всего матчей", value=str(stats.matches_played), inline=True)
    embed.add_field(name="Винрейт", value=win_rate, inline=True)
    if stats.last_played_at:
        embed.set_footer(text=f"Последний матч: {stats.last_played_at}")
    return embed


def build_leaderboard_embed(players: list[PlayerStats]) -> discord.Embed:
    embed = discord.Embed(title="🏆 Таблица лидеров", color=0xF1C40F)
    if not players:
        embed.description = "Пока никто не сыграл ни одного матча."
        return embed
    lines: list[str] = []
    medals = ["🥇", "🥈", "🥉"]
    for i, p in enumerate(players):
        medal = medals[i] if i < 3 else f"`{i+1}.`"
        lines.append(f"{medal} **{p.display_name or f'<@{p.discord_id}>'}** — {p.elo} ELO · {p.wins}W / {p.losses}L")
    embed.description = "\n".join(lines)
    return embed
