"""Card detail / list embeds."""
from __future__ import annotations

import discord

from app.models.card import Card
from app.services.card_service import CardService
from app.utils.helpers import hex_to_int, rarity_emoji, row_label, type_label, truncate


async def build_card_embed(card: Card) -> discord.Embed:
    faction = await CardService.get_faction(card.faction_id)
    color = hex_to_int(faction.color if faction else None)

    embed = discord.Embed(
        title=f"{rarity_emoji(card.rarity.value)} {card.name}",
        description=card.description or "—",
        color=color,
    )

    embed.add_field(
        name="Тип",
        value=type_label(card.type.value),
        inline=True,
    )
    embed.add_field(
        name="Фракция",
        value=faction.name if faction else card.faction_id,
        inline=True,
    )
    embed.add_field(
        name="Редкость",
        value=card.rarity.value,
        inline=True,
    )

    if card.is_unit:
        embed.add_field(name="Сила", value=str(card.base_strength), inline=True)
        embed.add_field(name="Ряд", value=row_label(card.row.value if card.row else None), inline=True)
        embed.add_field(name="Герой", value="★ Да" if card.hero else "Нет", inline=True)

    if card.tags:
        embed.add_field(name="Теги", value=", ".join(card.tags), inline=False)

    if card.effects:
        eff_lines = [f"• `{e.type}` — {e.params or '{}'}" for e in card.effects]
        embed.add_field(name="Эффекты", value="\n".join(eff_lines), inline=False)

    embed.set_footer(text=f"ID: {card.id}")

    if card.art_url:
        embed.set_image(url=card.art_url)

    return embed


async def build_card_list_embed(cards: list[Card], title: str = "Карты") -> discord.Embed:
    embed = discord.Embed(title=title, color=0x2B2D31)
    if not cards:
        embed.description = "Ничего не найдено."
        return embed

    lines: list[str] = []
    for c in cards[:25]:  # embed field value limit safety
        s = f"• **{c.name}** — {type_label(c.type.value)}"
        if c.is_unit:
            s += f" · {c.base_strength} сила · {row_label(c.row.value if c.row else None)}"
        if c.hero:
            s += " · ★hero"
        s += f"  `({c.id})`"
        lines.append(s)
    embed.description = "\n".join(lines)
    if len(cards) > 25:
        embed.set_footer(text=f"Показаны первые 25 из {len(cards)}.")
    return embed
