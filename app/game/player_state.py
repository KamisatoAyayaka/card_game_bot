"""Per-match player state: deck, hand, discard, leader, round flags."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.game.card_instance import CardInstance
from app.models.card import Card

if TYPE_CHECKING:
    from app.models.card import Card as CardModel


@dataclass
class PlayerState:
    discord_id: int
    display_name: str
    faction_id: str
    leader_card: Card | None = None
    deck: list[CardInstance] = field(default_factory=list)
    hand: list[CardInstance] = field(default_factory=list)
    discard: list[CardInstance] = field(default_factory=list)
    passed: bool = False
    leader_used_this_round: bool = False
    rounds_won: int = 0

    # ----------------------------------------------------------- lifecycle
    def build_from_card_ids(
        self,
        card_ids: list[str],
        card_lookup: dict[str, Card],
        leader_card_id: str | None = None,
        seed: int | None = None,
    ) -> None:
        """Populate deck with one CardInstance per card_id. Leader is tracked separately."""
        if leader_card_id and leader_card_id in card_lookup:
            self.leader_card = card_lookup[leader_card_id]
        instances: list[CardInstance] = []
        for idx, cid in enumerate(card_ids):
            card = card_lookup.get(cid)
            if card is None:
                continue
            instances.append(
                CardInstance(
                    instance_id=f"{self.discord_id}-{cid}-{idx}",
                    card=card,
                    owner_discord_id=self.discord_id,
                )
            )
        rng = random.Random(seed)
        rng.shuffle(instances)
        self.deck = instances
        self.hand = []
        self.discard = []

    def draw(self, n: int = 1) -> list[CardInstance]:
        drawn = []
        for _ in range(n):
            if not self.deck:
                break
            ci = self.deck.pop(0)
            ci.location = "hand"
            self.hand.append(ci)
            drawn.append(ci)
        return drawn

    def play_from_hand(self, instance_id: str) -> CardInstance | None:
        for i, ci in enumerate(self.hand):
            if ci.instance_id == instance_id:
                return self.hand.pop(i)
        return None

    def pass_round(self) -> None:
        self.passed = True

    def reset_for_new_round(self, start_first: bool = False) -> None:
        """Reset round-specific flags. Cards on the board go to discard;
        discard then returns to deck at end of round (Gwent rule: played cards
        are not reusable within a match, but discard + hand + deck reset between
        ROUNDS in this implementation — see engine for the strict variant)."""
        # In classic Gwent: cards played in a round are NOT returned to the deck
        # for subsequent rounds. Only hand carries over. We follow that rule.
        # Discard stays as-is across rounds.
        self.passed = False
        self.leader_used_this_round = False

    @property
    def hand_size(self) -> int:
        return len(self.hand)

    @property
    def deck_size(self) -> int:
        return len(self.deck)
