"""Generate card images (PNG) for every card in the database.

Outputs to app/static/cards/{card_id}.png — one file per card.

Style:
  - Vertical card, 240x336 px (5:7 aspect, similar to real Gwent cards)
  - Faction-colored gradient background
  - Large strength number in top-left corner (for unit cards)
  - Card name centered at top
  - Row/type emblem in the middle
  - Hero cards get a golden border
  - Description text wrapped at the bottom

Usage:
    python -m scripts.generate_card_images               # regenerate all
    python -m scripts.generate_card_images --card-id legion_legionary  # one card
"""
from __future__ import annotations

import argparse
import asyncio
import math
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from app.config import CARDS_JSON_DIR, PROJECT_ROOT
from app.database import Database
from app.models.card import Card, CardType, Rarity, Row
from app.services.card_service import CardService
from app.services.import_export import (
    import_all_cards_from_dir,
    import_factions_from_json,
    import_leaders_from_json,
)
from app.utils.logger import get_logger, setup_logging

log = get_logger(__name__)

# Output directory
STATIC_CARDS_DIR = PROJECT_ROOT / "app" / "static" / "cards"

# Card dimensions — large resolution for crisp rendering on retina displays.
# Default 600x840 (5:7 aspect ratio, matches the original 240x336 layout).
# You can use ANY aspect ratio — just edit both CARD_W and CARD_H. The CSS on
# the frontend uses `object-fit: cover` so cards always fill their slot
# regardless of source dimensions. A few popular choices:
#   240x336  — small, ~10 KB per PNG (good for mobile)
#   600x840  — DEFAULT, ~35 KB per PNG (5:7 aspect, classic Gwent)
#   600x1042 — tall portrait, ~50 KB per PNG (closer to real playing-card ratio 4:7)
#   750x1050 — very high detail, ~70 KB per PNG (4:7 aspect)
CARD_W = 600
CARD_H = 840
CORNER_RADIUS = 40  # scale up proportionally with card dimensions

# Font paths — rely on system fonts available on render.com / locally
FONT_PATHS = {
    "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
# CJK-capable fallback
CJK_FONT_PATH = "/usr/share/fonts/truetype/chinese/NotoSansSC-Regular.ttf"


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_PATHS["bold" if bold else "regular"]
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(CJK_FONT_PATH, size)
        except Exception:
            return ImageFont.load_default()


# Faction color palettes (RGB)
FACTION_PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "iron_legion": ((58, 32, 24), (139, 58, 46)),     # dark rust -> warm red
    "verdant_coven": ((24, 50, 32), (46, 139, 87)),   # deep green -> forest
    "ashen_pact": ((40, 32, 64), (90, 74, 139)),      # deep purple -> violet
    "neutral": ((50, 50, 55), (130, 130, 140)),       # gray
}

ROW_LABEL_RU = {
    "melee": "БЛИЖНИЙ",
    "ranged": "ДАЛЬНИЙ",
    "siege": "ОСАДА",
    "agile": "УНИВ.",
}

TYPE_LABEL_RU = {
    "unit": "БОЕЦ",
    "weather": "ПОГОДА",
    "leader": "ЛИДЕР",
    "special": "ОСОБАЯ",
}

RARITY_BORDER_COLOR = {
    Rarity.COMMON.value: (180, 180, 180),
    Rarity.RARE.value: (60, 120, 220),
    Rarity.EPIC.value: (180, 80, 220),
    Rarity.LEGENDARY.value: (240, 200, 60),
}


def _hex_to_rgb(h: str | None) -> tuple[int, int, int] | None:
    if not h:
        return None
    s = h.lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _rounded_rect_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", size, top)
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return base


def _text_centered(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, y: int, w: int, fill=(255, 255, 255)) -> int:
    """Draw text horizontally centered. Returns the y position below the text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (w - text_w) // 2 - bbox[0]
    draw.text((x, y), text, font=font, fill=fill)
    return y + text_h


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Greedy word-wrap that respects Russian/Cyrillic word boundaries."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    cur = ""
    # Use a dummy draw to measure text
    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    for word in words:
        candidate = (cur + " " + word).strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if (bbox[2] - bbox[0]) > max_width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines


def render_card_image(card: Card, faction_color_hex: str | None = None) -> Image.Image:
    """Render a single card as a PIL Image (RGB).

    All measurements are derived from CARD_W / CARD_H via a scale factor,
    so changing the card dimensions at the top of the file automatically
    scales every element (fonts, badges, paddings) proportionally.
    """
    # Scale factor: 1.0 at the original 240x336 size.
    scale = CARD_W / 240

    # Derived measurements
    pad = int(12 * scale)             # outer padding
    strength_circle_size = int(52 * scale)
    strength_circle_pad = pad
    strength_font_size = max(20, int(48 * scale))
    star_font_size = max(16, int(28 * scale))
    star_x_offset = int(36 * scale)
    star_y = int(18 * scale)
    name_font_size = max(14, int(20 * scale))
    name_y = int(82 * scale)
    mid_font_size = max(11, int(14 * scale))
    mid_y = int(120 * scale)
    divider_y = int(150 * scale)
    divider_pad = int(30 * scale)
    eff_font_size = max(10, int(12 * scale))
    eff_y_start = int(160 * scale)
    eff_line_height = int(16 * scale)
    desc_font_size = max(10, int(11 * scale))
    desc_line_height = int(14 * scale)
    desc_pad = int(24 * scale)
    tags_font_size = max(9, int(10 * scale))
    tags_y_offset = int(16 * scale)
    border_width = int(4 * scale) if card.hero else int(2 * scale)

    # Determine palette
    palette = FACTION_PALETTES.get(card.faction_id, FACTION_PALETTES["neutral"])
    faction_override = _hex_to_rgb(faction_color_hex)
    if faction_override:
        top = tuple(max(0, c - 30) for c in faction_override)
        bottom = faction_override
        palette = (top, bottom)  # type: ignore[assignment]

    # Background gradient
    bg = _vertical_gradient((CARD_W, CARD_H), palette[0], palette[1])

    # Apply rounded corners via mask
    mask = _rounded_rect_mask((CARD_W, CARD_H), CORNER_RADIUS)
    card_img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card_img.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(card_img)

    # Border (rarity color)
    rarity_color = RARITY_BORDER_COLOR.get(card.rarity.value, (180, 180, 180))
    draw.rounded_rectangle(
        (border_width // 2, border_width // 2, CARD_W - border_width // 2 - 1, CARD_H - border_width // 2 - 1),
        radius=max(1, CORNER_RADIUS - border_width // 2),
        outline=rarity_color + (255,),
        width=border_width,
    )

    # Strength number (top-left, big)
    if card.is_unit:
        strength_font = _load_font(strength_font_size, bold=True)
        s_text = str(card.base_strength)
        # Background circle for the strength number
        circle_x0 = strength_circle_pad
        circle_y0 = strength_circle_pad
        circle_x1 = strength_circle_pad + strength_circle_size
        circle_y1 = strength_circle_pad + strength_circle_size
        draw.ellipse(
            (circle_x0, circle_y0, circle_x1, circle_y1),
            fill=(20, 20, 20, 220),
            outline=rarity_color + (255,),
            width=max(1, int(2 * scale)),
        )
        bbox = draw.textbbox((0, 0), s_text, font=strength_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (
                circle_x0 + (strength_circle_size - tw) // 2 - bbox[0],
                circle_y0 + (strength_circle_size - th) // 2 - bbox[1],
            ),
            s_text,
            font=strength_font,
            fill=(255, 235, 80),
        )

    # Hero star (top-right)
    if card.hero:
        star_font = _load_font(star_font_size, bold=True)
        draw.text((CARD_W - star_x_offset, star_y), "★", font=star_font, fill=(240, 200, 60))

    # Card name (centered, top)
    name_font = _load_font(name_font_size, bold=True)
    name = card.name
    bbox = draw.textbbox((0, 0), name, font=name_font)
    max_name_width = CARD_W - desc_pad
    while (bbox[2] - bbox[0]) > max_name_width and len(name) > 4:
        name = name[:-1]
        bbox = draw.textbbox((0, 0), name + "…", font=name_font)
    if name != card.name:
        name = name + "…"
    _text_centered(draw, name, name_font, y=name_y, w=CARD_W, fill=(255, 255, 255))

    # Row/Type indicator (middle)
    type_label = TYPE_LABEL_RU.get(card.type.value, card.type.value.upper())
    if card.is_unit and card.row:
        row_label = ROW_LABEL_RU.get(card.row.value, card.row.value.upper())
        mid_text = f"{type_label} · {row_label}"
    else:
        mid_text = type_label
    mid_font = _load_font(mid_font_size, bold=False)
    _text_centered(draw, mid_text, mid_font, y=mid_y, w=CARD_W, fill=(220, 220, 220))

    # Decorative line
    draw.line(
        [(divider_pad, divider_y), (CARD_W - divider_pad, divider_y)],
        fill=rarity_color + (180,),
        width=max(1, int(scale)),
    )

    # Effects summary
    if card.effects:
        eff_font = _load_font(eff_font_size, bold=False)
        eff_lines: list[str] = [f"▸ {eff.type}" for eff in card.effects[:3]]
        y = eff_y_start
        for line in eff_lines:
            _text_centered(draw, line, eff_font, y=y, w=CARD_W, fill=(255, 220, 150))
            y += eff_line_height

    # Description (wrapped, at the bottom)
    desc_font = _load_font(desc_font_size, bold=False)
    desc = card.description or ""
    desc_lines = _wrap_text(desc, desc_font, CARD_W - desc_pad)
    y = CARD_H - tags_y_offset - desc_line_height * len(desc_lines)
    if y < divider_y + int(20 * scale):
        y = divider_y + int(20 * scale)
        desc_lines = desc_lines[: (CARD_H - tags_y_offset - y) // desc_line_height]
    for line in desc_lines:
        _text_centered(draw, line, desc_font, y=y, w=CARD_W, fill=(200, 200, 200))
        y += desc_line_height

    # Tags at very bottom
    if card.tags:
        tags_font = _load_font(tags_font_size, bold=False)
        tags_str = " · ".join(card.tags)
        bbox = draw.textbbox((0, 0), tags_str, font=tags_font)
        tw = bbox[2] - bbox[0]
        if tw < CARD_W - desc_pad:
            draw.text(
                ((CARD_W - tw) // 2, CARD_H - tags_y_offset),
                tags_str,
                font=tags_font,
                fill=(160, 160, 160),
            )

    return card_img


async def generate_all_cards(only_card_id: str | None = None, width: int | None = None, height: int | None = None) -> int:
    """Generate PNGs for every card (or just one). Returns count generated.

    If width/height are provided, they override the module-level CARD_W/CARD_H
    for this run — useful for regenerating at a different resolution without
    editing source.
    """
    global CARD_W, CARD_H, CORNER_RADIUS
    if width and height:
        CARD_W = width
        CARD_H = height
        CORNER_RADIUS = int(width * 16 / 240)  # scale corners proportionally
        log.info("Overriding card dimensions to %dx%d", CARD_W, CARD_H)

    STATIC_CARDS_DIR.mkdir(parents=True, exist_ok=True)
    await Database.init_schema()
    await CardService.reload()

    factions = {f.id: f for f in await CardService.list_factions()}
    cards = await CardService.all_cards()
    if only_card_id:
        cards = [c for c in cards if c.id == only_card_id]
        if not cards:
            log.error("Card not found: %s", only_card_id)
            return 0

    count = 0
    for card in cards:
        faction = factions.get(card.faction_id)
        faction_color = faction.color if faction else None
        img = render_card_image(card, faction_color)
        out_path = STATIC_CARDS_DIR / f"{card.id}.png"
        img.save(out_path, "PNG")
        log.info("Rendered %s -> %s", card.id, out_path.name)
        count += 1
    return count


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate card images.")
    p.add_argument("--card-id", type=str, default=None, help="Render only this card id")
    p.add_argument(
        "--width", type=int, default=None,
        help="Override card width (default: 600). Height must also be provided.",
    )
    p.add_argument(
        "--height", type=int, default=None,
        help="Override card height (default: 840). Width must also be provided.",
    )
    return p.parse_args()


async def main() -> int:
    setup_logging()
    args = parse_args()
    # Ensure DB has cards imported first
    from app.config import FACTIONS_JSON, LEADERS_JSON
    await import_factions_from_json(FACTIONS_JSON)
    await import_leaders_from_json(LEADERS_JSON)
    await import_all_cards_from_dir(CARDS_JSON_DIR)
    n = await generate_all_cards(
        only_card_id=args.card_id,
        width=args.width,
        height=args.height,
    )
    log.info("Generated %d card image(s) in %s", n, STATIC_CARDS_DIR)
    await Database.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
