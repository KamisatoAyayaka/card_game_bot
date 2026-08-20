"""Interactive deck builder view."""
from __future__ import annotations

import discord
from discord import ui

from app.models.card import CardType, Row
from app.services.card_service import CardService
from app.services.deck_service import DeckService, DeckValidationError
from app.ui.embeds.card_embed import build_card_list_embed


class DeckBuilderView(discord.ui.View):
    """Multi-step deck builder.

    Flow:
        1. Pick a faction (select).
        2. Pick a leader (select).
        3. Add cards (select, multi).
        4. Remove cards (select, multi) [optional].
        5. Save (button) — prompts for name via modal.
    """

    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.faction_id: str | None = None
        self.leader_card_id: str | None = None
        self.card_ids: list[str] = []
        self.message: discord.Message | None = None
        # Populate faction select
        self._build_faction_select()

    # -------------------------------------------------- rendering
    async def render(self) -> discord.Embed:
        embed = discord.Embed(title="🛠️ Билдер колод", color=0x1ABC9C)
        if self.faction_id:
            faction = await CardService.get_faction(self.faction_id)
            embed.add_field(
                name="Фракция",
                value=faction.name if faction else self.faction_id,
                inline=False,
            )
        if self.leader_card_id:
            leader = await CardService.get_card(self.leader_card_id)
            embed.add_field(name="Лидер", value=leader.name if leader else "—", inline=False)
        if self.card_ids:
            cards = await CardService.get_many(self.card_ids)
            units = sum(1 for c in cards if c.type == CardType.UNIT)
            heroes = sum(1 for c in cards if c.hero)
            specials = sum(1 for c in cards if c.type in (CardType.SPECIAL, CardType.WEATHER))
            embed.add_field(
                name="Состав",
                value=f"Всего: {len(cards)} · Бойцы: {units} · Герои: {heroes} · Особые: {specials}",
                inline=False,
            )
            embed.add_field(
                name="Карты",
                value=", ".join(c.name for c in cards[:30]) + ("…" if len(cards) > 30 else ""),
                inline=False,
            )
        else:
            embed.add_field(name="Состав", value="_пусто_", inline=False)
        embed.set_footer(text="Выберите фракцию, лидера и добавьте карты кнопками ниже.")
        return embed

    # -------------------------------------------------- faction select
    def _build_faction_select(self) -> None:
        self.clear_items()
        # Will be populated async on first render (we don't have factions yet synchronously)
        self.add_item(FactionSelect(self))
        self.add_item(RefreshButton(self))
        self.add_item(CancelButton(self))

    async def post_faction_picked(self) -> None:
        self.clear_items()
        self.add_item(LeaderSelect(self))
        self.add_item(AddCardSelect(self))
        self.add_item(RemoveCardSelect(self))
        self.add_item(SaveButton(self))
        self.add_item(CancelButton(self))

    async def refresh(self, interaction: discord.Interaction) -> None:
        if self.message:
            await self.message.edit(embed=await self.render(), view=self)


# ---------------------------------------------------------------------------
# Selects
# ---------------------------------------------------------------------------

class FactionSelect(ui.Select):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        # Defer option population — we cannot await in __init__
        # so we'll populate dynamically on first interaction via a sentinel
        super().__init__(
            placeholder="Выберите фракцию",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Загрузка…", value="__loading__")],
            custom_id="deck_faction_select",
        )
        self._populated = False

    async def _populate(self) -> None:
        factions = await CardService.list_factions()
        # Exclude "neutral" from faction select — neutrals are usable in any deck
        playable = [f for f in factions if f.id != "neutral"]
        self.options = [
            discord.SelectOption(
                label=f.name,
                value=f.id,
                description=(f.description or "")[:100],
            )
            for f in playable[:25]
        ]
        self._populated = True

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self._populated:
            await self._populate()
        if interaction.user.id != self.parent.owner_id:
            await interaction.response.send_message("Это не ваш билдер.", ephemeral=True)
            return
        chosen = self.values[0]
        if chosen == "__loading__":
            await interaction.response.edit_message(view=self.parent)
            return
        self.parent.faction_id = chosen
        self.parent.leader_card_id = None
        self.parent.card_ids = []
        await self.parent.post_faction_picked()
        await interaction.response.edit_message(embed=await self.parent.render(), view=self.parent)


class LeaderSelect(ui.Select):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        super().__init__(
            placeholder="Лидер фракции (необязательно)",
            min_values=0,
            max_values=1,
            options=[discord.SelectOption(label="Загрузка…", value="__loading__")],
            custom_id="deck_leader_select",
        )
        self._populated = False

    async def _populate(self) -> None:
        if not self.parent.faction_id:
            self.options = [discord.SelectOption(label="Сначала выберите фракцию", value="__none__")]
            self._populated = True
            return
        cards = await CardService.cards_by_faction(self.parent.faction_id)
        leaders = [c for c in cards if c.type == CardType.LEADER]
        if not leaders:
            self.options = [discord.SelectOption(label="Нет лидеров", value="__none__")]
        else:
            self.options = [
                discord.SelectOption(label=l.name, value=l.id, description=(l.description or "")[:100])
                for l in leaders[:25]
            ]
        self._populated = True

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self._populated:
            await self._populate()
        if interaction.user.id != self.parent.owner_id:
            await interaction.response.send_message("Это не ваш билдер.", ephemeral=True)
            return
        chosen = self.values[0] if self.values else None
        if chosen in ("__loading__", "__none__"):
            await interaction.response.edit_message(view=self.parent)
            return
        self.parent.leader_card_id = chosen
        await interaction.response.edit_message(embed=await self.parent.render(), view=self.parent)


class AddCardSelect(ui.Select):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        super().__init__(
            placeholder="Добавить карты в колоду",
            min_values=1,
            max_values=25,
            options=[discord.SelectOption(label="Загрузка…", value="__loading__")],
            custom_id="deck_add_card_select",
        )
        self._populated = False

    async def _populate(self) -> None:
        if not self.parent.faction_id:
            self.options = [discord.SelectOption(label="Сначала выберите фракцию", value="__none__")]
            self._populated = True
            return
        # Combine faction cards + neutrals, exclude leaders
        faction_cards = await CardService.cards_by_faction(self.parent.faction_id)
        neutral_cards = await CardService.cards_by_faction("neutral")
        candidates = [
            c for c in (faction_cards + neutral_cards)
            if c.type != CardType.LEADER
        ]
        self.options = [
            discord.SelectOption(
                label=c.name,
                value=c.id,
                description=self._desc(c),
            )
            for c in candidates[:25]
        ]
        self._populated = True

    @staticmethod
    def _desc(c) -> str:
        parts = []
        if c.is_unit:
            parts.append(f"Сила {c.base_strength}")
            if c.row:
                parts.append(c.row.value)
        if c.hero:
            parts.append("★")
        return " · ".join(parts)[:100]

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self._populated:
            await self._populate()
        if interaction.user.id != self.parent.owner_id:
            await interaction.response.send_message("Это не ваш билдер.", ephemeral=True)
            return
        if not self.values or self.values[0] in ("__loading__", "__none__"):
            await interaction.response.edit_message(view=self.parent)
            return
        for v in self.values:
            self.parent.card_ids.append(v)
        await interaction.response.edit_message(embed=await self.parent.render(), view=self.parent)


class RemoveCardSelect(ui.Select):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        super().__init__(
            placeholder="Убрать карты из колоды",
            min_values=1,
            max_values=25,
            options=[discord.SelectOption(label="Загрузка…", value="__loading__")],
            custom_id="deck_remove_card_select",
        )
        self._populated = False

    async def _populate(self) -> None:
        if not self.parent.card_ids:
            self.options = [discord.SelectOption(label="Колода пуста", value="__none__")]
            self._populated = True
            return
        cards = await CardService.get_many(self.parent.card_ids)
        # Deduplicate while preserving count info
        seen: dict[str, int] = {}
        for c in cards:
            seen[c.id] = seen.get(c.id, 0) + 1
        self.options = [
            discord.SelectOption(
                label=f"{c.name} ×{cnt}",
                value=c.id,
            )
            for c, cnt in [(await CardService.get_card(cid), cnt) for cid, cnt in seen.items()]
            if c is not None
        ][:25]
        self._populated = True

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self._populated:
            await self._populate()
        if interaction.user.id != self.parent.owner_id:
            await interaction.response.send_message("Это не ваш билдер.", ephemeral=True)
            return
        if not self.values or self.values[0] in ("__loading__", "__none__"):
            await interaction.response.edit_message(view=self.parent)
            return
        for v in self.values:
            if v in self.parent.card_ids:
                self.parent.card_ids.remove(v)
        await interaction.response.edit_message(embed=await self.parent.render(), view=self.parent)


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

class SaveButton(ui.Button):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        super().__init__(label="Сохранить", style=discord.ButtonStyle.success, custom_id="deck_save_btn")

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.parent.owner_id:
            await interaction.response.send_message("Это не ваш билдер.", ephemeral=True)
            return
        if not self.parent.faction_id or not self.parent.card_ids:
            await interaction.response.send_message(
                "Сначала выберите фракцию и добавьте карты.", ephemeral=True
            )
            return
        await interaction.response.send_modal(DeckSaveModal(self.parent))


class CancelButton(ui.Button):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        super().__init__(label="Отмена", style=discord.ButtonStyle.danger, custom_id="deck_cancel_btn")

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.parent.owner_id:
            await interaction.response.send_message("Это не ваш билдер.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=discord.Embed(title="Билдер закрыт.", color=0x95A5A6),
            view=None,
        )
        self.parent.stop()


class RefreshButton(ui.Button):
    def __init__(self, parent: DeckBuilderView) -> None:
        self.parent = parent
        super().__init__(label="Обновить", style=discord.ButtonStyle.secondary, custom_id="deck_refresh_btn")

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=await self.parent.render(), view=self.parent)


# ---------------------------------------------------------------------------
# Save modal
# ---------------------------------------------------------------------------

class DeckSaveModal(ui.Modal, title="Сохранить колоду"):
    deck_name = ui.TextInput(
        label="Название колоды",
        placeholder="Например: my_legion_deck",
        min_length=1,
        max_length=40,
    )

    def __init__(self, parent: DeckBuilderView) -> None:
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await DeckService.save_deck(
                discord_id=self.parent.owner_id,
                name=str(self.deck_name.value),
                faction_id=self.parent.faction_id,
                card_ids=self.parent.card_ids,
                leader_card_id=self.parent.leader_card_id,
            )
        except DeckValidationError as e:
            await interaction.response.send_message(
                f"❌ Ошибка валидации: {e}", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="✅ Колода сохранена",
            description=f"**{self.deck_name.value}** ({self.parent.faction_id}) — {len(self.parent.card_ids)} карт.",
            color=0x2ECC71,
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.parent.stop()
