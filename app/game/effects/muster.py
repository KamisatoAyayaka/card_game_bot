"""Muster effect — summon all copies of cards matching a tag from hand & deck."""
from __future__ import annotations

from .base import Effect, EffectContext
from app.models.card import Row


class MusterEffect(Effect):
    type_id = "muster"

    async def on_played(self, ctx: EffectContext) -> None:
        tag = self.params.get("tag")
        if not tag:
            # Fall back to the first tag of the host card
            tag = ctx.card_instance.card.tags[0] if ctx.card_instance.card.tags else None
        if not tag:
            return

        host = ctx.card_instance
        if host.row is None:
            return

        # Find matching cards in hand and deck
        # (In Gwent, muster only pulls copies of the *same* card name,
        # but we generalize: pull all unit cards with the same tag.)
        from app.models.card import CardType
        summoned: list = []

        # Hand
        for ci in list(ctx.player.hand):
            if ci is host:
                continue
            if (
                ci.card.type == CardType.UNIT
                and tag in ci.card.tags
                and ci.card.row == host.card.row
            ):
                ctx.player.hand.remove(ci)
                row_value = ci.card.row.value if ci.card.row != Row.AGILE else host.row
                ctx.board.add_unit(ctx.player.discord_id, row_value, ci)
                summoned.append(ci)

        # Deck
        for ci in list(ctx.player.deck):
            if (
                ci.card.type == CardType.UNIT
                and tag in ci.card.tags
                and ci.card.row == host.card.row
            ):
                ctx.player.deck.remove(ci)
                row_value = ci.card.row.value if ci.card.row != Row.AGILE else host.row
                ctx.board.add_unit(ctx.player.discord_id, row_value, ci)
                summoned.append(ci)

        if summoned:
            names = ", ".join(ci.card.name for ci in summoned)
            ctx.log.append(f"Сплочение призвало: {names}.")
