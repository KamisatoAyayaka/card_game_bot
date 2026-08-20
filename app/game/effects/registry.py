"""Effect registry — maps string type ids to Effect subclasses."""
from __future__ import annotations

from typing import Type

from .base import Effect


class EffectNotFoundError(KeyError):
    """Raised when a card JSON references an effect type that has no registered class."""


class EffectRegistry:
    """Simple registry mapping `type_id` -> Effect subclass."""

    def __init__(self) -> None:
        self._types: dict[str, Type[Effect]] = {}

    def register(self, effect_cls: Type[Effect]) -> Type[Effect]:
        if not effect_cls.type_id:
            raise ValueError(
                f"{effect_cls.__name__} must set a non-empty `type_id` class attribute."
            )
        if effect_cls.type_id in self._types:
            # Re-registration is allowed (useful for hot reload), but log it.
            pass
        self._types[effect_cls.type_id] = effect_cls
        return effect_cls

    def get(self, type_id: str) -> Type[Effect]:
        if type_id not in self._types:
            raise EffectNotFoundError(
                f"No effect registered for type_id={type_id!r}. "
                f"Did you forget to register it in app/game/effects/__init__.py?"
            )
        return self._types[type_id]

    def build(self, type_id: str, params: dict | None = None) -> Effect:
        cls = self.get(type_id)
        return cls(params=params)

    def all_types(self) -> list[str]:
        return sorted(self._types.keys())


# Singleton
EFFECT_REGISTRY = EffectRegistry()
