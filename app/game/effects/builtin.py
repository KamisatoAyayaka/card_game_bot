"""Built-in effect bundle — importing this module registers all standard effects.

Custom effects added by the user should be registered in
`app/game/effects/__init__.py` AFTER this module is imported.
"""
from __future__ import annotations

from .registry import EFFECT_REGISTRY
from .weather import WeatherEffect, ClearWeatherEffect
from .spy import SpyEffect
from .medic import MedicEffect
from .muster import MusterEffect
from .morale import MoraleBoostEffect
from .scorch import ScorchEffect
from .decoy import DecoyEffect
from .hero import HeroPassiveEffect

# Register all built-ins. Order does not matter.
for _cls in (
    WeatherEffect,
    ClearWeatherEffect,
    SpyEffect,
    MedicEffect,
    MusterEffect,
    MoraleBoostEffect,
    ScorchEffect,
    DecoyEffect,
    HeroPassiveEffect,
):
    EFFECT_REGISTRY.register(_cls)
