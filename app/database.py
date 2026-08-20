"""aiosqlite connection manager + schema bootstrap."""
from __future__ import annotations

import aiosqlite

from app.config import CONFIG

# ---------------------------------------------------------------------------
# Schema DDL — kept in one place so it is easy to audit and migrate.
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS factions (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    description  TEXT,
    color        TEXT,         -- hex color for Discord embeds, e.g. "#aa3333"
    icon_url     TEXT,
    ability_name TEXT,
    ability_desc TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    faction_id      TEXT NOT NULL REFERENCES factions(id),
    type            TEXT NOT NULL CHECK (type IN ('unit','weather','leader','special')),
    row             TEXT CHECK (row IN ('melee','ranged','siege','agile') OR row IS NULL),
    base_strength   INTEGER DEFAULT 0,
    tags            TEXT,      -- JSON array string
    hero            INTEGER DEFAULT 0,
    effects         TEXT,      -- JSON array string of {type, params}
    description     TEXT,
    art_url         TEXT,
    rarity          TEXT DEFAULT 'common',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cards_faction ON cards(faction_id);

CREATE TABLE IF NOT EXISTS players (
    discord_id      INTEGER PRIMARY KEY,
    display_name    TEXT,
    wins            INTEGER DEFAULT 0,
    losses          INTEGER DEFAULT 0,
    draws           INTEGER DEFAULT 0,
    elo             INTEGER DEFAULT 1000,
    matches_played  INTEGER DEFAULT 0,
    last_played_at  TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saved_decks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    faction_id      TEXT NOT NULL,
    leader_card_id  TEXT,
    card_ids        TEXT NOT NULL,  -- JSON array of card IDs
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(discord_id, name)
);

CREATE TABLE IF NOT EXISTS match_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT DEFAULT (datetime('now')),
    finished_at     TEXT,
    rounds_total    INTEGER,
    winner_discord_id INTEGER,
    player_ids      TEXT NOT NULL,  -- JSON array
    score           TEXT            -- JSON dict {discord_id: rounds_won}
);

CREATE TABLE IF NOT EXISTS admin_users (
    discord_id INTEGER PRIMARY KEY,
    added_at   TEXT DEFAULT (datetime('now'))
);
"""


class Database:
    """Thin async wrapper around aiosqlite with row_factory."""
    _db: aiosqlite.Connection | None = None

    @classmethod
    async def connect(cls) -> aiosqlite.Connection:
        if cls._db is None:
            cls._db = await aiosqlite.connect(CONFIG.database_path)
            cls._db.row_factory = aiosqlite.Row
            await cls._db.execute("PRAGMA journal_mode=WAL;")
            await cls._db.execute("PRAGMA foreign_keys=ON;")
            await cls._db.commit()
        return cls._db

    @classmethod
    async def init_schema(cls) -> None:
        db = await cls.connect()
        await db.executescript(SCHEMA_SQL)
        await db.commit()

    @classmethod
    async def close(cls) -> None:
        if cls._db is not None:
            await cls._db.close()
            cls._db = None


async def get_db() -> aiosqlite.Connection:
    """Convenience accessor for services."""
    return await Database.connect()
