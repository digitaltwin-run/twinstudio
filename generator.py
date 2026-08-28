#!/usr/bin/env python3
"""Compatibility launcher for the canonical Housing Studio component."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent / "components" / "housing-studio"


def main() -> int:
    sys.path.insert(0, str(COMPONENT_ROOT))
    namespace = runpy.run_path(
        str(COMPONENT_ROOT / "generator.py"),
        run_name="twinstudio_housing_generator",
    )
    return int(namespace["main"]())


if __name__ == "__main__":
    raise SystemExit(main())
