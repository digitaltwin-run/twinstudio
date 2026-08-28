"""Single resource loader for source and engineering feature-lens catalogs."""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

import yaml

from twinstudio.domain import FeatureLensCatalog


@lru_cache(maxsize=None)
def load_lens_catalog_resource(resource_name: str) -> FeatureLensCatalog:
    source = files("twinstudio").joinpath(f"data/{resource_name}")
    return FeatureLensCatalog.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
