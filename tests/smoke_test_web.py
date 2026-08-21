"""End-to-end smoke test for the web UI layer.

Starts the aiohttp web server, creates a match, issues an access token,
and exercises the WebSocket protocol — verifying that:
  - The HTML page is served at /play/{match_id}
  - The WebSocket authenticates with a valid token
  - The initial state snapshot is sent on connect
  - Card images are served from /static/cards/{card_id}.png
  - Action messages trigger state broadcasts
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
from aiohttp import web

# Force test DB
os.environ["DATABASE_PATH"] = "data/gwent_web_test.db"
import app.config as cfg_mod
cfg_mod.CONFIG = cfg_mod.Config.from_env()

from app.database import Database
from app.config import CARDS_JSON_DIR, FACTIONS_JSON, LEADERS_JSON, CONFIG
from app.game.engine import Match, MatchPhase
from app.services.card_service import CardService
from app.services.deck_service import DeckService
from app.services.import_export import (
    import_all_cards_from_dir,
    import_factions_from_json,
    import_leaders_from_json,
)
from app.services.match_service import MatchService
from app.utils.logger import get_logger, setup_logging
from app.web import tokens as web_tokens
from app.web.routes import register_web_routes, notify_match_started
from app.web.websocket import WS_MANAGER

log = get_logger(__name__)


async def main() -> int:
    setup_logging()
    # Override DATABASE_PATH for test
    test_db = Path("data/gwent_web_test.db")
    if test_db.exists():
        test_db.unlink()
    # Re-import config after env override
    import importlib
    importlib.reload(cfg_mod)
    global CONFIG
    CONFIG = cfg_mod.CONFIG

    await Database.init_schema()
    await import_factions_from_json(FACTIONS_JSON)
    await import_leaders_from_json(LEADERS_JSON)
    await import_all_cards_from_dir(CARDS_JSON_DIR)
    await CardService.reload()

    # Build match
    preset_a = DeckService.load_preset("legion_starter")
    preset_b = DeckService.load_preset("coven_starter")
    participants = [
        (111, "Alice", preset_a["faction_id"], list(preset_a["card_ids"]), preset_a.get("leader_card_id")),
        (222, "Bob", preset_b["faction_id"], list(preset_b["card_ids"]), preset_b.get("leader_card_id")),
    ]
    all_card_ids = set()
    for _, _, _, cids, lid in participants:
        all_card_ids.update(cids)
        if lid:
            all_card_ids.add(lid)
    cards = await CardService.get_many(list(all_card_ids))
    card_lookup = {c.id: c for c in cards}

    match = Match.create(
        channel_id=999,
        participants=participants,
        card_lookup=card_lookup,
        rounds_total=3,
    )
    await MatchService.register(999, match)
    await notify_match_started(match)

    # Issue access tokens for both players
    tok_a = web_tokens.issue_token(match.match_id, 111, "Alice")
    tok_b = web_tokens.issue_token(match.match_id, 222, "Bob")
    log.info("Issued tokens: Alice=%s..., Bob=%s...", tok_a.token[:8], tok_b.token[:8])

    await match.start_match()

    # Build web app
    class FakeBot:
        user = None
    app = web.Application()
    app["bot"] = FakeBot()
    register_web_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=11000)
    await site.start()
    log.info("Test server on http://127.0.0.1:11000")

    async with aiohttp.ClientSession() as session:
        # 1. Test HTML page
        log.info("--- Test 1: HTML page ---")
        async with session.get(f"http://127.0.0.1:11000/play/{match.match_id}?token={tok_a.token}") as resp:
            assert resp.status == 200, f"HTML status: {resp.status}"
            html = await resp.text()
            assert "<title>Gwent" in html
            log.info("✓ HTML page served (status=200)")

        # 2. Test static card image
        log.info("--- Test 2: card image ---")
        async with session.get("http://127.0.0.1:11000/static/cards/legion_legionary.png") as resp:
            assert resp.status == 200, f"Image status: {resp.status}"
            data = await resp.read()
            assert len(data) > 1000
            log.info("✓ Card image served (%d bytes)", len(data))

        # 3. Test CSS
        log.info("--- Test 3: CSS ---")
        async with session.get("http://127.0.0.1:11000/static/css/style.css") as resp:
            assert resp.status == 200
            log.info("✓ CSS served")

        # 4. Test JS
        log.info("--- Test 4: JS ---")
        async with session.get("http://127.0.0.1:11000/static/js/app.js") as resp:
            assert resp.status == 200
            log.info("✓ JS served")

        # 5. Test WebSocket connect with valid token
        log.info("--- Test 5: WebSocket connect ---")
        ws_url = f"ws://127.0.0.1:11000/ws/{match.match_id}?token={tok_a.token}"
        async with session.ws_connect(ws_url) as ws_client:
            # Receive initial state
            msg = await asyncio.wait_for(ws_client.receive(), timeout=3)
            data = json.loads(msg.data)
            assert data["type"] == "state"
            snap = data["snapshot"]
            assert snap["match_id"] == match.match_id
            assert data["you"] == 111
            # Alice should see her own hand
            alice = next(p for p in snap["players"] if p["discord_id"] == 111)
            assert alice["hand"] is not None, "Alice should see her own hand"
            assert len(alice["hand"]) == 10
            # Bob's hand should be hidden
            bob = next(p for p in snap["players"] if p["discord_id"] == 222)
            assert bob["hand"] is None, "Bob's hand should be hidden from Alice"
            log.info("✓ WS state received. Alice's hand: %d cards (Bob's hidden)", len(alice["hand"]))

            # Verify card images URLs in snapshot
            hand_card = alice["hand"][0]
            assert hand_card["image"].endswith(f"/static/cards/{hand_card['card_id']}.png")
            log.info("✓ Card image URL: %s", hand_card["image"])

            # 6. Test action: Alice plays a non-agile unit card
            log.info("--- Test 6: play card via WS ---")
            unit = next(c for c in alice["hand"] if c["type"] == "unit" and c["row"] != "agile")
            await ws_client.send_json({
                "type": "action",
                "action": "play_card",
                "instance_id": unit["id"],
            })
            # Receive updated state
            msg = await asyncio.wait_for(ws_client.receive(), timeout=3)
            data = json.loads(msg.data)
            assert data["type"] == "state"
            new_alice = next(p for p in data["snapshot"]["players"] if p["discord_id"] == 111)
            assert len(new_alice["hand"]) == 9, f"Expected 9 cards, got {len(new_alice['hand'])}"
            log.info("✓ Alice played %s. Hand now has %d cards", unit["name"], len(new_alice["hand"]))

        # 7. Test WebSocket with INVALID token
        log.info("--- Test 7: invalid token rejected ---")
        async with session.ws_connect(f"ws://127.0.0.1:11000/ws/{match.match_id}?token=INVALID") as ws_client:
            msg = await asyncio.wait_for(ws_client.receive(), timeout=3)
            data = json.loads(msg.data)
            assert data["type"] == "error"
            log.info("✓ Invalid token rejected: %s", data["message"])

    await runner.cleanup()
    await Database.close()
    if test_db.exists():
        test_db.unlink()
    log.info("=== ALL WEB SMOKE TESTS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
