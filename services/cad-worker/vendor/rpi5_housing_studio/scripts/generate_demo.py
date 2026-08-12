from pathlib import Path

from housing_studio.artifacts import generate_artifacts
from housing_studio.models import default_project_config

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    manifest = generate_artifacts(
        default_project_config(),
        project_root / "generated",
        job_id="demo",
        source_prompt="Default Raspberry Pi 5 enclosure specification.",
    )
    print(project_root / "generated" / manifest["job_id"] / manifest["bundle"])
