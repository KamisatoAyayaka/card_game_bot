"""Weather effect — sets strength of all non-hero units in target_row to 1.

Card JSON form:
    {"type": "weather", "params": {"target_row": "melee"}}
"""
from __future__ import annotations

from .base import Effect, EffectContext
from app.models.card import Row


class WeatherEffect(Effect):
    type_id = "weather"

    async def on_played(self, ctx: EffectContext) -> None:
        target_row_raw = self.params.get("target_row")
        if not target_row_raw:
            return
        try:
            target_row = Row(target_row_raw)
        except ValueError:
            return
        ctx.board.set_weather(target_row, True)
        ctx.log.append(
            f"Погода «{ctx.card_instance.card.name}» накрыла ряд «{target_row.value}»."
        )


class ClearWeatherEffect(Effect):
    type_id = "clear_weather"

    async def on_played(self, ctx: EffectContext) -> None:
        ctx.board.clear_all_weather()
        ctx.log.append("Все эффекты погоды сняты.")
