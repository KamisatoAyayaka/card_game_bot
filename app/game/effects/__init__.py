"""Effects package — pluggable card-effect framework.

To add a new effect:
  1. Subclass `Effect` in a new file `your_effect.py`.
  2. Set `type_id` to the string used in card JSON (`effects[].type`).
  3. Override the lifecycle hooks you need (on_played, on_round_end, etc.).
  4. Register it in `app/game/effects/__init__.py` via `EFFECT_REGISTRY.register(YourEffect)`.
  5. Reference it from card JSON: `"effects": [{"type": "your_type", "params": {...}}]`.

The engine will instantiate and invoke the effect automatically when the card is played.
"""
from .base import Effect, EffectContext
from .registry import EFFECT_REGISTRY, EffectRegistry, EffectNotFoundError

# Import and register all built-in effects.
from . import builtin  # noqa: F401  (side-effect: registers built-ins)

__all__ = [
    "Effect",
    "EffectContext",
    "EFFECT_REGISTRY",
    "EffectRegistry",
    "EffectNotFoundError",
]
