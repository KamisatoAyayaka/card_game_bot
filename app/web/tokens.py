"""Per-match access tokens.

When a match starts, the bot generates a short-lived access token for each
participant. The web UI uses this token to authenticate the WebSocket
connection — without it, no game state is revealed.

Tokens are kept in-memory (matches are short-lived). A token is bound to:
  - match_id
  - discord_id (the player)
  - expires_at (15 minutes)
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Iterable


@dataclass
class MatchAccessToken:
    token: str
    match_id: str
    discord_id: int
    display_name: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "match_id": self.match_id,
            "discord_id": self.discord_id,
            "display_name": self.display_name,
            "expires_at": self.expires_at,
        }


# In-memory store: token_string -> MatchAccessToken
_TOKENS: dict[str, MatchAccessToken] = {}
# match_id -> set of token strings (for cleanup)
_MATCH_TOKENS: dict[str, set[str]] = {}

TTL_SECONDS = 6 * 3600  # 6 hours — long enough for a slow match


def issue_token(match_id: str, discord_id: int, display_name: str) -> MatchAccessToken:
    """Issue a fresh access token for a (match_id, discord_id) pair."""
    # Revoke any previous tokens for this user in this match
    revoke_for_user(match_id, discord_id)

    raw = secrets.token_urlsafe(32)
    tok = MatchAccessToken(
        token=raw,
        match_id=match_id,
        discord_id=discord_id,
        display_name=display_name,
        expires_at=time.time() + TTL_SECONDS,
    )
    _TOKENS[raw] = tok
    _MATCH_TOKENS.setdefault(match_id, set()).add(raw)
    return tok


def validate_token(token: str) -> MatchAccessToken | None:
    tok = _TOKENS.get(token)
    if tok is None or tok.is_expired:
        # Lazy cleanup
        if tok is not None:
            _revoke(tok)
        return None
    return tok


def revoke_for_user(match_id: str, discord_id: int) -> None:
    tokens = _MATCH_TOKENS.get(match_id, set())
    to_remove = [t for t in tokens if (tok := _TOKENS.get(t)) and tok.discord_id == discord_id]
    for t in to_remove:
        if t in _TOKENS:
            _revoke(_TOKENS[t])


def revoke_match(match_id: str) -> None:
    tokens = _MATCH_TOKENS.pop(match_id, set())
    for t in tokens:
        tok = _TOKENS.pop(t, None)
        if tok:
            continue  # already popped


def _revoke(tok: MatchAccessToken) -> None:
    _TOKENS.pop(tok.token, None)
    if tok.match_id in _MATCH_TOKENS:
        _MATCH_TOKENS[tok.match_id].discard(tok.token)


def issue_tokens_for_match(match_id: str, participants: Iterable[tuple[int, str]]) -> list[MatchAccessToken]:
    """Convenience: issue tokens for every (discord_id, display_name) pair."""
    return [issue_token(match_id, did, name) for did, name in participants]
