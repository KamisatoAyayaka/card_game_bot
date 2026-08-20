"""Pydantic models for factions, cards, effects, decks, and player stats."""
from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CardType(str, Enum):
    UNIT = "unit"
    WEATHER = "weather"
    LEADER = "leader"
    SPECIAL = "special"


class Row(str, Enum):
    MELEE = "melee"
    RANGED = "ranged"
    SIEGE = "siege"
    AGILE = "agile"  # playable in either melee or ranged

    @classmethod
    def allowed_for(cls, raw: str | None) -> "Row | None":
        if raw is None:
            return None
        try:
            return cls(raw)
        except ValueError:
            return None


class Rarity(str, Enum):
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


# ---------------------------------------------------------------------------
# Effect spec (as authored in JSON, before being hydrated into an Effect class)
# ---------------------------------------------------------------------------

class EffectSpec(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Faction
# ---------------------------------------------------------------------------

class Faction(BaseModel):
    id: str
    name: str
    description: str | None = None
    color: str | None = None      # hex string "#rrggbb"
    icon_url: str | None = None
    ability_name: str | None = None
    ability_desc: str | None = None


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class Card(BaseModel):
    """Authoritative card definition (matches the `cards` SQLite table)."""
    id: str
    name: str
    faction_id: str
    type: CardType
    row: Row | None = None
    base_strength: int = 0
    tags: list[str] = Field(default_factory=list)
    hero: bool = False
    effects: list[EffectSpec] = Field(default_factory=list)
    description: str | None = None
    art_url: str | None = None
    rarity: Rarity = Rarity.COMMON

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else [v]
            except json.JSONDecodeError:
                return [t.strip() for t in v.split(",") if t.strip()]
        return list(v)

    @field_validator("effects", mode="before")
    @classmethod
    def _coerce_effects(cls, v: Any) -> list[EffectSpec]:
        if v is None:
            return []
        if isinstance(v, str):
            v = json.loads(v)
        if not isinstance(v, list):
            raise ValueError("effects must be a list")
        return [EffectSpec(**e) if isinstance(e, dict) else e for e in v]

    @field_validator("row", mode="before")
    @classmethod
    def _coerce_row(cls, v: Any) -> Row | None:
        return Row.allowed_for(v)

    @property
    def is_unit(self) -> bool:
        return self.type == CardType.UNIT

    @property
    def is_weather(self) -> bool:
        return self.type == CardType.WEATHER

    @property
    def is_leader(self) -> bool:
        return self.type == CardType.LEADER

    def to_db_row(self) -> dict[str, Any]:
        """Serialize for INSERT into the SQLite `cards` table."""
        return {
            "id": self.id,
            "name": self.name,
            "faction_id": self.faction_id,
            "type": self.type.value,
            "row": self.row.value if self.row else None,
            "base_strength": self.base_strength,
            "tags": json.dumps(self.tags, ensure_ascii=False),
            "hero": 1 if self.hero else 0,
            "effects": json.dumps(
                [e.model_dump() for e in self.effects], ensure_ascii=False
            ),
            "description": self.description,
            "art_url": self.art_url,
            "rarity": self.rarity.value,
        }

    @classmethod
    def from_db_row(cls, row: Any) -> "Card":
        """Hydrate from an aiosqlite.Row or dict."""
        d = dict(row)
        return cls(
            id=d["id"],
            name=d["name"],
            faction_id=d["faction_id"],
            type=d["type"],
            row=d.get("row"),
            base_strength=d.get("base_strength", 0),
            tags=d.get("tags") or [],
            hero=bool(d.get("hero", 0)),
            effects=d.get("effects") or [],
            description=d.get("description"),
            art_url=d.get("art_url"),
            rarity=d.get("rarity", "common"),
        )


# ---------------------------------------------------------------------------
# Player stats
# ---------------------------------------------------------------------------

class PlayerStats(BaseModel):
    discord_id: int
    display_name: str | None = None
    wins: int = 0
    losses: int = 0
    draws: int = 0
    elo: int = 1000
    matches_played: int = 0
    last_played_at: str | None = None

    @classmethod
    def from_db_row(cls, row: Any) -> "PlayerStats":
        d = dict(row)
        return cls(
            discord_id=d["discord_id"],
            display_name=d.get("display_name"),
            wins=d.get("wins", 0),
            losses=d.get("losses", 0),
            draws=d.get("draws", 0),
            elo=d.get("elo", 1000),
            matches_played=d.get("matches_played", 0),
            last_played_at=d.get("last_played_at"),
        )


# ---------------------------------------------------------------------------
# Saved deck
# ---------------------------------------------------------------------------

class SavedDeck(BaseModel):
    id: int | None = None
    discord_id: int
    name: str
    faction_id: str
    leader_card_id: str | None = None
    card_ids: list[str] = Field(default_factory=list)

    @field_validator("card_ids", mode="before")
    @classmethod
    def _coerce_card_ids(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else [v]
        return list(v)

    def to_db_row(self) -> dict[str, Any]:
        return {
            "discord_id": self.discord_id,
            "name": self.name,
            "faction_id": self.faction_id,
            "leader_card_id": self.leader_card_id,
            "card_ids": json.dumps(self.card_ids, ensure_ascii=False),
        }

    @classmethod
    def from_db_row(cls, row: Any) -> "SavedDeck":
        d = dict(row)
        return cls(
            id=d.get("id"),
            discord_id=d["discord_id"],
            name=d["name"],
            faction_id=d["faction_id"],
            leader_card_id=d.get("leader_card_id"),
            card_ids=d.get("card_ids") or [],
        )
