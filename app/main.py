"""Application entrypoint.

Launches:
  1. A small aiohttp server exposing /health (required by render.com health checks).
  2. The Discord bot client.

Both run concurrently in the same asyncio event loop.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from app.bot import run_bot
from app.config import CONFIG
from app.database import Database
from app.utils.logger import get_logger, setup_logging

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Health-check HTTP server
# ---------------------------------------------------------------------------

async def health_handler(request: web.Request) -> web.Response:
    """Return 200 if the bot process is alive. Used by render.com."""
    db_ok = Database._db is not None
    payload: dict[str, Any] = {
        "status": "ok",
        "db_initialized": db_ok,
        "bot_user": str(request.app["bot"].user) if request.app.get("bot") and request.app["bot"].user else "not_ready",
    }
    return web.Response(
        text=json.dumps(payload),
        content_type="application/json",
    )


async def root_handler(request: web.Request) -> web.Response:
    return web.Response(
        text=json.dumps({"service": "gwent-discord-bot", "status": "running"}),
        content_type="application/json",
    )


async def start_health_server(bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", root_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=CONFIG.port)
    await site.start()
    log.info("Health-check server listening on :%d", CONFIG.port)
    return runner


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    setup_logging()
    log.info("Starting Gwent Discord bot (port=%s, db=%s)", CONFIG.port, CONFIG.database_path)

    # Initialize DB eagerly so /health reflects truth
    await Database.init_schema()

    # Build the bot client (without starting it yet) so the health server can reference it
    from app.bot import build_bot
    bot = build_bot()

    health_runner = await start_health_server(bot)

    try:
        async with bot:
            await bot.start(CONFIG.discord_token)
    except KeyboardInterrupt:
        log.info("Shutdown requested.")
    finally:
        await health_runner.cleanup()
        await Database.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
