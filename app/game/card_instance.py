"""Per-match card instance — wraps a static Card with mutable in-match state."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.card import Card


@dataclass
class CardInstance:
    """A card that exists in a particular match (in deck, hand, board, or discard).

    Multiple instances can reference the same Card definition (e.g. 3x Legionary).
    """
    instance_id: str
    card: Card
    owner_discord_id: int
    # Where it currently lives
    location: str = "deck"  # "deck" | "hand" | "board" | "discard"
    # When on board, which row it occupies ("melee" / "ranged" / "siege")
    row: str | None = None
    # Mutable combat state
    bonus_strength: int = 0       # additive (morale boost, etc.)
    weathered: bool = False       # set by board when weather affects this unit
    # Cached effect instances built once when the card is played
    _effects_built: bool = field(default=False, repr=False)

    @property
    def current_strength(self) -> int:
        if self.card.hero:
            # Heroes are immune to weather; morale boost does NOT apply to them
            return max(0, self.card.base_strength + self.bonus_strength)
        if self.weathered:
            return 1
        return max(0, self.card.base_strength + self.bonus_strength)

    @property
    def is_unit(self) -> bool:
        return self.card.is_unit

    def reset_for_new_round(self) -> None:
        """Clear in-round state; the card returns to the player's deck."""
        self.location = "deck"
        self.row = None
        self.bonus_strength = 0
        self.weathered = False
