"""Small validation primitives shared by independently versioned models."""
from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any


def require_unique_attribute(items: Iterable[Any], attribute: str, label: str) -> None:
    values = [getattr(item, attribute) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def validate_evaluation_weights(
    value: dict[str, float], allowed: Collection[str]
) -> dict[str, float]:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"Unknown evaluation dimensions: {', '.join(unknown)}")
    if not value or sum(value.values()) <= 0:
        raise ValueError("At least one positive evaluation weight is required")
    if any(weight < 0 for weight in value.values()):
        raise ValueError("Evaluation weights cannot be negative")
    return value
