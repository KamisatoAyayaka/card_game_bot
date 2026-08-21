"""Application entrypoint.

Launches:
  1. An aiohttp web server that serves:
     - /health          — render.com health check
     - /                — landing page
     - /play/{match_id} — full game UI (HTML/CSS/JS)
     - /static/*        — card images, CSS, JS
     - /ws/{match_id}   — real-time WebSocket for game state
  2. The Discord bot client.

Both run concurrently in the same asyncio event loop.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import web

from app.config import CONFIG
from app.database import Database
from app.utils.logger import get_logger, setup_logging
from app.web.routes import register_web_routes

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Health-check endpoint
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


# ---------------------------------------------------------------------------
# Web app factory
# ---------------------------------------------------------------------------

def build_web_app(bot) -> web.Application:
    """Build the aiohttp app with all routes registered."""
    app = web.Application(client_max_size=8 * 1024 * 1024)  # 8 MB for card image uploads
    app["bot"] = bot
    # Health check
    app.router.add_get("/health", health_handler)
    # All other web routes (HTML, static, WS) come from app/web/routes.py
    register_web_routes(app)
    return app


async def start_web_server(bot) -> web.AppRunner:
    app = build_web_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=CONFIG.port)
    await site.start()
    log.info("Web server listening on :%d (HTML / WS / static)", CONFIG.port)
    return runner


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    setup_logging()
    log.info(
        "Starting Gwent Discord bot (port=%s, db=%s, public_url=%s)",
        CONFIG.port, CONFIG.database_path, CONFIG.public_base_url or "<unset>",
    )

    if not CONFIG.public_base_url:
        log.warning(
            "PUBLIC_BASE_URL is not set. The bot will not be able to generate "
            "working game URLs. Set it to your render.com URL (e.g. "
            "https://my-app.onrender.com) in the render.com dashboard."
        )

    # Initialize DB eagerly so /health reflects truth
    await Database.init_schema()

    # Build the bot client (without starting it yet) so the web server can reference it
    from app.bot import build_bot
    bot = build_bot()

    web_runner = await start_web_server(bot)

    try:
        async with bot:
            await bot.start(CONFIG.discord_token)
    except KeyboardInterrupt:
        log.info("Shutdown requested.")
    finally:
        await web_runner.cleanup()
        await Database.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
