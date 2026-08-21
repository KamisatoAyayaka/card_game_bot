"""WebSocket connection registry + broadcast helper.

Each match has a set of connected WebSocket clients. When the engine emits
an event, the WebSocketManager broadcasts the new game snapshot to all
clients connected to that match.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from app.game.engine import Match

log = logging.getLogger(__name__)


@dataclass
class _Client:
    ws: web.WebSocketResponse
    discord_id: int
    display_name: str


@dataclass
class MatchRoom:
    match_id: str
    clients: list[_Client] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def add_client(self, client: _Client) -> None:
        async with self._lock:
            self.clients.append(client)

    async def remove_client(self, client: _Client) -> None:
        async with self._lock:
            if client in self.clients:
                self.clients.remove(client)

    async def broadcast(self, message: dict) -> None:
        """Send a message to every connected client (concurrently)."""
        async with self._lock:
            snapshot = list(self.clients)
        if not snapshot:
            return
        payload = json.dumps(message, ensure_ascii=False, default=str)
        results = await asyncio.gather(
            *[c.ws.send_str(payload) for c in snapshot],
            return_exceptions=True,
        )
        for client, result in zip(snapshot, results):
            if isinstance(result, Exception):
                log.warning("Broadcast to %s failed: %s", client.display_name, result)


class WebSocketManager:
    """Singleton-ish registry of match rooms."""

    _rooms: dict[str, MatchRoom] = {}
    _lock = asyncio.Lock()

    @classmethod
    async def get_or_create_room(cls, match_id: str) -> MatchRoom:
        async with cls._lock:
            if match_id not in cls._rooms:
                cls._rooms[match_id] = MatchRoom(match_id=match_id)
            return cls._rooms[match_id]

    @classmethod
    async def get_room(cls, match_id: str) -> MatchRoom | None:
        return cls._rooms.get(match_id)

    @classmethod
    async def close_room(cls, match_id: str) -> None:
        async with cls._lock:
            room = cls._rooms.pop(match_id, None)
        if room:
            for client in list(room.clients):
                try:
                    await client.ws.close()
                except Exception:
                    pass

    @classmethod
    async def broadcast_match_state(cls, match: "Match", viewer_discord_id: int | None = None) -> None:
        """Broadcast a snapshot. If viewer_discord_id is None, send a per-viewer
        personalized snapshot to each connected client (recommended — each
        player should see only their own hand).
        """
        room = await cls.get_room(match.match_id)
        if room is None:
            return

        if viewer_discord_id is not None:
            # Single targeted message
            snap = match.snapshot(viewer_discord_id=viewer_discord_id)
            await room.broadcast({"type": "state", "snapshot": snap})
            return

        # Per-viewer: send each client a personalized snapshot
        async with room._lock:
            clients = list(room.clients)
        for client in clients:
            snap = match.snapshot(viewer_discord_id=client.discord_id)
            payload = json.dumps(
                {"type": "state", "snapshot": snap},
                ensure_ascii=False,
                default=str,
            )
            try:
                await client.ws.send_str(payload)
            except Exception as e:
                log.warning("Personalized broadcast to %s failed: %s", client.display_name, e)


# Singleton
WS_MANAGER = WebSocketManager()
