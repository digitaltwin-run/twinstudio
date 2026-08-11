from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import yaml

from living_product_studio.domain import ProjectSnapshot


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path, *, run_tests: bool = False) -> dict:
    checks: list[dict] = []
    project_path = root / "examples" / "rpi5-camera3" / "project.json"
    snapshot = ProjectSnapshot.model_validate_json(project_path.read_text(encoding="utf-8"))
    checks.append({"name": "project_schema", "status": "passed", "objects": len(snapshot.objects)})

    missing: list[str] = []
    mismatched: list[str] = []
    for artifact in snapshot.artifacts.values():
        path = root / artifact.path
        if not path.exists():
            missing.append(artifact.uri)
        elif artifact.sha256 and sha256(path) != artifact.sha256:
            mismatched.append(artifact.uri)
    checks.append(
        {
            "name": "artifact_integrity",
            "status": "passed" if not missing and not mismatched else "failed",
            "artifact_count": len(snapshot.artifacts),
            "missing": missing,
            "hash_mismatches": mismatched,
        }
    )

    scoped_demo = root / "examples" / "rpi5-camera3" / "scoped-edit-demo" / "output"
    scoped_journal_path = scoped_demo / "operation-journal.json"
    scoped_errors: list[str] = []
    scoped_journal: dict = {}
    for name in ("scoped-result.step", "scoped-result.stl", "operation-journal.json"):
        if not (scoped_demo / name).is_file():
            scoped_errors.append(f"missing {name}")
    if scoped_journal_path.is_file():
        scoped_journal = json.loads(scoped_journal_path.read_text(encoding="utf-8"))
        if scoped_journal.get("adapter") != "cadquery-scoped-brep-v1":
            scoped_errors.append("unexpected adapter id")
        if not scoped_journal.get("result", {}).get("valid"):
            scoped_errors.append("derived B-Rep result not valid")
        if scoped_journal.get("result", {}).get("volume_delta_mm3", 0) >= 0:
            scoped_errors.append("demonstration hole did not reduce volume")
    checks.append(
        {
            "name": "scoped_brep_demo",
            "status": "passed" if not scoped_errors else "failed",
            "errors": scoped_errors,
            "volume_delta_mm3": scoped_journal.get("result", {}).get("volume_delta_mm3"),
        }
    )

    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    checks.append(
        {
            "name": "compose_yaml",
            "status": "passed",
            "services": sorted(compose.get("services", {})),
        }
    )

    proto_errors: list[str] = []
    proto_files = sorted((root / "proto").rglob("*.proto"))
    for path in proto_files:
        text = path.read_text(encoding="utf-8")
        if 'syntax = "proto3";' not in text:
            proto_errors.append(f"{path.relative_to(root)}: missing proto3 syntax")
        if "package lps.v1;" not in text:
            proto_errors.append(f"{path.relative_to(root)}: unexpected package")
        if text.count("{") != text.count("}"):
            proto_errors.append(f"{path.relative_to(root)}: unbalanced braces")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith('import "lps/'):
                imported = stripped.split('"')[1]
                if not (root / "proto" / imported).exists():
                    proto_errors.append(f"{path.relative_to(root)}: missing import {imported}")
    checks.append(
        {
            "name": "protobuf_static_structure",
            "status": "passed" if not proto_errors else "failed",
            "file_count": len(proto_files),
            "errors": proto_errors,
            "note": "Static source check only; run buf lint/protoc in CI for compiler validation.",
        }
    )

    node = shutil.which("node")
    if node:
        completed = subprocess.run(
            [node, "--check", str(root / "src" / "living_product_studio" / "static" / "app.js")],
            text=True,
            capture_output=True,
        )
        checks.append(
            {
                "name": "browser_javascript_syntax",
                "status": "passed" if completed.returncode == 0 else "failed",
                "stderr": completed.stderr,
            }
        )
    else:
        checks.append({"name": "browser_javascript_syntax", "status": "skipped", "reason": "node not installed"})

    if run_tests:
        completed = subprocess.run(
            ["python", "-m", "pytest", "-q"],
            cwd=root,
            text=True,
            capture_output=True,
            env={**__import__("os").environ, "PYTHONPATH": str(root / "src"), "MQTT_ENABLED": "false"},
        )
        checks.append(
            {
                "name": "pytest",
                "status": "passed" if completed.returncode == 0 else "failed",
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )

    return {
        "project": snapshot.project_id,
        "revision": snapshot.revision,
        "status": "passed" if all(item["status"] in {"passed", "skipped"} for item in checks) else "failed",
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = verify(args.root.resolve(), run_tests=args.run_tests)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
