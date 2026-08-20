"""Bot client setup, slash command registration, lifecycle hooks."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord

from app.commands.admin_cmds import register_admin_commands
from app.commands.card_cmds import register_card_commands
from app.commands.deck_cmds import register_deck_commands
from app.commands.game_cmds import register_gwent_commands
from app.commands.stats_cmds import register_stats_commands
from app.config import CONFIG
from app.database import Database
from app.services.card_service import CardService
from app.utils.logger import get_logger, setup_logging

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class GwentBot(discord.Client):
    """Discord client with app_commands tree."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = False  # not needed for slash commands
        intents.message_content = False  # we use slash commands only
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Initialize DB schema + load card cache
        await Database.init_schema()
        await CardService.reload()
        log.info("Database initialized and card cache loaded (%d cards).", len(CardService._cache))

        # Register all command groups
        register_gwent_commands(self.tree, self)
        register_deck_commands(self.tree)
        register_card_commands(self.tree)
        register_stats_commands(self.tree)
        register_admin_commands(self.tree)

        # Sync commands (to dev guild for instant updates, globally otherwise)
        if CONFIG.dev_guild_id:
            guild = discord.Object(id=CONFIG.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to dev guild %s.", len(synced), CONFIG.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally.", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")
        log.info("Connected to %d guild(s).", len(self.guilds))


def build_bot() -> GwentBot:
    return GwentBot()


async def run_bot() -> None:
    setup_logging()
    if not CONFIG.discord_token or CONFIG.discord_token == "your-bot-token-here":
        log.error("DISCORD_TOKEN is not set. Edit .env and restart.")
        return
    bot = build_bot()
    try:
        async with bot:
            await bot.start(CONFIG.discord_token)
    except KeyboardInterrupt:
        log.info("Shutdown requested.")
    finally:
        await Database.close()
