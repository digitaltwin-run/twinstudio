from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

import yaml

from twinstudio.evolution_models import EvolutionCatalog


@lru_cache(maxsize=1)
def load_evolution_catalog() -> EvolutionCatalog:
    """Load TwinStudio-authored evolution extensions and lifecycle lists.

    The catalog explicitly labels itself as a platform extension.  The separate
    feature-lens catalog remains the source-grounded transcription of the supplied
    viewing-lens material.
    """

    source = files("twinstudio").joinpath("data/evolution_catalog.yaml")
    return EvolutionCatalog.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
