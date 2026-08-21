"""Import JSON card data into SQLite.

Usage:
    python -m scripts.seed_cards                      # import factions + leaders + all cards in data/cards/
    python -m scripts.seed_cards --file path/to.json  # import a specific file
    python -m scripts.seed_cards --all                # same as default (explicit)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import CARDS_JSON_DIR, FACTIONS_JSON, LEADERS_JSON
from app.database import Database
from app.services.card_service import CardService
from app.services.import_export import (
    import_all_cards_from_dir,
    import_cards_from_json_file,
    import_factions_from_json,
    import_leaders_from_json,
)
from app.utils.logger import get_logger, setup_logging

log = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed SQLite with JSON card data.")
    p.add_argument("--file", type=Path, help="Import only this JSON file")
    p.add_argument("--all", action="store_true", help="Import factions + leaders + all cards (default)")
    p.add_argument(
        "--generate-images",
        action="store_true",
        default=True,
        help="Also (re)generate PNG card images (default: on)",
    )
    p.add_argument(
        "--no-images",
        dest="generate_images",
        action="store_false",
        help="Skip image generation",
    )
    return p.parse_args()


async def main() -> int:
    setup_logging()
    args = parse_args()
    await Database.init_schema()

    if args.file:
        path: Path = args.file
        if not path.exists():
            log.error("File not found: %s", path)
            return 1
        # Try factions file separately
        if path == FACTIONS_JSON:
            n = await import_factions_from_json(path)
            log.info("Imported %d factions.", n)
        else:
            n = await import_cards_from_json_file(path)
            log.info("Imported %d cards from %s.", n, path)
        await CardService.reload()
        return 0

    # Default: full seed
    f_count = await import_factions_from_json(FACTIONS_JSON)
    log.info("Imported %d factions.", f_count)

    l_count = await import_leaders_from_json(LEADERS_JSON)
    log.info("Imported %d leaders.", l_count)

    c_count = await import_all_cards_from_dir(CARDS_JSON_DIR)
    log.info("Imported %d cards from %s.", c_count, CARDS_JSON_DIR)

    await CardService.reload()
    log.info("Card cache refreshed.")

    # Auto-generate card images so the web UI can serve them
    if args.generate_images:
        from scripts.generate_card_images import generate_all_cards
        img_count = await generate_all_cards()
        log.info("Generated %d card image(s).", img_count)

    await Database.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
