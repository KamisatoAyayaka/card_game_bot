"""Decoy effect — swap a friendly non-hero unit on the board back to hand.

The Decoy card itself occupies the row where the swapped unit was.

Implementation note: the engine calls on_played *after* placing the card.
For Decoy this is awkward because the card doesn't have a natural row.
We therefore special-case Decoy placement in the engine: the player is
prompted to pick a target unit, the Decoy takes its place, and the target
returns to hand. Here we just validate / log.
"""
from __future__ import annotations

from .base import Effect, EffectContext


class DecoyEffect(Effect):
    type_id = "decoy"

    async def on_played(self, ctx: EffectContext) -> None:
        # The engine pre-handles the swap before invoking this hook.
        # We just emit a log entry.
        ctx.log.append(f"«{ctx.card_instance.card.name}» заменила единицу и вернула её в руку.")
