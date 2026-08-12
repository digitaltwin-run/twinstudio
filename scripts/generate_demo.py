"""Generate the deterministic sample artifact set shipped with the project."""

from __future__ import annotations

import shutil
from pathlib import Path

from housing_studio.artifacts import generate_artifacts
from housing_studio.models import ProjectConfig

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    output_root = project_root / "sample_output"
    demo_dir = output_root / "demo"
    shutil.rmtree(demo_dir, ignore_errors=True)

    config = ProjectConfig.model_validate_json(
        (project_root / "examples" / "rpi5_enclosure.json").read_text(encoding="utf-8")
    )
    manifest = generate_artifacts(
        config,
        output_root,
        job_id="demo",
        source_prompt=(
            "Bundled baseline derived from the consolidated Raspberry Pi 5 housing "
            "specification. No natural-language values were changed for this snapshot."
        ),
        interpretation_mode="baseline",
        configuration_changes=[],
    )
    print(output_root / manifest["job_id"] / manifest["bundle"])
