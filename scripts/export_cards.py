"""Export SQLite card data to JSON files (round-trip with seed_cards.py).

Usage:
    python -m scripts.export_cards
"""
from __future__ import annotations

import asyncio
import sys

from app.database import Database
from app.services.import_export import full_export
from app.utils.logger import get_logger, setup_logging

log = get_logger(__name__)


async def main() -> int:
    setup_logging()
    await Database.init_schema()
    result = await full_export()
    log.info("Exported %d cards and %d factions.", result["cards"], result["factions"])
    await Database.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
