# Gwent-like Discord Card Game

A multiplayer Discord bot for a card game inspired by the mechanics of **Gwent** (Witcher 3),
but with a completely original universe, factions, art, and effects.

The framework is designed so that new cards, factions, and effects can be added
**by dropping a JSON file** into `data/cards/` (or by inserting rows into SQLite)
— no Python code changes required for content additions.

## Features

- Python 3.11 + discord.py 2.x
- SQLite for runtime storage + JSON import/export for manual card authoring
- **Full web-based game UI** — opened in browser via Discord button (not just embeds!)
  - HTML/CSS/JS frontend styled like Gwent
  - Real-time state sync over WebSocket
  - Per-player personalized view (only you see your own hand)
  - Card images served from the bot's own static directory
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

## How it works

1. A player runs `/gwent challenge @opponent` in a Discord text channel.
2. Opponent(s) accept the invite via Discord button.
3. When the match starts, the bot posts a message with **per-player buttons**:
   clicking your button opens a personalized URL in your browser.
4. Each player's browser tab connects to the bot's WebSocket and renders the
   full game UI: opponent's board (3 rows) on top, your board on the bottom,
   your hand at the very bottom with real card images.
5. All actions (play card, pass, use leader, surrender) are sent via WebSocket.
   The engine processes them and broadcasts new state to every connected client.
6. Each player sees **only their own hand** — opponents' hands show just the card count.

## Project Structure

```
.
├── app/
│   ├── main.py                 # Entrypoint: launches web server + Discord bot
│   ├── config.py               # Environment configuration
│   ├── bot.py                  # discord.Bot client setup, slash command registration
│   ├── database.py             # aiosqlite connection manager
│   ├── models/                 # Pydantic + DB models (Card, Faction, Player, Match)
│   ├── data/                   # Static JSON content (cards, factions, leaders, presets)
│   ├── game/                   # Pure game engine (no Discord/web coupling)
│   │   ├── engine.py           # Match state machine
│   │   ├── board.py            # Battlefield with rows
│   │   ├── card_instance.py    # Per-match card state
│   │   ├── player_state.py     # Player deck/hand/discard
│   │   └── effects/            # Effect framework + registry + concrete effects
│   ├── services/               # Business logic (card_service, deck_service, etc.)
│   ├── web/                    # Web server layer (HTTP + WebSocket)
│   │   ├── routes.py           # /play, /static, /ws routes
│   │   ├── websocket.py        # WS connection manager + broadcast
│   │   └── tokens.py           # Per-match access tokens
│   ├── static/                 # Static assets served by the web server
│   │   ├── index.html          # Game UI page
│   │   ├── css/style.css       # Gwent-like styling
│   │   ├── js/app.js           # WebSocket client + rendering
│   │   └── cards/              # Generated card PNG images (240x336)
│   ├── ui/                     # Discord views, embeds, components
│   ├── commands/               # Slash command groups
│   └── utils/                  # Helpers, logging
├── scripts/
│   ├── init_db.py              # Initialize SQLite schema
│   ├── seed_cards.py           # Import JSON into SQLite
│   ├── export_cards.py         # Export SQLite → JSON
│   └── generate_card_images.py # Render card PNGs from card data
├── tests/
│   ├── smoke_test_engine.py    # Engine end-to-end test
│   └── smoke_test_web.py       # Web layer end-to-end test
├── requirements.txt
├── render.yaml                 # render.com deployment config
├── .env.example
├── .python-version             # Pins Python 3.11.9 (avoids audioop removal in 3.13+)
└── Procfile
```

## Quick Start (Local Dev)

```bash
# 1. Clone & install deps
pip install -r requirements.txt

# 2. Copy env config and fill in your Discord token + your ngrok/render URL
cp .env.example .env
# edit .env — set DISCORD_TOKEN, DISCORD_APPLICATION_ID, PUBLIC_BASE_URL

# 3. Initialize the database and import seed cards
python -m scripts.init_db
python -m scripts.seed_cards
python -m scripts.generate_card_images   # renders PNGs into app/static/cards/

# 4. Run the bot
python -m app.main
```

**Note about `PUBLIC_BASE_URL`:** for the web UI to work, the bot must be
reachable from the internet. Locally, use [ngrok](https://ngrok.com) or
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
to expose port 10000:

```bash
ngrok http 10000
# Copy the https URL it gives you (e.g. https://abc-123.ngrok.io)
# Put it in .env as PUBLIC_BASE_URL=https://abc-123.ngrok.io
```

## Deployment on render.com

1. Push the repo to GitHub.
2. In render.com dashboard: **New → Web Service** → connect your repo.
3. render.yaml will be detected automatically — confirm the env vars
   (`DISCORD_TOKEN`, `DISCORD_APPLICATION_ID`, `PUBLIC_BASE_URL`, `DEV_GUILD_ID`).
4. The service exposes `/health` for render's health checks.
5. The persistent disk at `/var/data` keeps the SQLite DB across restarts.
6. **After the first deploy**, open the render.com **Shell** and run:
   ```bash
   python -m scripts.seed_cards
   python -m scripts.generate_card_images
   ```
   This imports cards from JSON into SQLite and renders the PNG images.
   (Alternatively, use `/admin reload-cards` from Discord — but you'll still
   need to run `generate_card_images` once via shell to render the initial PNGs.)

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

### Replacing generated card images with custom art

The `generate_card_images.py` script auto-renders placeholder PNGs for every
card. To use your own custom artwork instead:

1. Drop a PNG file at `app/static/cards/{card_id}.png` — same filename as the
   card's `id` field.
2. Re-deploy. The web UI will pick up your custom image automatically.

You can mix and match: generated PNGs for cards without custom art, custom
PNGs for the cards you've drawn art for. Re-running `generate_card_images.py`
will overwrite existing files, so back up any custom art first.

### Choosing card image resolution

The default size is **600×840 px** (5:7 aspect ratio, ~35 KB per PNG). You can
change it to any size/aspect — the frontend CSS uses `object-fit: cover` so
cards always fill their slot regardless of source dimensions.

To change the default for all generated cards, edit `CARD_W` and `CARD_H`
constants at the top of `scripts/generate_card_images.py`:

```python
CARD_W = 600
CARD_H = 840   # or 1042 for taller portrait, 1050 for 4:7, etc.
```

Then regenerate:

```bash
python -m scripts.generate_card_images
```

Or override on the command line without editing source:

```bash
python -m scripts.generate_card_images --width 600 --height 1042
```

Recommended sizes:

| Size | Aspect | File size | Use case |
|------|--------|-----------|----------|
| 240×336 | 5:7 | ~10 KB | Mobile-first, low bandwidth |
| 600×840 | 5:7 | ~35 KB | **Default**, classic Gwent look |
| 600×1042 | ~4:7 | ~50 KB | Taller portrait, real playing-card ratio |
| 750×1050 | 4:7 | ~70 KB | High detail for desktop only |

**Note about custom art:** when dropping your own PNG files, any size works —
the frontend will scale them to fit the card slot (~120×168 px on screen). For
best quality on high-DPI/retina displays, use source images at least 2× the
display size, i.e. 240×336 or larger.

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
| `/gwent open`                      | Get a fresh personalized link to your active match |
| `/gwent surrender`                 | Forfeit current match                              |
| `/gwent info`                      | Show current match state (compact embed)           |
| `/gwent presets`                   | List available preset decks                        |
| `/deck list`                       | List your saved decks                              |
| `/deck build <faction>`            | Open the interactive deck builder                  |
| `/deck delete <name>`              | Delete a saved deck                                |
| `/card search <query>`             | Search cards by name/tag                           |
| `/card info <card_id>`             | Show full card details                             |
| `/card factions`                   | List all factions                                  |
| `/stats`                           | Your win/loss/ELO                                  |
| `/leaderboard`                     | Top players                                        |
| `/admin reload-cards`              | Re-import JSON cards into SQLite (admin only)      |
| `/admin export-cards`              | Dump SQLite → JSON (admin only)                    |
| `/admin add-admin user:@user`      | Grant admin rights (admin only)                    |

## License

MIT — see `LICENSE` file (to be added).
