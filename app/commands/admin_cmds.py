"""`/admin` slash command group — reload cards, export, etc."""
from __future__ import annotations

import discord
from discord import app_commands

from app.services import import_export
from app.services.card_service import CardService
from app.services.import_export import full_export


ADMIN_IDS: set[int] = set()  # populated at runtime from DB or env


async def is_admin(discord_id: int) -> bool:
    # Always allow server admins
    # (for finer control, query admin_users table)
    from app.database import get_db
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM admin_users WHERE discord_id=?", (discord_id,)
    ) as cur:
        row = await cur.fetchone()
    return row is not None


def register_admin_commands(tree: app_commands.CommandTree) -> None:
    group = app_commands.Group(
        name="admin",
        description="Административные команды (только для админов)",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @group.command(name="reload-cards", description="Переимпорт JSON-карт в SQLite")
    async def reload_cards(interaction: discord.Interaction) -> None:
        if not await is_admin(interaction.user.id) and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        from app.config import CARDS_JSON_DIR, FACTIONS_JSON, LEADERS_JSON
        f_count = await import_export.import_factions_from_json(FACTIONS_JSON)
        l_count = await import_export.import_leaders_from_json(LEADERS_JSON)
        c_count = await import_export.import_all_cards_from_dir(CARDS_JSON_DIR)
        await CardService.reload()
        await interaction.followup.send(
            f"✅ Импортировано: фракций={f_count}, лидеров={l_count}, карт={c_count}.",
            ephemeral=True,
        )

    @group.command(name="export-cards", description="Экспорт SQLite → JSON")
    async def export_cards(interaction: discord.Interaction) -> None:
        if not await is_admin(interaction.user.id) and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await full_export()
        await interaction.followup.send(
            f"✅ Экспортировано: карт={result['cards']}, фракций={result['factions']}.",
            ephemeral=True,
        )

    @group.command(name="add-admin", description="Добавить администратора бота")
    @app_commands.describe(user="Новый админ")
    async def add_admin(interaction: discord.Interaction, user: discord.Member) -> None:
        if not await is_admin(interaction.user.id) and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
            return
        from app.database import get_db
        db = await get_db()
        await db.execute(
            "INSERT OR IGNORE INTO admin_users (discord_id) VALUES (?)",
            (user.id,),
        )
        await db.commit()
        await interaction.response.send_message(
            f"✅ {user.mention} добавлен как админ.", ephemeral=True
        )

    tree.add_command(group)
