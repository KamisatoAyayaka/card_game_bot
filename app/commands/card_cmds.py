"""`/card` slash command group — search, info."""
from __future__ import annotations

import discord
from discord import app_commands

from app.services.card_service import CardService
from app.ui.embeds.card_embed import build_card_embed, build_card_list_embed


def register_card_commands(tree: app_commands.CommandTree) -> None:
    group = app_commands.Group(
        name="card",
        description="Поиск и просмотр карт",
    )

    @group.command(name="search", description="Поиск карт по имени или тегу")
    @app_commands.describe(
        query="Подстрока в имени карты",
        faction="Фильтр по фракции",
        tag="Фильтр по тегу (например, soldier, machine)",
        hero_only="Только герои",
    )
    async def card_search(
        interaction: discord.Interaction,
        query: str | None = None,
        faction: str | None = None,
        tag: str | None = None,
        hero_only: bool = False,
    ) -> None:
        cards = await CardService.search(
            query=query,
            faction_id=faction,
            tag=tag,
            hero=hero_only if hero_only else None,
            limit=25,
        )
        embed = await build_card_list_embed(cards, title="🔍 Результаты поиска")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @card_search.autocomplete("faction")
    async def faction_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        factions = await CardService.list_factions()
        return [
            app_commands.Choice(name=f.name, value=f.id)
            for f in factions
            if current.lower() in f.name.lower()
        ][:25]

    @group.command(name="info", description="Подробная информация о карте")
    @app_commands.describe(card_id="ID карты (например, legion_legionary)")
    async def card_info(interaction: discord.Interaction, card_id: str) -> None:
        card = await CardService.get_card(card_id)
        if card is None:
            await interaction.response.send_message("Карта не найдена.", ephemeral=True)
            return
        embed = await build_card_embed(card)
        await interaction.response.send_message(embed=embed)

    @card_info.autocomplete("card_id")
    async def card_id_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cards = await CardService.search(query=current, limit=25)
        return [
            app_commands.Choice(name=f"{c.name} ({c.id})", value=c.id)
            for c in cards
        ][:25]

    @group.command(name="factions", description="Список всех фракций")
    async def card_factions(interaction: discord.Interaction) -> None:
        factions = await CardService.list_factions()
        embed = discord.Embed(title="⚜️ Фракции", color=0xE67E22)
        for f in factions:
            ability = ""
            if f.ability_name:
                ability = f"\n👑 {f.ability_name}: {f.ability_desc or ''}"
            embed.add_field(
                name=f.name,
                value=f"{f.description or '—'}{ability}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    tree.add_command(group)
