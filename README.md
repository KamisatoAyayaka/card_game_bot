# Gwent-like Discord Card Game

A multiplayer Discord bot for a card game inspired by the mechanics of **Gwent** (Witcher 3),
but with a completely original universe, factions, art, and effects.

The framework is designed so that new cards, factions, and effects can be added
**by dropping a JSON file** into `data/cards/` (or by inserting rows into SQLite)
— no Python code changes required for content additions.

## Features

- Python 3.11 + discord.py 2.x
- SQLite for runtime storage + JSON import/export for manual card authoring
- 2–4 players per match (configurable)
- Full Gwent ruleset:
  - Three combat rows per player (Melee / Ranged / Siege)
  - Weather effects (Frost / Fog / Rain) — sets row units to strength 1
  - Hero cards (immune to weather and most abilities)
  - Spy (play on opponent's side, draw 2 cards)
  - Medic (revive a non-hero unit from discard)
  - Muster (summon all copies of the same unit)
  - Morale Boost (+1 to all other units in the row)
  - Scorch (destroy the strongest unit(s) on the board)
  - Decoy (swap with a friendly unit, return it to hand)
  - Leader abilities (one per faction, once per round)
  - Siege/zone battlefield rows
- Configurable match format: BO1 / BO3 / BO5
- Slash commands + Discord UI components (buttons, select menus, modals)
- Deck builder + preset decks
- Player statistics (wins / losses / ELO) in SQLite
- Designed for render.com deployment

## Project Structure

```
.
├── app/
│   ├── main.py                 # Entrypoint: launches HTTP health server + Discord bot
│   ├── config.py               # Environment configuration
│   ├── bot.py                  # discord.Bot client setup, slash command registration
│   ├── database.py             # aiosqlite connection manager
│   ├── models/                 # Pydantic + DB models (Card, Faction, Player, Match)
│   ├── data/                   # Static JSON content (cards, factions, leaders, presets)
│   ├── game/                   # Pure game engine (no Discord coupling)
│   │   ├── engine.py           # Match state machine
│   │   ├── board.py            # Battlefield with rows
│   │   ├── round.py            # Round lifecycle
│   │   ├── deck.py             # Deck shuffle/draw
│   │   └── effects/            # Effect framework + registry + concrete effects
│   ├── services/               # Business logic (card_service, deck_service, etc.)
│   ├── ui/                     # Discord views, embeds, components
│   ├── commands/               # Slash command groups
│   └── utils/                  # Helpers, logging
├── data/                       # SQLite DB lives here at runtime
│   ├── cards/                  # JSON card definitions (one file per faction)
│   ├── factions.json           # Faction metadata
│   ├── leaders.json            # Leader cards with abilities
│   └── presets/                # Pre-built decks
├── scripts/
│   ├── init_db.py              # Initialize SQLite schema
│   ├── seed_cards.py           # Import JSON into SQLite
│   └── export_cards.py         # Export SQLite → JSON (for manual editing workflow)
├── tests/
├── requirements.txt
├── render.yaml                 # render.com deployment config
├── .env.example
└── Procfile
```

## Quick Start (Local Dev)

```bash
# 1. Clone & install deps
pip install -r requirements.txt

# 2. Copy env config and fill in your Discord token
cp .env.example .env
# edit .env — set DISCORD_TOKEN, DISCORD_APPLICATION_ID

# 3. Initialize the database and import seed cards
python -m scripts.init_db
python -m scripts.seed_cards

# 4. Run the bot
python -m app.main
```

## Deployment on render.com

1. Push the repo to GitHub.
2. In render.com dashboard: **New → Web Service** → connect your repo.
3. render.yaml will be detected automatically — confirm the env vars
   (`DISCORD_TOKEN`, `DISCORD_APPLICATION_ID`, `PUBLIC_BASE_URL`).
4. The service exposes `/health` for render's health checks.
5. The persistent disk at `/var/data` keeps the SQLite DB across restarts.

## Adding New Cards (Manual Workflow)

There are **two equivalent ways** to add cards:

### A. JSON file (recommended for content authors)

1. Drop a JSON file into `data/cards/`. Format (see `data/cards/example_faction.json`):

```json
{
  "id": "iron_legionnaire",
  "name": "Iron Legionnaire",
  "faction_id": "iron_legion",
  "type": "unit",
  "row": "melee",
  "base_strength": 4,
  "tags": ["soldier", "human"],
  "hero": false,
  "effects": [
    { "type": "morale_boost" }
  ],
  "description": "A disciplined melee fighter. Boosts adjacent allies.",
  "art_url": null,
  "rarity": "common"
}
```

2. Run the import:

```bash
python -m scripts.seed_cards --file data/cards/your_file.json
# or import everything:
python -m scripts.seed_cards --all
```

3. Restart the bot (or run `/admin reload-cards` if you are an admin).

### B. SQLite directly

Use any SQLite client to insert into the `cards` table. Then run:

```bash
python -m scripts.export_cards   # dumps current DB → data/cards/*.json
```

This is useful if you prefer to author in the DB and keep JSON as a snapshot.

## Adding New Effects (Developer Workflow)

Effects are Python classes registered in `app/game/effects/registry.py`.

1. Create a new file `app/game/effects/my_effect.py`:

```python
from .base import Effect, EffectContext

class MyEffect(Effect):
    type_id = "my_effect"
    
    async def on_played(self, ctx: EffectContext) -> None:
        # ctx.board, ctx.player, ctx.card_instance, ctx.match
        target_row = ctx.board.row_for(ctx.player, "melee")
        for unit in target_row.units:
            unit.bonus_strength += 2
```

2. Register it in `app/game/effects/__init__.py`:

```python
from .my_effect import MyEffect
EFFECT_REGISTRY.register(MyEffect)
```

3. Reference it from a card JSON:

```json
"effects": [
  { "type": "my_effect", "params": {} }
]
```

That's it — the engine will instantiate and call your effect automatically.

## Card JSON Schema

| Field             | Type     | Required | Description                                                  |
|-------------------|----------|----------|--------------------------------------------------------------|
| `id`              | string   | yes      | Unique snake_case identifier                                 |
| `name`            | string   | yes      | Display name                                                 |
| `faction_id`      | string   | yes      | Faction ID or `"neutral"`                                    |
| `type`            | string   | yes      | `unit` / `weather` / `leader` / `special`                    |
| `row`             | string   | for unit | `melee` / `ranged` / `siege`                                 |
| `base_strength`   | int      | for unit | Base power (0 for non-unit)                                  |
| `tags`            | string[] | no       | Categorical tags (e.g. `["soldier", "machine"]`)             |
| `hero`            | bool     | no       | If true — immune to weather & most abilities                 |
| `effects`         | object[] | no       | List of `{ "type": "...", "params": {...} }`                 |
| `description`     | string   | no       | Flavor / rules text shown in card embed                      |
| `art_url`         | string?  | no       | Optional image URL                                          |
| `rarity`          | string   | no       | `common` / `rare` / `epic` / `legendary`                     |

## Discord Commands

| Command                            | Description                                        |
|------------------------------------|----------------------------------------------------|
| `/gwent challenge @user [...]`     | Start a match (configurable rounds & player count) |
| `/gwent surrender`                 | Forfeit current match                              |
| `/gwent info`                      | Show current match state                           |
| `/deck list`                       | List your saved decks                              |
| `/deck build <faction>`            | Open the interactive deck builder                  |
| `/deck save <name>`                | Save current deck-in-progress                      |
| `/deck use <name>`                 | Set a saved deck as your active deck               |
| `/deck presets`                    | List available preset decks                        |
| `/card search <query>`             | Search cards by name/tag                           |
| `/card info <card_id>`             | Show full card details                             |
| `/stats`                           | Your win/loss/ELO                                  |
| `/leaderboard`                     | Top players                                        |
| `/admin reload-cards`              | Re-import JSON cards into SQLite (admin only)      |
| `/admin export-cards`              | Dump SQLite → JSON (admin only)                    |

## License

MIT — see `LICENSE` file (to be added).
