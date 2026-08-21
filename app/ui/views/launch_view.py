"""Launch view — per-player buttons that open the web UI in browser."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse, urlunparse

import discord
from discord import ui

from app.game.engine import Match


def _normalize_url(raw: str) -> str:
    """Normalize a user-provided URL.

    Handles common copy-paste pathologies:
      - backslashes instead of forward slashes (Windows clipboard)
        e.g. `https:\\\\example.com` or `https:\\example.com` -> `https://example.com`
      - missing or duplicated slashes after the scheme
        e.g. `https:/example.com`, `https:////example.com` -> `https://example.com`
      - whitespace around the URL
      - trailing slash
      - missing scheme (defaults to https://)
    """
    if not raw:
        return ""
    s = raw.strip()
    # Replace any backslash with forward slash (handles `https:\\host` -> `https://host`)
    s = s.replace("\\", "/")
    # Collapse multiple slashes anywhere in the URL
    while "//" in s:
        s = s.replace("//", "/")
    # Now `s` looks like `https:/host/path` (single slash after colon).
    # If there's a `:/` separator, normalize to `://`
    if ":/" in s and "://" not in s:
        s = s.replace(":/", "://", 1)
    # If there's still no scheme separator, the user typed just a hostname.
    # Prepend `https://`
    if "://" not in s:
        s = f"https://{s}"
    # Strip trailing slash
    return s.rstrip("/")


def _is_valid_http_url(url: str) -> bool:
    """Return True only if URL is well-formed and uses http/https scheme.

    Strict check: must contain `://` separator AND have a non-empty netloc
    (host:port). This catches the common copy-paste error where the URL
    becomes `https:\\host` (single backslash) — which `urlparse` would
    otherwise silently accept.
    """
    if not url:
        return False
    # Must contain the literal scheme separator
    if "://" not in url:
        return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        # netloc must contain at least one dot or be localhost (basic sanity)
        host = parsed.netloc.split(":")[0]
        if host not in ("localhost",) and "." not in host:
            return False
        # Reject if there are any backslashes left
        if "\\" in url:
            return False
        return True
    except (ValueError, TypeError):
        return False


class LaunchView(discord.ui.View):
    """One button per participant. Clicking opens the personalized game URL.

    Each button's URL is the per-player access link. Discord renders URL
    buttons as native hyperlinks — no JS, no risk of token leakage through
    the bot's own click handler.

    If `base_url` is missing or invalid, no URL buttons are added — instead
    a single disabled info button is shown, and the caller (game_cmds.py)
    should send a follow-up message explaining the misconfiguration.
    """

    def __init__(self, match: Match, base_url: str) -> None:
        super().__init__(timeout=None)  # buttons persist for the match duration
        self.match = match
        # Normalize the base URL before validation
        self.base_url = _normalize_url(base_url)
        self.url_valid = _is_valid_http_url(self.base_url)
        self._add_player_buttons()

    def _add_player_buttons(self) -> None:
        from app.web import tokens as web_tokens

        if not self.url_valid:
            # Add a single disabled placeholder button explaining the issue
            self.add_item(
                discord.ui.Button(
                    label="⚠️ PUBLIC_BASE_URL не настроен — обратитесь к админу",
                    style=discord.ButtonStyle.danger,
                    disabled=True,
                )
            )
            return

        for player in self.match.players:
            # Find the existing token for this player
            tok = None
            for t in web_tokens._TOKENS.values():
                if t.match_id == self.match.match_id and t.discord_id == player.discord_id:
                    tok = t
                    break
            if tok is None:
                tok = web_tokens.issue_token(
                    self.match.match_id,
                    player.discord_id,
                    player.display_name,
                )
            url = f"{self.base_url}/play/{self.match.match_id}?token={tok.token}"
            # Defensive: ensure the final URL is still valid
            if not _is_valid_http_url(url):
                continue
            # Sanitize label (Discord limit 80 chars)
            label = (player.display_name or f"Player {player.discord_id}")[:78]
            btn = discord.ui.Button(
                label=f"🎮 {label}",
                style=discord.ButtonStyle.link,
                url=url,
            )
            self.add_item(btn)
