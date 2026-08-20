"""Matchmaking & active-match registry (in-memory)."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.game.engine import Match

# In-memory registry of active matches, keyed by match_id.
# Matches are short-lived (one Discord channel = one match) so RAM is fine.
# A more durable backend can be plugged in later if horizontal scaling is needed.


@dataclass
class _PendingInvite:
    invite_id: str
    challenger_id: int
    challenged_ids: list[int]
    channel_id: int
    rounds: int
    created_at: float


class MatchService:
    _matches: dict[str, "Match"] = {}
    _channel_to_match: dict[int, str] = {}
    _invites: dict[str, _PendingInvite] = {}
    _lock = asyncio.Lock()

    # ---------------------------------------------------------- invites
    @classmethod
    async def create_invite(
        cls,
        challenger_id: int,
        challenged_ids: list[int],
        channel_id: int,
        rounds: int,
    ) -> _PendingInvite:
        async with cls._lock:
            invite_id = uuid.uuid4().hex[:8]
            inv = _PendingInvite(
                invite_id=invite_id,
                challenger_id=challenger_id,
                challenged_ids=challenged_ids,
                channel_id=channel_id,
                rounds=rounds,
                created_at=asyncio.get_event_loop().time(),
            )
            cls._invites[invite_id] = inv
            return inv

    @classmethod
    async def get_invite(cls, invite_id: str) -> _PendingInvite | None:
        return cls._invites.get(invite_id)

    @classmethod
    async def cancel_invite(cls, invite_id: str) -> None:
        cls._invites.pop(invite_id, None)

    # --------------------------------------------------------- matches
    @classmethod
    async def register(cls, channel_id: int, match: "Match") -> None:
        async with cls._lock:
            cls._matches[match.match_id] = match
            cls._channel_to_match[channel_id] = match.match_id

    @classmethod
    async def get_for_channel(cls, channel_id: int) -> "Match | None":
        mid = cls._channel_to_match.get(channel_id)
        if not mid:
            return None
        return cls._matches.get(mid)

    @classmethod
    async def get(cls, match_id: str) -> "Match | None":
        return cls._matches.get(match_id)

    @classmethod
    async def end(cls, channel_id: int, match_id: str) -> None:
        async with cls._lock:
            cls._matches.pop(match_id, None)
            if cls._channel_to_match.get(channel_id) == match_id:
                cls._channel_to_match.pop(channel_id, None)

    @classmethod
    async def is_channel_busy(cls, channel_id: int) -> bool:
        return channel_id in cls._channel_to_match
