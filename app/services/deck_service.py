"""Deck service: validation, save/load, presets."""
from __future__ import annotations

import json
from pathlib import Path

from app.config import PRESETS_DIR
from app.database import get_db
from app.models.card import Card, CardType, SavedDeck
from app.services.card_service import CardService

# Gwent deck-building rules
DECK_MIN_CARDS = 22
DECK_MAX_CARDS = 40
DECK_MIN_UNITS = 22  # at least 22 unit cards
HERO_PER_DECK_MAX = 4
SPECIAL_PER_DECK_MAX = 10
DECK_PRESET_FILE_SUFFIX = ".json"


class DeckValidationError(ValueError):
    pass


class DeckService:
    # ----------------------------------------------------------- validation
    @staticmethod
    async def validate_deck(
        faction_id: str,
        card_ids: list[str],
        leader_card_id: str | None = None,
    ) -> tuple[list[Card], list[Card]]:
        """Return (units, specials) or raise DeckValidationError."""
        if leader_card_id:
            leader = await CardService.get_card(leader_card_id)
            if leader is None or leader.type != CardType.LEADER:
                raise DeckValidationError("Leader card is invalid.")
            if leader.faction_id != faction_id:
                raise DeckValidationError(
                    "Leader must belong to the same faction as the deck."
                )

        cards = await CardService.get_many(card_ids)
        if len(cards) != len(card_ids):
            missing = set(card_ids) - {c.id for c in cards}
            raise DeckValidationError(f"Unknown card ids: {missing}")

        # All cards must belong to deck faction or be neutral
        for c in cards:
            if c.faction_id not in (faction_id, "neutral"):
                raise DeckValidationError(
                    f"Card '{c.name}' belongs to faction '{c.faction_id}', "
                    f"not '{faction_id}'."
                )

        if not (DECK_MIN_CARDS <= len(cards) <= DECK_MAX_CARDS):
            raise DeckValidationError(
                f"Deck must have between {DECK_MIN_CARDS} and {DECK_MAX_CARDS} cards "
                f"(have {len(cards)})."
            )

        units = [c for c in cards if c.type == CardType.UNIT]
        specials = [c for c in cards if c.type in (CardType.SPECIAL, CardType.WEATHER)]
        heroes = [c for c in units if c.hero]

        if len(units) < DECK_MIN_UNITS:
            raise DeckValidationError(
                f"Deck must contain at least {DECK_MIN_UNITS} unit cards "
                f"(have {len(units)})."
            )
        if len(heroes) > HERO_PER_DECK_MAX:
            raise DeckValidationError(
                f"Deck may contain at most {HERO_PER_DECK_MAX} hero cards "
                f"(have {len(heroes)})."
            )
        if len(specials) > SPECIAL_PER_DECK_MAX:
            raise DeckValidationError(
                f"Deck may contain at most {SPECIAL_PER_DECK_MAX} special/weather cards "
                f"(have {len(specials)})."
            )
        return units, specials

    # ------------------------------------------------------------ save/load
    @classmethod
    async def save_deck(
        cls,
        discord_id: int,
        name: str,
        faction_id: str,
        card_ids: list[str],
        leader_card_id: str | None = None,
    ) -> SavedDeck:
        await cls.validate_deck(faction_id, card_ids, leader_card_id)
        deck = SavedDeck(
            discord_id=discord_id,
            name=name,
            faction_id=faction_id,
            leader_card_id=leader_card_id,
            card_ids=card_ids,
        )
        db = await get_db()
        row = deck.to_db_row()
        row["name"] = name
        row["discord_id"] = discord_id
        await db.execute(
            """
            INSERT INTO saved_decks (discord_id, name, faction_id, leader_card_id, card_ids)
            VALUES (:discord_id, :name, :faction_id, :leader_card_id, :card_ids)
            ON CONFLICT(discord_id, name) DO UPDATE SET
                faction_id=excluded.faction_id,
                leader_card_id=excluded.leader_card_id,
                card_ids=excluded.card_ids
            """,
            row,
        )
        await db.commit()
        return deck

    @classmethod
    async def list_decks(cls, discord_id: int) -> list[SavedDeck]:
        db = await get_db()
        async with db.execute(
            "SELECT * FROM saved_decks WHERE discord_id=? ORDER BY name",
            (discord_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [SavedDeck.from_db_row(r) for r in rows]

    @classmethod
    async def get_deck(cls, discord_id: int, name: str) -> SavedDeck | None:
        db = await get_db()
        async with db.execute(
            "SELECT * FROM saved_decks WHERE discord_id=? AND name=?",
            (discord_id, name),
        ) as cur:
            row = await cur.fetchone()
        return SavedDeck.from_db_row(row) if row else None

    @classmethod
    async def delete_deck(cls, discord_id: int, name: str) -> bool:
        db = await get_db()
        cur = await db.execute(
            "DELETE FROM saved_decks WHERE discord_id=? AND name=?",
            (discord_id, name),
        )
        await db.commit()
        return cur.rowcount > 0

    # --------------------------------------------------------------- presets
    @classmethod
    def list_presets(cls) -> list[str]:
        if not PRESETS_DIR.exists():
            return []
        return sorted(
            p.stem for p in PRESETS_DIR.glob(f"*{DECK_PRESET_FILE_SUFFIX}")
        )

    @classmethod
    def load_preset(cls, name: str) -> dict | None:
        path = PRESETS_DIR / f"{name}{DECK_PRESET_FILE_SUFFIX}"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
