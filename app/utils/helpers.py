"""Small helpers used across the Discord layer."""
from __future__ import annotations

import re
from typing import Any

from app.models.card import Card, CardType, Rarity


_RARITY_EMOJI = {
    Rarity.COMMON.value: "⚪",
    Rarity.RARE.value: "🔵",
    Rarity.EPIC.value: "🟣",
    Rarity.LEGENDARY.value: "🟡",
}

_ROW_LABEL_RU = {
    "melee": "Ближний бой",
    "ranged": "Дальний бой",
    "siege": "Осада",
}

_TYPE_LABEL_RU = {
    CardType.UNIT.value: "Боец",
    CardType.WEATHER.value: "Погода",
    CardType.LEADER.value: "Лидер",
    CardType.SPECIAL.value: "Особая",
}


def row_label(row: str | None) -> str:
    if row is None:
        return "—"
    return _ROW_LABEL_RU.get(row, row)


def type_label(card_type: str) -> str:
    return _TYPE_LABEL_RU.get(card_type, card_type)


def rarity_emoji(rarity: str) -> str:
    return _RARITY_EMOJI.get(rarity, "")


def truncate(text: str | None, n: int = 200) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[: n - 1] + "…"


def hex_to_int(color: str | None) -> int:
    """'#aa3333' -> 0xaa3333 (default 0x2b2d31 if None)."""
    if not color:
        return 0x2B2D31
    s = color.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return 0x2B2D31
    return int(s, 16)


def strength_emoji(s: int) -> str:
    if s <= 0:
        return "0"
    return str(s)


def card_short_label(card: Card) -> str:
    """One-line summary used in select menus."""
    parts: list[str] = [card.name]
    if card.is_unit:
        parts.append(f"({card.base_strength})")
    parts.append(f"[{type_label(card.type.value)}]")
    if card.hero:
        parts.append("★hero")
    return " ".join(parts)


def safe_get(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur
