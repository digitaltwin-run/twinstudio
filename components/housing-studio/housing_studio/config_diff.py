from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .models import ProjectConfig


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """One auditable change between two project configurations."""

    path: str
    before: Any
    after: Any
    kind: str = "changed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _plain(value: ProjectConfig | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, ProjectConfig):
        return value.model_dump(mode="json")
    return value


def _walk_diff(before: Any, after: Any, path: tuple[str, ...]) -> Iterable[ConfigChange]:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        for key in keys:
            next_path = (*path, str(key))
            if key not in before:
                yield ConfigChange(".".join(next_path), None, after[key], "added")
            elif key not in after:
                yield ConfigChange(".".join(next_path), before[key], None, "removed")
            else:
                yield from _walk_diff(before[key], after[key], next_path)
        return

    if isinstance(before, list) and isinstance(after, list):
        length = max(len(before), len(after))
        for index in range(length):
            next_path = (*path, str(index))
            if index >= len(before):
                yield ConfigChange(".".join(next_path), None, after[index], "added")
            elif index >= len(after):
                yield ConfigChange(".".join(next_path), before[index], None, "removed")
            else:
                yield from _walk_diff(before[index], after[index], next_path)
        return

    if before != after:
        yield ConfigChange(".".join(path), before, after, "changed")


def diff_configs(
    before: ProjectConfig | dict[str, Any],
    after: ProjectConfig | dict[str, Any],
) -> list[ConfigChange]:
    """Return a stable, leaf-level configuration diff."""

    return list(_walk_diff(_plain(before), _plain(after), ()))


def diff_as_dicts(
    before: ProjectConfig | dict[str, Any],
    after: ProjectConfig | dict[str, Any],
) -> list[dict[str, Any]]:
    return [change.to_dict() for change in diff_configs(before, after)]


def change_summary_text(changes: list[ConfigChange], *, max_items: int = 12) -> str:
    """Create a compact human-readable summary without hiding the full JSON diff."""

    if not changes:
        return "No configuration values changed."
    shown = changes[:max_items]
    chunks = [f"{change.path}: {change.before!r} -> {change.after!r}" for change in shown]
    remaining = len(changes) - len(shown)
    if remaining > 0:
        chunks.append(f"... and {remaining} more change(s)")
    return "; ".join(chunks)
