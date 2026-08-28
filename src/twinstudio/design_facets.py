from __future__ import annotations

from functools import lru_cache

from twinstudio.domain import FeatureLens, FeatureLensCatalog
from twinstudio.feature_lenses import load_feature_lens_catalog
from twinstudio.lens_catalog_io import load_lens_catalog_resource


@lru_cache(maxsize=1)
def load_engineering_lens_catalog() -> FeatureLensCatalog:
    """Load TwinStudio's explicit engineering extensions.

    The source-grounded catalog remains unchanged and separately addressable.  The
    engineering catalog is intentionally marked as an extension so callers can
    distinguish supplied-source terminology from TwinStudio additions.
    """

    return load_lens_catalog_resource("engineering_lenses.yaml")


@lru_cache(maxsize=1)
def combined_feature_lens_catalog() -> FeatureLensCatalog:
    source = load_feature_lens_catalog()
    extension = load_engineering_lens_catalog()
    lenses: list[FeatureLens] = []
    for item in source.lenses:
        lenses.append(item.model_copy(deep=True))
    offset = source.declared_lens_count
    for item in extension.lenses:
        lenses.append(item.model_copy(update={"order": offset + item.order}, deep=True))
    return FeatureLensCatalog(
        catalog_version=f"{source.catalog_version}+{extension.catalog_version}",
        title="TwinStudio combined design-facet catalog",
        declared_lens_count=len(lenses),
        active_lens_count=sum(1 for item in lenses if item.enabled),
        catalog_kind="combined",
        source_notes=[
            *source.source_notes,
            *extension.source_notes,
            "Combined order preserves source slots 1-50 and places TwinStudio extensions after them.",
        ],
        lenses=lenses,
    )


def catalog_by_kind(kind: str) -> FeatureLensCatalog:
    normalized = kind.strip().lower()
    if normalized in {"source", "source_grounded", "fifty", "viewing_lenses"}:
        return load_feature_lens_catalog()
    if normalized in {"engineering", "extension", "twinstudio_extension"}:
        return load_engineering_lens_catalog()
    if normalized in {"all", "combined"}:
        return combined_feature_lens_catalog()
    raise ValueError("catalog must be one of: source, engineering, all")


def enabled_lens_map(*, combined: bool = True) -> dict[str, FeatureLens]:
    catalog = combined_feature_lens_catalog() if combined else load_feature_lens_catalog()
    return {item.id: item for item in catalog.lenses if item.enabled}
