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

    resp = web.FileResponse(requested)
    # Disable caching for HTML, JS, CSS (so changes deploy immediately).
    # Card images (PNG) can be cached since they never change for a given card_id.
    if requested.suffix in (".html", ".js", ".css"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


async def index_handler(request: web.Request) -> web.StreamResponse:
    """Serve the main HTML page at /play/{match_id}.

    The HTML is the same for every match — the actual match_id comes from the
    URL and is read by client-side JS.
    """
    html_path = STATIC_DIR / "index.html"
    if not html_path.is_file():
        return web.Response(text="index.html not found", status=500)
    resp = web.FileResponse(html_path)
    # Always disable caching for the HTML — ensures the latest JS version loads
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


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

    # Mark player as connected. If this was the last player needed, start_match()
    # will be called automatically and emit a match_started event.
    just_started = await match.mark_player_connected(tok.discord_id)
    if just_started:
        log.info("Match %s just started — all players connected.", match_id)

    # Send initial state immediately (personalized to this viewer).
    # If match is still in waiting room (not all players connected yet), the
    # snapshot will include `waiting_for_players: true` and `players_not_connected`.
    snap = match.snapshot(viewer_discord_id=tok.discord_id)
    try:
        await ws.send_json({
            "type": "state",
            "snapshot": snap,
            # Send as string — Discord IDs exceed JS Number.MAX_SAFE_INTEGER
            "you": str(tok.discord_id),
        })
        log.info(
            "WS initial state sent to %s (match=%s, you=%s, current_player=%s, hand_cards=%d, waiting=%s)",
            tok.display_name, match_id, str(tok.discord_id),
            snap.get("current_player_id"),
            next((p["hand_size"] for p in snap.get("players", []) if str(p["discord_id"]) == str(tok.discord_id)), -1),
            snap.get("waiting_for_players"),
        )
    except Exception as e:
        log.exception("Failed to send initial WS state to %s: %s", tok.display_name, e)

    # If we just started the match (or are still waiting), broadcast updated
    # state to ALL connected clients so their UIs refresh.
    await WS_MANAGER.broadcast_match_state(match)

    # Listen for messages
    msg_count = 0
    try:
        async for msg in ws:
            msg_count += 1
            log.info(
                "WS msg #%d from %s (match=%s): type=%s data=%r",
                msg_count, tok.display_name, match_id, msg.type, msg.data if msg.type == web.WSMsgType.TEXT else None,
            )
            if msg.type == web.WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    log.warning("Bad JSON from %s: %r", tok.display_name, msg.data)
                    await ws.send_json({"type": "error", "message": "Неверный JSON."})
                    continue
                await _handle_client_action(match, tok.discord_id, payload, ws)
            elif msg.type == web.WSMsgType.ERROR:
                log.warning("WS error: %s", ws.exception())
            elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSING, web.WSMsgType.CLOSED):
                log.info("WS close signal from %s (match=%s)", tok.display_name, match_id)
                break
    finally:
        await room.remove_client(client)
        log.info("WS disconnected: %s (match=%s, total msgs received=%d)", tok.display_name, match_id, msg_count)

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
# Debug middleware — logs every incoming request to help diagnose 404s
# ---------------------------------------------------------------------------

@web.middleware
async def request_log_middleware(request: web.Request, handler):
    """Log every incoming request with full path + query, so we can see what
    the reverse proxy (Zeabur / Cloudflare) actually forwards to us."""
    log.info(
        "REQUEST %s %s%s (host=%s, ua=%s)",
        request.method,
        request.path,
        f"?{request.query_string}" if request.query_string else "",
        request.host,
        (request.headers.get("User-Agent", "")[:80]),
    )
    try:
        response = await handler(request)
        log.info("RESPONSE %s %s -> %d", request.method, request.path, response.status)
        return response
    except web.HTTPNotFound:
        log.warning("404 NOT FOUND: %s %s (matched=%s)", request.method, request.path, request.match_info)
        raise
    except Exception as e:
        log.exception("Error handling %s %s: %s", request.method, request.path, e)
        raise

def register_web_routes(app: web.Application) -> None:
    """Add all web routes to the aiohttp app."""
    app.router.add_get("/", root_index_handler)
    app.router.add_get("/play/{match_id}", index_handler)
    # Also accept /play/{match_id}/ (with trailing slash) — some reverse proxies
    # add a trailing slash before forwarding, which would otherwise 404.
    app.router.add_get("/play/{match_id}/", index_handler)
    # Static files: /static/{tail:.*}
    app.router.add_get("/static/{tail:.*}", static_handler)
    # WebSocket
    app.router.add_get("/ws/{match_id}", ws_handler)

    # Debug endpoint — lists all registered routes. Useful for diagnosing
    # 404 issues behind reverse proxies (Zeabur, Cloudflare, etc.).
    async def debug_routes_handler(request: web.Request) -> web.Response:
        routes_info = []
        for route in app.router.routes():
            routes_info.append({
                "method": route.method,
                "path": route.resource.canonical if route.resource else None,
            })
        return web.json_response({
            "routes": routes_info,
            "static_dir": str(STATIC_DIR),
            "static_dir_exists": STATIC_DIR.is_dir(),
            "index_html_exists": (STATIC_DIR / "index.html").is_file(),
            "cards_dir_exists": (STATIC_DIR / "cards").is_dir(),
            "cards_count": len(list((STATIC_DIR / "cards").glob("*.png"))) if (STATIC_DIR / "cards").is_dir() else 0,
        })

    app.router.add_get("/debug/routes", debug_routes_handler)

    # Debug endpoint — list every card PNG with size + last-modified time + md5.
    # Useful when you need to verify (without SSH/shell access) that a recently
    # pushed card image actually made it onto the server.
    # Usage:
    #   /debug/cards                       — list all cards
    #   /debug/cards?card_id=coven_elder_ent — show only one card (also includes md5)
    async def debug_cards_handler(request: web.Request) -> web.Response:
        import hashlib
        import os
        import subprocess
        from datetime import datetime, timezone

        card_id_filter = request.query.get("card_id")
        cards_dir = STATIC_DIR / "cards"
        if not cards_dir.is_dir():
            return web.json_response({"error": "cards dir not found", "path": str(cards_dir)})

        # Try to gather git info — this helps diagnose "file didn't make it to server" issues.
        # subprocess.run is sync but fast (<100ms); we accept the brief block.
        git_info: dict = {}
        try:
            # Find the git root by walking up from STATIC_DIR
            git_dir = STATIC_DIR
            for _ in range(10):
                if (git_dir / ".git").exists():
                    break
                git_dir = git_dir.parent
            else:
                git_dir = None

            if git_dir:
                def _git(*args: str) -> str:
                    r = subprocess.run(
                        ["git", "-C", str(git_dir), *args],
                        capture_output=True, text=True, timeout=3,
                    )
                    return r.stdout.strip() if r.returncode == 0 else f"(git error: {r.stderr.strip()})"

                git_info = {
                    "repo_root": str(git_dir),
                    "head_commit": _git("rev-parse", "HEAD"),
                    "head_short": _git("rev-parse", "--short", "HEAD"),
                    "current_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                    "last_commit_message": _git("log", "-1", "--pretty=%s"),
                    "last_commit_date": _git("log", "-1", "--pretty=%ci"),
                    "last_commit_author": _git("log", "-1", "--pretty=%an"),
                }
        except Exception as e:
            git_info = {"error": f"git not available: {e}"}

        items = []
        for png_path in sorted(cards_dir.glob("*.png")):
            cid = png_path.stem
            if card_id_filter and cid != card_id_filter:
                continue
            stat = png_path.stat()
            # Compute md5 (only for single-card queries, to avoid hashing 47 files)
            md5 = ""
            if card_id_filter:
                with open(png_path, "rb") as f:
                    md5 = hashlib.md5(f.read()).hexdigest()
            # Also try to get git log for this specific file
            git_file_log = None
            if card_id_filter and git_info and "error" not in git_info:
                try:
                    rel_path = png_path.relative_to(git_dir)
                    git_file_log = _git("log", "-1", "--pretty=%h %an %ci %s", "--", str(rel_path))
                except Exception:
                    pass
            items.append({
                "card_id": cid,
                "filename": png_path.name,
                "size_bytes": stat.st_size,
                "size_kb": round(stat.st_size / 1024, 1),
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "md5": md5 or None,
                "git_last_commit": git_file_log,
            })

        return web.json_response({
            "count": len(items),
            "filter": card_id_filter,
            "git_info": git_info,
            "items": items,
        })

    app.router.add_get("/debug/cards", debug_cards_handler)
