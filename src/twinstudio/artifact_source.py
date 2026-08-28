"""Wspólne zabezpieczenia dla tekstowych DSL artefaktów."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_text(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def resolve_artifact_source(
    root: Path,
    relative: str,
    *,
    suffix: str,
    label: str,
    error_type: type[ValueError],
) -> Path:
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        raise error_type(f"{label} source path must be relative")
    resolved_root = root.resolve()
    path = (resolved_root / relative).resolve()
    if (
        not path.is_relative_to(resolved_root)
        or not path.is_file()
        or path.is_symlink()
        or path.suffix.lower() != suffix
    ):
        raise error_type(
            f"{label} source is outside the configured artifact root or does not exist"
        )
    return path
