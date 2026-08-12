"""Compatibility namespace for TwinStudio 0.4.

New code should import :mod:`twinstudio`.  This namespace remains available for
one migration cycle and emits a deprecation warning only when imported.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "living_product_studio is deprecated; import twinstudio instead",
    DeprecationWarning,
    stacklevel=2,
)

from twinstudio import __product__, __version__  # noqa: E402,F401

__all__ = ["__product__", "__version__"]
