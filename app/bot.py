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

        # Auto-seed cards from JSON if the database is empty.
        # This makes the bot self-bootstrapping on fresh deployments (Zeabur,
        # render.com free tier, etc.) without requiring manual `seed_cards`.
        from app.services.card_service import CardService as _cs
        await _cs.reload()
        if len(_cs._cache) == 0:
            log.info("Card database is empty — auto-seeding from JSON files...")
            from app.config import CARDS_JSON_DIR, FACTIONS_JSON, LEADERS_JSON
            from app.services.import_export import (
                import_all_cards_from_dir,
                import_factions_from_json,
                import_leaders_from_json,
            )
            try:
                f_count = await import_factions_from_json(FACTIONS_JSON)
                l_count = await import_leaders_from_json(LEADERS_JSON)
                c_count = await import_all_cards_from_dir(CARDS_JSON_DIR)
                log.info(
                    "Auto-seeded: %d factions, %d leaders, %d cards.", f_count, l_count, c_count
                )
                await _cs.reload()

                # Also generate card PNG images if the static directory is empty
                static_cards_dir = CARDS_JSON_DIR.parent / "static" / "cards"
                if not static_cards_dir.exists() or not any(static_cards_dir.glob("*.png")):
                    log.info("Card images missing — generating PNGs...")
                    try:
                        from scripts.generate_card_images import generate_all_cards
                        img_count = await generate_all_cards()
                        log.info("Generated %d card image(s).", img_count)
                    except Exception as e:
                        log.warning("Card image generation failed (non-fatal): %s", e)
            except Exception as e:
                log.error("Auto-seed failed: %s", e)

        log.info(
            "Database initialized and card cache loaded (%d cards).", len(_cs._cache)
        )

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
            try:
                synced = await self.tree.sync(guild=guild)
                log.info("Synced %d command(s) to dev guild %s.", len(synced), CONFIG.dev_guild_id)
            except discord.errors.HTTPException as e:
                log.error("Guild command sync failed: %s. Commands may not be available.", e)
        else:
            # Global sync can fail if the application has an Entry Point command
            # configured in Discord Developer Portal (Embedded App / Activity).
            # Discord API error 50240: "You cannot remove this app's Entry Point
            # command in a bulk update operation."
            # Workaround: catch and continue — previously registered commands
            # remain available. To force-resync, set DEV_GUILD_ID env var.
            try:
                synced = await self.tree.sync()
                log.info("Synced %d command(s) globally.", len(synced))
            except discord.errors.HTTPException as e:
                if e.code == 50240:
                    log.warning(
                        "Global command sync skipped — application has an Entry Point "
                        "command configured in Discord Developer Portal. Either: "
                        "(a) set DEV_GUILD_ID env var to sync commands to a specific "
                        "guild instead, or (b) remove the Embedded App / Activity "
                        "from Discord Developer Portal → General Information. "
                        "Bot will continue with previously-registered commands (if any)."
                    )
                    log.warning("Original Discord error: %s", e)
                else:
                    log.error("Global command sync failed (code=%s): %s", e.code, e)

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
