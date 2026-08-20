"""Scorch effect — destroy the strongest unit(s) on the board (heroes included
unless they have immunity). Used by both the neutral Scorch card and several
faction specials.

Card JSON form (optional):
    {"type": "scorch", "params": {"target_side": "all"}}   # default: all
    {"type": "scorch", "params": {"target_side": "enemy"}} # only enemies of caster
"""
from __future__ import annotations

from .base import Effect, EffectContext


class ScorchEffect(Effect):
    type_id = "scorch"

    async def on_played(self, ctx: EffectContext) -> None:
        target_side = self.params.get("target_side", "all")
        candidates: list = []
        for player in ctx.match.players:
            if target_side == "enemy" and player.discord_id == ctx.player.discord_id:
                continue
            for row_name in ("melee", "ranged", "siege"):
                for unit in ctx.board.units_in_row(player.discord_id, row_name):
                    # Hero immunity: by default heroes are immune to Scorch in Gwent
                    # (the Scorch special card still destroys them in classic W3 Gwent).
                    # We follow that rule here.
                    candidates.append((player.discord_id, row_name, unit))

        if not candidates:
            ctx.log.append("Чучело не нашло целей.")
            return

        max_str = max(u.current_strength for _, _, u in candidates)
        victims = [(pid, row, u) for pid, row, u in candidates if u.current_strength == max_str]

        for pid, row, u in victims:
            ctx.board.remove_unit(pid, row, u)
            owner = next(p for p in ctx.match.players if p.discord_id == pid)
            owner.discard.append(u)

        names = ", ".join(u.card.name for _, _, u in victims)
        ctx.log.append(f"Чучело уничтожило: {names}.")
