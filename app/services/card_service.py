"""Card & faction CRUD service."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.database import get_db
from app.models.card import Card, Faction


class CardService:
    """Read access for cards/factions. Writes go through import/export service."""

    # ------------------------------------------------------------------ cache
    _cache: dict[str, Card] = {}
    _faction_cache: dict[str, Faction] = {}
    _cache_loaded: bool = False

    # ------------------------------------------------------------- factions
    @classmethod
    async def list_factions(cls) -> list[Faction]:
        await cls._ensure_loaded()
        return list(cls._faction_cache.values())

    @classmethod
    async def get_faction(cls, faction_id: str) -> Faction | None:
        await cls._ensure_loaded()
        return cls._faction_cache.get(faction_id)

    # ---------------------------------------------------------------- cards
    @classmethod
    async def get_card(cls, card_id: str) -> Card | None:
        await cls._ensure_loaded()
        return cls._cache.get(card_id)

    @classmethod
    async def get_many(cls, card_ids: list[str]) -> list[Card]:
        await cls._ensure_loaded()
        out: list[Card] = []
        for cid in card_ids:
            c = cls._cache.get(cid)
            if c is not None:
                out.append(c)
        return out

    @classmethod
    async def all_cards(cls) -> list[Card]:
        await cls._ensure_loaded()
        return list(cls._cache.values())

    @classmethod
    async def cards_by_faction(cls, faction_id: str) -> list[Card]:
        await cls._ensure_loaded()
        return [c for c in cls._cache.values() if c.faction_id == faction_id]

    @classmethod
    async def search(
        cls,
        query: str | None = None,
        faction_id: str | None = None,
        tag: str | None = None,
        hero: bool | None = None,
        limit: int = 50,
    ) -> list[Card]:
        await cls._ensure_loaded()
        q = (query or "").lower().strip()
        out: list[Card] = []
        for c in cls._cache.values():
            if q and q not in c.name.lower() and q not in c.id.lower():
                continue
            if faction_id and c.faction_id != faction_id:
                continue
            if tag and tag not in c.tags:
                continue
            if hero is not None and c.hero != hero:
                continue
            out.append(c)
            if len(out) >= limit:
                break
        return out

    # -------------------------------------------------------------- loading
    @classmethod
    async def reload(cls) -> None:
        """Force reload from DB. Called by /admin reload-cards."""
        cls._cache.clear()
        cls._faction_cache.clear()
        cls._cache_loaded = False
        await cls._ensure_loaded()

    @classmethod
    async def _ensure_loaded(cls) -> None:
        if cls._cache_loaded:
            return
        db = await get_db()

        async with db.execute("SELECT * FROM factions") as cur:
            rows = await cur.fetchall()
        for r in rows:
            f = Faction(**dict(r))
            cls._faction_cache[f.id] = f

        async with db.execute("SELECT * FROM cards") as cur:
            rows = await cur.fetchall()
        for r in rows:
            c = Card.from_db_row(r)
            cls._cache[c.id] = c

        cls._cache_loaded = True
