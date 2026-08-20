"""Medic effect — revive a non-hero unit from the player's discard pile."""
from __future__ import annotations

from .base import Effect, EffectContext


class MedicEffect(Effect):
    type_id = "medic"

    async def on_played(self, ctx: EffectContext) -> None:
        # Player must have at least one non-hero unit in discard.
        revivable = [
            ci for ci in ctx.player.discard
            if ci.card.is_unit and not ci.card.hero
        ]
        if not revivable:
            ctx.log.append("Медик не нашёл кого воскресить.")
            return

        # For MVP we auto-pick the strongest revivable unit.
        # Future enhancement: prompt the player via Discord UI.
        chosen = max(revivable, key=lambda ci: ci.card.base_strength)
        ctx.player.discard.remove(chosen)
        # Place the revived unit on its proper row (no extra effect re-trigger).
        row = chosen.card.row
        if row is None:
            return
        # AGILE units default to melee when revived
        from app.models.card import Row
        actual_row = row.value if row != Row.AGILE else Row.MELEE.value
        ctx.board.add_unit(ctx.player.discord_id, actual_row, chosen)
        ctx.log.append(f"Медик воскресил «{chosen.card.name}».")
