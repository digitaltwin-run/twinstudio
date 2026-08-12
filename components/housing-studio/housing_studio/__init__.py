"""Parametric 2D/3D housing generator with LiteLLM-assisted configuration."""

from .models import ProjectConfig, default_project_config
from .version import __version__

__all__ = ["ProjectConfig", "default_project_config", "__version__"]
