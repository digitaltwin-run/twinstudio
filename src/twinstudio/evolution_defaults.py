"""Shared defaults for evolution operator policies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_BASE_OPERATORS = (
    ("reframe_goal", 1.0),
    ("repurpose_feature", 1.0),
    ("parameter_shift", 0.9),
    ("modularize", 0.8),
    ("make_reversible", 0.7),
    ("substitute_process", 0.6),
    ("adjacent_association", 1.0),
)


def build_default_evolution_operators(
    operator_kind: Callable[[str], Any],
    operator_spec: Callable[..., Any],
    *,
    include_crossover: bool = False,
) -> list[Any]:
    """Build typed defaults while keeping the policy table in one place."""
    definitions = _BASE_OPERATORS + (("crossover", 0.4),) if include_crossover else _BASE_OPERATORS
    return [
        operator_spec(operator=operator_kind(name), weight=weight)
        for name, weight in definitions
    ]
