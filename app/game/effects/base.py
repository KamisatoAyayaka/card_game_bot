"""Base classes for the effect framework.

An `Effect` is a stateless strategy object: the engine instantiates one
instance per effect *spec* on a card at the moment the card is played,
then calls the relevant lifecycle hooks. Concrete effect classes live in
sibling modules and register themselves with `EFFECT_REGISTRY`.

Effects should never reach into Discord or asyncio — they are pure
mutations on the game state held by `EffectContext`. The engine then
decides how/when to broadcast state changes to Discord.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.game.board import Board
    from app.game.card_instance import CardInstance
    from app.game.engine import Match
    from app.game.player_state import PlayerState


# ---------------------------------------------------------------------------
# Context passed to every effect hook
# ---------------------------------------------------------------------------

@dataclass
class EffectContext:
    """All state an effect needs to do its job.

    The engine constructs this per card-play and passes it to each effect
    on that card in declaration order.
    """
    match: "Match"
    board: "Board"
    player: "PlayerState"           # the player who played the card
    card_instance: "CardInstance"   # the played card instance (with row assignment)
    target_row: str | None = None   # row the player chose (for agile cards)
    log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Base Effect class
# ---------------------------------------------------------------------------

class Effect:
    """Subclass and override the hooks you need. Set `type_id` to a unique string."""
    type_id: str = ""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = params or {}

    # ----------------------------------------------------------- lifecycle
    async def on_played(self, ctx: EffectContext) -> None:
        """Called when the host card is played, after it is placed on the board."""
        return None

    async def on_removed(self, ctx: EffectContext) -> None:
        """Called when the host card leaves the board (destroyed, returned, etc.)."""
        return None

    async def on_round_end(self, ctx: EffectContext) -> None:
        """Called at the end of each round for every effect currently on the board."""
        return None

    async def on_opponent_card_played(self, ctx: EffectContext, opponent_card: "CardInstance") -> None:
        """Reactive hook: an opponent just played a card."""
        return None

    # --------------------------------------------------------- introspection
    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} type_id={self.type_id!r} params={self.params}>"
