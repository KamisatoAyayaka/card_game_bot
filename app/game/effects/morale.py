"""Morale boost effect — +1 strength to all other friendly units in the same row."""
from __future__ import annotations

from .base import Effect, EffectContext


class MoraleBoostEffect(Effect):
    type_id = "morale_boost"

    async def on_played(self, ctx: EffectContext) -> None:
        ci = ctx.card_instance
        if ci.row is None:
            return
        row_units = ctx.board.units_in_row(ctx.player.discord_id, ci.row)
        boosted = 0
        for unit in row_units:
            if unit is ci:
                continue
            unit.bonus_strength += 1
            boosted += 1
        if boosted:
            ctx.log.append(
                f"«{ci.card.name}» поднял боевой дух {boosted} союзник(ов) в ряду «{ci.row}»."
            )
