"""HTTP routes for the web UI: HTML page, static files, WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from app.config import CONFIG, PROJECT_ROOT
from app.game.engine import MatchError, MatchPhase
from app.services.match_service import MatchService
from app.utils.helpers import safe_get
from app.web.tokens import validate_token
from app.web.websocket import WS_MANAGER, MatchRoom, _Client

if TYPE_CHECKING:
    from app.game.engine import Match

log = logging.getLogger(__name__)

STATIC_DIR = PROJECT_ROOT / "app" / "static"


# ---------------------------------------------------------------------------
# Static files (cards, css, js, html)
# ---------------------------------------------------------------------------

async def static_handler(request: web.Request) -> web.StreamResponse:
    """Serve files from app/static/ — supports /static/cards/foo.png etc."""
    # The matched suffix path is in request.match_info['tail']
    tail = request.match_info.get("tail", "")
    if not tail:
        raise web.HTTPNotFound()

    # Prevent path traversal
    requested = (STATIC_DIR / tail).resolve()
    try:
        requested.relative_to(STATIC_DIR.resolve())
    except ValueError:
        raise web.HTTPNotFound()

    if not requested.is_file():
        raise web.HTTPNotFound()

    return web.FileResponse(requested)


async def index_handler(request: web.Request) -> web.StreamResponse:
    """Serve the main HTML page at /play/{match_id}.

    The HTML is the same for every match — the actual match_id comes from the
    URL and is read by client-side JS.
    """
    html_path = STATIC_DIR / "index.html"
    if not html_path.is_file():
        return web.Response(text="index.html not found", status=500)
    return web.FileResponse(html_path)


async def root_index_handler(request: web.Request) -> web.StreamResponse:
    """Landing page at / — shows bot info / health."""
    html = """
    <!doctype html>
    <html lang="ru"><head><meta charset="utf-8"><title>Gwent Bot</title></head>
    <body style="font-family:sans-serif;max-width:600px;margin:2rem auto;padding:1rem">
      <h1>🃏 Gwent-like Discord Bot</h1>
      <p>Это веб-сервер бота. Чтобы начать игру, используйте команду
         <code>/gwent challenge @user</code> в Discord-канале бота.</p>
      <p>После старта матча нажмите кнопку <b>«Открыть игровое поле»</b> в
         Discord-сообщении — откроется это окно с полноценным игровым UI.</p>
      <p><a href="/health">Health check</a></p>
    </body></html>
    """
    return web.Response(text=html, content_type="text/html")


# ---------------------------------------------------------------------------
# WebSocket endpoint: /ws/{match_id}?token=xxx
# ---------------------------------------------------------------------------

async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)

    match_id = request.match_info.get("match_id", "")
    token = request.query.get("token", "")

    # Authenticate
    tok = validate_token(token)
    if tok is None or tok.match_id != match_id:
        await ws.send_json({"type": "error", "message": "Недействительный или истёкший токен."})
        await ws.close()
        return ws

    match = await MatchService.get(match_id)
    if match is None:
        await ws.send_json({"type": "error", "message": "Матч не найден."})
        await ws.close()
        return ws

    # Join the room
    room = await WS_MANAGER.get_or_create_room(match_id)
    client = _Client(ws=ws, discord_id=tok.discord_id, display_name=tok.display_name)
    await room.add_client(client)

    log.info("WS connected: %s (match=%s)", tok.display_name, match_id)

    # Send initial state immediately (personalized to this viewer)
    snap = match.snapshot(viewer_discord_id=tok.discord_id)
    await ws.send_json({"type": "state", "snapshot": snap, "you": tok.discord_id})

    # Listen for messages
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Неверный JSON."})
                    continue
                await _handle_client_action(match, tok.discord_id, payload, ws)
            elif msg.type == web.WSMsgType.ERROR:
                log.warning("WS error: %s", ws.exception())
    finally:
        await room.remove_client(client)
        log.info("WS disconnected: %s (match=%s)", tok.display_name, match_id)

    return ws


async def _handle_client_action(match: "Match", discord_id: int, payload: dict, ws: web.WebSocketResponse) -> None:
    """Process an action from the web UI (play card, pass, etc.)."""
    msg_type = payload.get("type", "")
    if msg_type == "ping":
        await ws.send_json({"type": "pong"})
        return

    if msg_type != "action":
        await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
        return

    action = payload.get("action", "")
    try:
        if action == "play_card":
            instance_id = payload.get("instance_id", "")
            target_row = payload.get("target_row")
            await match.play_card(discord_id, instance_id, target_row=target_row)
        elif action == "pass":
            await match.pass_turn(discord_id)
        elif action == "use_leader":
            await match.use_leader(discord_id)
        elif action == "surrender":
            await match.surrender(discord_id)
        else:
            await ws.send_json({"type": "error", "message": f"Unknown action: {action}"})
            return
    except MatchError as e:
        await ws.send_json({"type": "error", "message": str(e)})
        return
    except Exception as e:
        log.exception("Action error")
        await ws.send_json({"type": "error", "message": f"Внутренняя ошибка: {e}"})
        return

    # Broadcast updated state to all clients (each gets personalized snapshot)
    await WS_MANAGER.broadcast_match_state(match)


# ---------------------------------------------------------------------------
# Helper used by the bot to issue tokens when a match starts
# ---------------------------------------------------------------------------

async def notify_match_started(match: "Match") -> None:
    """Ensure a WS room exists for the match. Called by the bot."""
    await WS_MANAGER.get_or_create_room(match.match_id)


async def notify_match_finished(match: "Match") -> None:
    """Close all WS connections for this match."""
    await WS_MANAGER.close_room(match.match_id)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_web_routes(app: web.Application) -> None:
    """Add all web routes to the aiohttp app."""
    app.router.add_get("/", root_index_handler)
    app.router.add_get("/play/{match_id}", index_handler)
    # Static files: /static/{tail:.*}
    app.router.add_get("/static/{tail:.*}", static_handler)
    # WebSocket
    app.router.add_get("/ws/{match_id}", ws_handler)
