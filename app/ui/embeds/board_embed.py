"""Game-board embeds: full match state, simplified status, round results."""
from __future__ import annotations

import discord

from app.game.engine import Match, MatchPhase
from app.utils.helpers import hex_to_int, row_label


_ROW_ICONS = {
    "siege": "🏰",
    "ranged": "🏹",
    "melee": "⚔️",
}

_WEATHER_ICONS = {
    "melee": "❄️",
    "ranged": "🌫️",
    "siege": "🌧️",
}


def _format_unit(u: dict) -> str:
    hero_marker = "★" if u.get("hero") else ""
    weathered_marker = " (1️⃣ weather)" if u.get("weathered") and not u.get("hero") else ""
    return f"`{u['current']:>2}` {hero_marker}{u['name']}{weathered_marker}"


def build_board_embed(match: Match) -> discord.Embed:
    snap = match.snapshot()
    players = snap["players"]

    # Use the *opponent* (non-current) faction color for the embed if there are 2 players.
    # For more players, fall back to neutral.
    if len(players) >= 1:
        first_player = players[0]
    else:
        first_player = None

    color = 0x2B2D31

    title = f"🃏 Матч {snap['match_id']} — Раунд {snap['round']}/{snap['rounds_total']}"
    if snap["phase"] == MatchPhase.FINISHED.value:
        title = f"🃏 Матч {snap['match_id']} — Завершён"

    embed = discord.Embed(title=title, color=color)

    # Weather strip
    weather_parts = []
    for row, active in snap["weather"].items():
        if active:
            weather_parts.append(f"{_WEATHER_ICONS.get(row, '')} {row_label(row)}")
    weather_str = " · ".join(weather_parts) if weather_parts else "Ясно ☀️"
    embed.add_field(name="Погода", value=weather_str, inline=False)

    # Render each player's board as its own block
    for p in players:
        name = f"**{p['name']}** — {p['total_strength']} очк. · раундов выиграно: {p['rounds_won']}"
        if p["discord_id"] == snap["current_player_id"] and snap["phase"] == MatchPhase.IN_PROGRESS.value:
            name = "▶️ " + name
        if p["passed"]:
            name = "💤 " + name + " (пас)"

        body_parts: list[str] = []
        for row_name in ("siege", "ranged", "melee"):
            units = p["rows"][row_name]
            icon = _ROW_ICONS.get(row_name, "")
            label = row_label(row_name)
            row_str = sum(u["current"] for u in units)
            if units:
                unit_lines = "\n".join("   " + _format_unit(u) for u in units)
                body_parts.append(f"{icon} **{label}** ({row_str}):\n{unit_lines}")
            else:
                body_parts.append(f"{icon} **{label}** (0): _пусто_")
        body_parts.append(f"📚 Рука: {p['hand_size']} · Колода: {p['deck_size']}")
        if p.get("leader_name"):
            leader_state = "использован" if p.get("leader_used_this_round") else "доступен"
            body_parts.append(f"👑 Лидер: {p['leader_name']} ({leader_state})")

        embed.add_field(name=name, value="\n".join(body_parts), inline=False)

    # Recent log tail
    if snap.get("log_tail"):
        log_text = "\n".join(f"· {l}" for l in snap["log_tail"][-6:])
        embed.add_field(name="Журнал", value=log_text, inline=False)

    embed.set_footer(text=f"Phase: {snap['phase']} · match_id={snap['match_id']}")
    return embed


def build_round_result_embed(match: Match, event: dict) -> discord.Embed:
    embed = discord.Embed(title=f"🏁 Раунд {event['round']} завершён", color=0x95A5A6)
    lines: list[str] = []
    for pid, s in event["strengths"].items():
        marker = "🏆 " if pid in event["winners"] else "   "
        player = match.get_player(int(pid))
        if player:
            lines.append(f"{marker}**{player.display_name}**: {s} очк.")
    embed.description = "\n".join(lines)
    return embed


def build_match_finished_embed(match: Match, event: dict) -> discord.Embed:
    winner_id = event.get("winner_id")
    winner = match.get_player(winner_id) if winner_id else None
    if winner:
        embed = discord.Embed(
            title="🎉 Матч завершён!",
            description=f"Победитель: **{winner.display_name}**",
            color=0xF1C40F,
        )
    else:
        embed = discord.Embed(
            title="🤝 Матч завершён",
            description="Ничья!",
            color=0x95A5A6,
        )
    rounds_str = "\n".join(
        f"• {p.display_name}: {p.rounds_won} раунд(а)"
        for p in match.players
    )
    embed.add_field(name="Раунды", value=rounds_str, inline=False)
    return embed


def build_status_embed(match: Match) -> discord.Embed:
    snap = match.snapshot()
    cur_player = next(
        (p for p in snap["players"] if p["discord_id"] == snap["current_player_id"]),
        None,
    )
    embed = discord.Embed(
        title=f"📊 Статус матча {snap['match_id']}",
        color=0x3498DB,
    )
    if cur_player and snap["phase"] == MatchPhase.IN_PROGRESS.value:
        embed.description = f"Сейчас ход: **{cur_player['name']}**"
    elif snap["phase"] == MatchPhase.FINISHED.value:
        embed.description = "Матч завершён."
    else:
        embed.description = "Ожидание хода."
    embed.add_field(
        name="Раунд",
        value=f"{snap['round']} / {snap['rounds_total']}",
        inline=True,
    )
    score_lines = [
        f"• {p['name']}: {p['rounds_won']} раунд(а) · {p['total_strength']} очк. сейчас"
        for p in snap["players"]
    ]
    embed.add_field(name="Счёт", value="\n".join(score_lines), inline=False)
    return embed
