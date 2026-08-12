from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

import yaml

from twinstudio.evolution_models import EvolutionLifecycleTemplate, LifecycleTemplateCatalog


@lru_cache(maxsize=1)
def load_lifecycle_templates() -> LifecycleTemplateCatalog:
    source = files("twinstudio").joinpath("data/lifecycle_templates.yaml")
    return LifecycleTemplateCatalog.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


class LifecycleRegistry:
    def __init__(self, catalog: LifecycleTemplateCatalog | None = None):
        self.catalog = catalog or load_lifecycle_templates()
        self.by_id = {item.template_id: item for item in self.catalog.templates}

    def get(self, template_id: str) -> EvolutionLifecycleTemplate:
        try:
            return self.by_id[template_id]
        except KeyError as exc:
            available = ", ".join(sorted(self.by_id))
            raise ValueError(f"Unknown lifecycle template {template_id!r}. Available: {available}") from exc
