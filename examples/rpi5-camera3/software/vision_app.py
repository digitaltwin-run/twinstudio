from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageStat

INPUT = Path(os.getenv("VISION_INPUT_DIR", "/input"))
OUTPUT = Path(os.getenv("VISION_OUTPUT_DIR", "/output"))
OUTPUT.mkdir(parents=True, exist_ok=True)


def analyze(path: Path) -> dict:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        stat = ImageStat.Stat(rgb)
        mean = [round(value, 3) for value in stat.mean]
        brightness = round(sum(mean) / 3.0, 3)
        return {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "width": rgb.width,
            "height": rgb.height,
            "mean_rgb": mean,
            "mean_brightness": brightness,
            "classification": "bright" if brightness >= 127.5 else "dark",
        }


results = [analyze(path) for path in sorted([*INPUT.glob("*.png"), *INPUT.glob("*.jpg")])]
report = {"application": "demo-vision-app", "schema_version": 1, "results": results}
(OUTPUT / "camera-analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
