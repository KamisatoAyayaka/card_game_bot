"""`/deck` slash command group — list, build, save, use, delete."""
from __future__ import annotations

import discord
from discord import app_commands

from app.services.card_service import CardService
from app.services.deck_service import DeckService, DeckValidationError
from app.ui.embeds.card_embed import build_card_list_embed
from app.ui.views.deck_builder import DeckBuilderView


def register_deck_commands(tree: app_commands.CommandTree) -> None:
    group = app_commands.Group(
        name="deck",
        description="Управление колодами",
    )

    # ------------------------------------------------------------ list
    @group.command(name="list", description="Показать ваши сохранённые колоды")
    async def deck_list(interaction: discord.Interaction) -> None:
        decks = await DeckService.list_decks(interaction.user.id)
        if not decks:
            await interaction.response.send_message(
                "У вас пока нет сохранённых колод. Используйте `/deck build` "
                "или выберите пресет через `/gwent presets`.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="📚 Ваши колоды", color=0x1ABC9C)
        for d in decks:
            faction = await CardService.get_faction(d.faction_id)
            leader = await CardService.get_card(d.leader_card_id) if d.leader_card_id else None
            embed.add_field(
                name=d.name,
                value=(
                    f"Фракция: {faction.name if faction else d.faction_id}\n"
                    f"Карт: {len(d.card_ids)}\n"
                    f"Лидер: {leader.name if leader else '—'}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------ build
    @group.command(name="build", description="Открыть интерактивный билдер колод")
    @app_commands.describe(faction="Фракция для новой колоды (необязательно — выберете в UI)")
    async def deck_build(
        interaction: discord.Interaction,
        faction: str | None = None,
    ) -> None:
        view = DeckBuilderView(owner_id=interaction.user.id)
        await interaction.response.send_message(
            embed=await view.render(),
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    @deck_build.autocomplete("faction")
    async def faction_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        factions = await CardService.list_factions()
        playable = [f for f in factions if f.id != "neutral"]
        return [
            app_commands.Choice(name=f.name, value=f.id)
            for f in playable
            if current.lower() in f.name.lower() or current.lower() in f.id.lower()
        ][:25]

    # ------------------------------------------------------------ delete
    @group.command(name="delete", description="Удалить сохранённую колоду")
    @app_commands.describe(name="Название колоды")
    async def deck_delete(interaction: discord.Interaction, name: str) -> None:
        ok = await DeckService.delete_deck(interaction.user.id, name)
        if ok:
            await interaction.response.send_message(f"Колода «{name}» удалена.", ephemeral=True)
        else:
            await interaction.response.send_message("Колода не найдена.", ephemeral=True)

    @deck_delete.autocomplete("name")
    async def deck_name_autocomplete(
        interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        decks = await DeckService.list_decks(interaction.user.id)
        return [
            app_commands.Choice(name=d.name, value=d.name)
            for d in decks
            if current.lower() in d.name.lower()
        ][:25]

    tree.add_command(group)
