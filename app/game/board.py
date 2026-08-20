"""Battlefield board — 3 rows per player (melee / ranged / siege), plus weather flags."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.game.card_instance import CardInstance
from app.models.card import Row

if TYPE_CHECKING:
    from app.game.player_state import PlayerState


# Order matters: melee is "front", siege is "back" — used by embed rendering.
ROW_ORDER: list[str] = [Row.SIEGE.value, Row.RANGED.value, Row.MELEE.value]
ALL_ROWS: list[str] = [Row.MELEE.value, Row.RANGED.value, Row.SIEGE.value]


@dataclass
class Board:
    """In-memory battlefield.

    Internal structure: dict[discord_id] -> dict[row_name] -> list[CardInstance].
    Weather is tracked per row name (a single frost affects BOTH players' melee rows).
    """
    rows: dict[int, dict[str, list[CardInstance]]] = field(default_factory=dict)
    weather: dict[str, bool] = field(default_factory=lambda: {
        Row.MELEE.value: False,
        Row.RANGED.value: False,
        Row.SIEGE.value: False,
    })

    def init_player(self, discord_id: int) -> None:
        self.rows[discord_id] = {r: [] for r in ALL_ROWS}

    # ----------------------------------------------------------- accessors
    def units_in_row(self, discord_id: int, row: str) -> list[CardInstance]:
        return self.rows.get(discord_id, {}).get(row, [])

    def all_units_for(self, discord_id: int) -> list[CardInstance]:
        out: list[CardInstance] = []
        for r in ALL_ROWS:
            out.extend(self.units_in_row(discord_id, r))
        return out

    def total_units_for(self, discord_id: int) -> int:
        return len(self.all_units_for(discord_id))

    def row_strength(self, discord_id: int, row: str) -> int:
        return sum(u.current_strength for u in self.units_in_row(discord_id, row))

    def player_strength(self, discord_id: int) -> int:
        return sum(self.row_strength(discord_id, r) for r in ALL_ROWS)

    def total_strength(self) -> int:
        return sum(self.player_strength(pid) for pid in self.rows)

    # ----------------------------------------------------------- mutators
    def add_unit(self, discord_id: int, row: str, unit: CardInstance) -> None:
        unit.row = row
        unit.location = "board"
        # Apply weather flag immediately if applicable
        unit.weathered = self.weather.get(row, False) and not unit.card.hero
        self.rows.setdefault(discord_id, {r: [] for r in ALL_ROWS}).setdefault(row, []).append(unit)

    def remove_unit(self, discord_id: int, row: str, unit: CardInstance) -> None:
        row_units = self.rows.get(discord_id, {}).get(row, [])
        if unit in row_units:
            row_units.remove(unit)
            unit.location = "discard"

    def set_weather(self, row: str, active: bool) -> None:
        self.weather[row] = active
        # Re-apply weather flag to all units in that row across all players
        for pid in self.rows:
            for unit in self.rows[pid].get(row, []):
                unit.weathered = active and not unit.card.hero

    def clear_all_weather(self) -> None:
        for r in ALL_ROWS:
            self.set_weather(r, False)

    # ---------------------------------------------------------- reset
    def reset_for_new_round(self) -> None:
        """All units on the board go to their owners' discard piles. Weather clears."""
        for pid, player_rows in self.rows.items():
            for row_name in ALL_ROWS:
                for unit in player_rows[row_name]:
                    unit.location = "discard"
                    unit.row = None
                    unit.bonus_strength = 0
                    unit.weathered = False
                player_rows[row_name] = []
        for r in ALL_ROWS:
            self.weather[r] = False
