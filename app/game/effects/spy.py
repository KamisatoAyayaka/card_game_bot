"""Spy effect — the card is placed on the opponent's side; owner draws 2 cards."""
from __future__ import annotations

from .base import Effect, EffectContext


class SpyEffect(Effect):
    type_id = "spy"

    async def on_played(self, ctx: EffectContext) -> None:
        # Move the just-played card to the opponent's side of the board.
        # In a 2-player game we relocate it to the other player's row.
        # In multiplayer we relocate to the "next" player.
        opponents = [p for p in ctx.match.players if p.discord_id != ctx.player.discord_id]
        if not opponents:
            return
        # Choose the opponent with the fewest cards on their side (simplest fair heuristic).
        target = min(opponents, key=lambda p: ctx.board.total_units_for(p.discord_id))

        # Remove from current location, add to opponent's matching row
        ci = ctx.card_instance
        if ci.row is None:
            return
        ctx.board.remove_unit(ctx.player.discord_id, ci.row, ci)
        ctx.board.add_unit(target.discord_id, ci.row, ci)
        ci.owner_discord_id = target.discord_id

        # Owner draws 2 cards
        drawn = ctx.player.draw(2)
        ctx.log.append(
            f"Шпион «{ci.card.name}» перешёл на сторону противника. "
            f"Игрок взял {len(drawn)} карт(ы)."
        )
