"""Hero effect — passive immunity marker.

Hero cards are flagged `hero: true` in their JSON. They are immune to:
- Weather effects (the board's `set_weather` skips them when computing strength)
- Scorch (the Scorch effect skips them by default — see scorch.py)
- Morale Boost does *not* affect them (Gwent classic rule)

There is no runtime `Effect` to invoke; this file exists only so that
authors can attach `{ "type": "hero_passive" }` for documentation if desired.
The engine checks `card.hero` directly when computing immunities.
"""
from __future__ import annotations

from .base import Effect, EffectContext


class HeroPassiveEffect(Effect):
    """No-op marker. Real hero behaviour lives in the board/scorch code."""
    type_id = "hero_passive"

    async def on_played(self, ctx: EffectContext) -> None:
        return None
