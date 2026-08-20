"""Initialize the SQLite database schema.

Usage:
    python -m scripts.init_db
"""
from __future__ import annotations

import asyncio
import sys

from app.config import CONFIG
from app.database import Database
from app.utils.logger import get_logger, setup_logging

log = get_logger(__name__)


async def main() -> int:
    setup_logging()
    log.info("Initializing DB at %s", CONFIG.database_path)
    await Database.init_schema()
    await Database.close()
    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
