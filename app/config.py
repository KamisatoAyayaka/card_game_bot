"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env if present (local dev). On render.com env vars come from dashboard.
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    discord_token: str
    discord_application_id: int
    public_base_url: str
    database_path: str
    dev_guild_id: int | None
    default_match_rounds: int
    default_max_players: int
    log_level: str
    port: int

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "")
        app_id_raw = os.getenv("DISCORD_APPLICATION_ID", "0")
        try:
            app_id = int(app_id_raw)
        except ValueError:
            app_id = 0

        guild_raw = os.getenv("DEV_GUILD_ID", "").strip()
        guild_id = int(guild_raw) if guild_raw.isdigit() else None

        db_path = os.getenv("DATABASE_PATH", "data/gwent.db")
        # Resolve relative paths against project root
        if not os.path.isabs(db_path):
            db_path = str(PROJECT_ROOT / db_path)
        # Ensure parent dir exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        return cls(
            discord_token=token,
            discord_application_id=app_id,
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip(),
            database_path=db_path,
            dev_guild_id=guild_id,
            default_match_rounds=int(os.getenv("DEFAULT_MATCH_ROUNDS", "3")),
            default_max_players=int(os.getenv("DEFAULT_MAX_PLAYERS", "2")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            port=int(os.getenv("PORT", "10000")),
        )


# Singleton-style global config
CONFIG = Config.from_env()


# Derived paths
DATA_DIR = PROJECT_ROOT / "data"
CARDS_JSON_DIR = PROJECT_ROOT / "app" / "data" / "cards"
FACTIONS_JSON = PROJECT_ROOT / "app" / "data" / "factions.json"
LEADERS_JSON = PROJECT_ROOT / "app" / "data" / "leaders.json"
PRESETS_DIR = PROJECT_ROOT / "app" / "data" / "presets"

for _p in (DATA_DIR, CARDS_JSON_DIR, PRESETS_DIR):
    _p.mkdir(parents=True, exist_ok=True)
