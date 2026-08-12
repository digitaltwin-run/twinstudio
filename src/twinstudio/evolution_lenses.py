from __future__ import annotations

from functools import lru_cache

from twinstudio.domain import FeatureLens, FeatureLensCatalog
from twinstudio.evolution_catalog import load_evolution_catalog
from twinstudio.evolution_models import LensSearchSpec
from twinstudio.feature_lenses import load_feature_lens_catalog


@lru_cache(maxsize=1)
def load_extension_lens_catalog() -> FeatureLensCatalog:
    catalog = load_evolution_catalog()
    lenses = [
        FeatureLens(
            id=item.id,
            order=index,
            name=item.name,
            category=item.category,
            summary=item.summary,
            prompts=item.prompts
            or [
                f"Which assumption about {item.name.lower()} is inherited from the current design?",
                f"What nearby alternative becomes possible when {item.name.lower()} is changed?",
            ],
            enabled=True,
            source_status="extension",
            provenance="twinstudio_extension",
            tags=item.associations,
        )
        for index, item in enumerate(catalog.extension_dimensions, start=1)
    ]
    return FeatureLensCatalog(
        catalog_version=f"{catalog.catalog_version}-extensions",
        title="TwinStudio project-evolution extension lenses",
        declared_lens_count=len(lenses),
        active_lens_count=len(lenses),
        catalog_kind="twinstudio_extension",
        source_notes=[
            "These dimensions are TwinStudio extensions and are not presented as rows from the supplied fifty-lens table.",
            *catalog.source_notes,
        ],
        lenses=lenses,
    )


class EvolutionLensRegistry:
    """Expose source-grounded lenses and TwinStudio extensions with provenance."""

    def __init__(
        self,
        source_catalog: FeatureLensCatalog | None = None,
        extension_catalog: FeatureLensCatalog | None = None,
    ):
        self.source_catalog = source_catalog or load_feature_lens_catalog()
        self.extension_catalog = extension_catalog or load_extension_lens_catalog()
        self.source_by_id = {item.id: item for item in self.source_catalog.lenses if item.enabled}
        self.extension_by_id = {item.id: item for item in self.extension_catalog.lenses if item.enabled}

    @property
    def active_count(self) -> int:
        return len(self.source_by_id) + len(self.extension_by_id)

    def select(self, spec: LensSearchSpec) -> list[FeatureLens]:
        selected: list[FeatureLens] = []
        if spec.include_source_lenses:
            selected.extend(self._select_group(self.source_by_id, spec.source_lens_ids, "source"))
        if spec.include_extension_dimensions:
            selected.extend(
                self._select_group(
                    self.extension_by_id,
                    spec.extension_dimension_ids,
                    "extension",
                )
            )
        return selected[: spec.max_lenses]

    @staticmethod
    def _select_group(
        available: dict[str, FeatureLens],
        requested: list[str],
        label: str,
    ) -> list[FeatureLens]:
        if not requested or requested == ["*"]:
            return sorted(available.values(), key=lambda item: item.order)
        unknown = sorted(set(requested) - set(available))
        if unknown:
            raise ValueError(f"Unknown {label} evolution lens IDs: {', '.join(unknown)}")
        return [available[item] for item in requested]

    def payload(self, include_disabled: bool = False) -> dict:
        source = self.source_catalog.model_dump(mode="json")
        extension = self.extension_catalog.model_dump(mode="json")
        if not include_disabled:
            source["lenses"] = [item for item in source["lenses"] if item["enabled"]]
            extension["lenses"] = [item for item in extension["lenses"] if item["enabled"]]
        return {
            "source": source,
            "extensions": extension,
            "active_count": len(source["lenses"]) + len(extension["lenses"]),
            "provenance_note": (
                "The source catalog preserves the supplied feature-type table, including its unresolved count gap. "
                "The extension catalog is TwinStudio-authored and is not presented as source transcription."
            ),
        }
