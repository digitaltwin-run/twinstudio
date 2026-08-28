"""Wspólne zabezpieczenia dla tekstowych DSL artefaktów."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

SourceModel = TypeVar("SourceModel")
DocumentModel = TypeVar("DocumentModel")


def sha256_text(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def content_addressed_source(
    model: Callable[..., SourceModel], source: str, path: str
) -> SourceModel:
    """Bind a text DSL source model to the exact content it was parsed from."""

    return model(path=path, sha256=sha256_text(source))


def content_addressed_document(
    document_model: Callable[..., DocumentModel],
    source_model: Callable[..., SourceModel],
    source: str,
    path: str,
    **content: object,
) -> DocumentModel:
    """Build a parsed DSL document with a content-bound source descriptor."""

    return document_model(
        source=content_addressed_source(source_model, source, path), **content
    )


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
