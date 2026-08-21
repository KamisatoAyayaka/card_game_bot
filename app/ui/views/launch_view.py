"""Launch view — per-player buttons that open the web UI in browser."""
from __future__ import annotations

import discord
from discord import ui

from app.game.engine import Match


class LaunchView(discord.ui.View):
    """One button per participant. Clicking opens the personalized game URL.

    Each button's URL is the per-player access link. Discord renders URL
    buttons as native hyperlinks — no JS, no risk of token leakage through
    the bot's own click handler.
    """

    def __init__(self, match: Match, base_url: str) -> None:
        super().__init__(timeout=None)  # buttons persist for the match duration
        self.match = match
        self.base_url = base_url
        self._add_player_buttons()

    def _add_player_buttons(self) -> None:
        # Look up tokens that were issued when the match was created.
        from app.web import tokens as web_tokens
        from app.web.websocket import WS_MANAGER  # ensure room exists

        for player in self.match.players:
            # Find the existing token for this player
            tok = None
            # Tokens are stored in _TOKENS dict; we need to find one matching this user.
            for t in web_tokens._TOKENS.values():
                if t.match_id == self.match.match_id and t.discord_id == player.discord_id:
                    tok = t
                    break
            if tok is None:
                # Issue one if missing (shouldn't happen, but be defensive)
                tok = web_tokens.issue_token(
                    self.match.match_id,
                    player.discord_id,
                    player.display_name,
                )
            url = f"{self.base_url}/play/{self.match.match_id}?token={tok.token}"
            # Sanitize label (Discord limit 80 chars)
            label = (player.display_name or f"Player {player.discord_id}")[:80]
            btn = discord.ui.Button(
                label=f"🎮 {label}",
                style=discord.ButtonStyle.link,
                url=url,
            )
            self.add_item(btn)
