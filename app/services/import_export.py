"""JSON <-> SQLite import/export for cards, factions, and leaders."""
from __future__ import annotations

import json
from pathlib import Path

from app.config import CARDS_JSON_DIR, FACTIONS_JSON, LEADERS_JSON
from app.database import get_db
from app.models.card import Card, Faction


# ---------------------------------------------------------------------------
# Factions
# ---------------------------------------------------------------------------

async def import_factions_from_json(path: Path = FACTIONS_JSON) -> int:
    if not path.exists():
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    db = await get_db()
    count = 0
    for item in raw:
        f = Faction(**item)
        await db.execute(
            """
            INSERT INTO factions (id, name, description, color, icon_url, ability_name, ability_desc)
            VALUES (:id, :name, :description, :color, :icon_url, :ability_name, :ability_desc)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                color=excluded.color,
                icon_url=excluded.icon_url,
                ability_name=excluded.ability_name,
                ability_desc=excluded.ability_desc
            """,
            {
                "id": f.id,
                "name": f.name,
                "description": f.description,
                "color": f.color,
                "icon_url": f.icon_url,
                "ability_name": f.ability_name,
                "ability_desc": f.ability_desc,
            },
        )
        count += 1
    await db.commit()
    return count


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

async def import_card(card: Card) -> None:
    db = await get_db()
    row = card.to_db_row()
    cols = list(row.keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    col_list = ", ".join(cols)
    update_cols = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    await db.execute(
        f"""
        INSERT INTO cards ({col_list})
        VALUES ({placeholders})
        ON CONFLICT(id) DO UPDATE SET {update_cols},
            updated_at=datetime('now')
        """,
        row,
    )
    await db.commit()


async def import_cards_from_json_file(path: Path) -> int:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    count = 0
    for item in raw:
        c = Card(**item)
        await import_card(c)
        count += 1
    return count


async def import_all_cards_from_dir(directory: Path = CARDS_JSON_DIR) -> int:
    """Import every *.json file in directory (non-recursive)."""
    total = 0
    for fp in sorted(directory.glob("*.json")):
        total += await import_cards_from_json_file(fp)
    return total


async def import_leaders_from_json(path: Path = LEADERS_JSON) -> int:
    if not path.exists():
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    count = 0
    for item in raw:
        c = Card(**item)
        await import_card(c)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Export: SQLite -> JSON
# ---------------------------------------------------------------------------

async def export_all_cards(directory: Path = CARDS_JSON_DIR) -> int:
    """Dump all cards from SQLite to directory, one file per faction."""
    directory.mkdir(parents=True, exist_ok=True)
    db = await get_db()

    async with db.execute("SELECT * FROM factions ORDER BY id") as cur:
        factions = [dict(r) for r in await cur.fetchall()]

    total = 0
    for f in factions:
        async with db.execute(
            "SELECT * FROM cards WHERE faction_id=? ORDER BY id", (f["id"],)
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            continue
        cards_json = [Card.from_db_row(r).model_dump(mode="json") for r in rows]
        out_path = directory / f"{f['id']}.json"
        out_path.write_text(
            json.dumps(cards_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        total += len(cards_json)
    return total


async def export_factions(path: Path = FACTIONS_JSON) -> int:
    db = await get_db()
    async with db.execute("SELECT * FROM factions ORDER BY id") as cur:
        rows = await cur.fetchall()
    if not rows:
        return 0
    data = [dict(r) for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data)


async def full_export() -> dict[str, int]:
    """Convenience: export everything."""
    cards = await export_all_cards()
    factions = await export_factions()
    return {"cards": cards, "factions": factions}
