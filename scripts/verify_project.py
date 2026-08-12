from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import yaml

from twinstudio.domain import ProjectSnapshot
from twinstudio.dsl import compile_dsl, parse_dsl
from twinstudio.evolution import ProjectEvolutionEngine
from twinstudio.feature_lenses import FeatureLensEngine
from twinstudio.settings import settings


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subprocess_check(name: str, command: list[str], *, root: Path, env: dict[str, str] | None = None) -> dict:
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        env=env,
    )
    return {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


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
            proto_errors.append(f"{path.relative_to(root)}: unexpected compatibility package")
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
            "note": "The lps.v1 package is retained as a wire-compatibility namespace. Static source check only; use buf/protoc in CI for compiler validation.",
        }
    )

    schema_errors: list[str] = []
    schema_files = sorted((root / "schemas").glob("*.json"))
    for path in schema_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - release verification boundary
            schema_errors.append(f"{path.name}: {exc}")
    grammar = root / "schemas" / "twinscript.ebnf"
    if not grammar.is_file() or "version-statement" not in grammar.read_text(encoding="utf-8"):
        schema_errors.append("TwinScript EBNF missing or incomplete")
    package_grammar = root / "src" / "twinstudio" / "data" / "twinscript.ebnf"
    if grammar.is_file() and package_grammar.is_file() and grammar.read_bytes() != package_grammar.read_bytes():
        schema_errors.append("packaged grammar differs from source grammar")
    canonical_schema = root / "schemas" / "twin-dsl.schema.json"
    package_schema = root / "src" / "twinstudio" / "data" / "twin-dsl.schema.json"
    if canonical_schema.is_file() and package_schema.is_file() and canonical_schema.read_bytes() != package_schema.read_bytes():
        schema_errors.append("packaged DSL schema differs from source schema")
    checks.append(
        {
            "name": "schema_and_grammar",
            "status": "passed" if not schema_errors else "failed",
            "json_files": len(schema_files),
            "schema_documents": max(len(schema_files) - 1, 0),
            "errors": schema_errors,
        }
    )

    evolution_engine = ProjectEvolutionEngine(replace(settings, litellm_model=""))
    evolution_catalog = evolution_engine.catalog
    feature_catalog = FeatureLensEngine(replace(settings, litellm_model="")).catalog
    active_lenses = sum(1 for lens in feature_catalog.lenses if lens.enabled)
    catalog_ok = (
        len(evolution_catalog.verb_graph) == 20
        and len(evolution_catalog.extension_dimensions) == 34
        and len(evolution_catalog.operators) == 17
        and len(evolution_catalog.lifecycle_templates) == 3
        and feature_catalog.declared_lens_count == 50
        and active_lenses == 49
    )
    checks.append(
        {
            "name": "evolution_catalogs",
            "status": "passed" if catalog_ok else "failed",
            "controlled_verbs": len(evolution_catalog.verb_graph),
            "extension_dimensions": len(evolution_catalog.extension_dimensions),
            "operators": len(evolution_catalog.operators),
            "lifecycle_templates": {
                template_id: len(template.stages)
                for template_id, template in evolution_catalog.lifecycle_templates.items()
            },
            "declared_feature_lenses": feature_catalog.declared_lens_count,
            "active_feature_lenses": active_lenses,
        }
    )

    dsl_errors: list[str] = []
    documents: list[dict] = []
    source_root = root / "examples" / "evolution" / "rpi5-hinge-evolution"
    for suffix, source_format in ((".twin", "twin"), (".yaml", "yaml"), (".json", "json")):
        parsed = parse_dsl(source_root.with_suffix(suffix).read_text(encoding="utf-8"), source_format=source_format)
        if not parsed.valid or parsed.document is None:
            dsl_errors.extend(f"{suffix}: {item.code}: {item.message}" for item in parsed.diagnostics)
        else:
            documents.append(parsed.document.model_dump(mode="json"))
    if documents and not all(document == documents[0] for document in documents[1:]):
        dsl_errors.append("TwinScript/YAML/JSON canonical documents differ")
    compilation = None
    if documents:
        parsed = parse_dsl(source_root.with_suffix(".twin").read_text(encoding="utf-8"), source_format="twin")
        if parsed.document is not None:
            compilation = compile_dsl(
                snapshot,
                parsed.document,
                evolution_engine,
                actor="verification@twinstudio.local",
            )
            if not compilation.valid or compilation.evolution_run is None:
                dsl_errors.append("evolution example did not compile")
    checks.append(
        {
            "name": "dsl_equivalence_and_evolution",
            "status": "passed" if not dsl_errors else "failed",
            "formats": 3,
            "goal_variants": len(compilation.evolution_run.goal_variants) if compilation and compilation.evolution_run else 0,
            "resources": len(compilation.evolution_run.resources) if compilation and compilation.evolution_run else 0,
            "candidates": len(compilation.evolution_run.candidates) if compilation and compilation.evolution_run else 0,
            "shortlist": len(compilation.evolution_run.selected_candidate_ids) if compilation and compilation.evolution_run else 0,
            "change_plans": len(compilation.change_plans) if compilation else 0,
            "errors": dsl_errors,
        }
    )

    bundle_path = root / "examples" / "rpi5-camera3" / "demo-rpi5.twinstudio.zip"
    bundle_errors: list[str] = []
    bundle_summary: dict[str, object] = {}
    if not bundle_path.is_file():
        bundle_errors.append("portable demo bundle is missing")
    else:
        try:
            with zipfile.ZipFile(bundle_path) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    bundle_errors.append(f"corrupt ZIP member: {bad_member}")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("format") != "twinstudio-project-bundle":
                    bundle_errors.append("unexpected bundle format")
                if manifest.get("missing_artifacts"):
                    bundle_errors.append("bundle reports missing artifacts")
                for item in manifest.get("files", []):
                    payload = archive.read(item["path"])
                    if len(payload) != item["size_bytes"]:
                        bundle_errors.append(f"size mismatch: {item['path']}")
                    if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                        bundle_errors.append(f"hash mismatch: {item['path']}")
                bundled_snapshot = json.loads(archive.read("project.snapshot.json"))
                bundle_summary = {
                    "entries": len(archive.namelist()),
                    "manifest_files": len(manifest.get("files", [])),
                    "stream_version": bundled_snapshot.get("stream_version"),
                    "objects": len(bundled_snapshot.get("objects", {})),
                    "artifacts": len(bundled_snapshot.get("artifacts", {})),
                    "evolution_runs": len(bundled_snapshot.get("evolution_runs", {})),
                    "change_plans": len(bundled_snapshot.get("change_plans", {})),
                    "dsl_executions": len(bundled_snapshot.get("dsl_executions", {})),
                }
        except Exception as exc:  # pragma: no cover - release verification boundary
            bundle_errors.append(str(exc))
    checks.append(
        {
            "name": "portable_demo_bundle",
            "status": "passed" if not bundle_errors else "failed",
            "path": str(bundle_path.relative_to(root)),
            "size_bytes": bundle_path.stat().st_size if bundle_path.is_file() else 0,
            **bundle_summary,
            "errors": bundle_errors,
        }
    )

    html = (root / "src" / "twinstudio" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "src" / "twinstudio" / "static" / "app.js").read_text(encoding="utf-8")
    html_ids = re.findall(r'\bid="([^"]+)"', html)
    js_refs = set(re.findall(r"\$\('([^']+)'\)", javascript))
    duplicate_ids = sorted({item for item in html_ids if html_ids.count(item) > 1})
    missing_refs = sorted(js_refs - set(html_ids))
    checks.append(
        {
            "name": "web_dom_contract",
            "status": "passed" if not duplicate_ids and not missing_refs else "failed",
            "html_id_count": len(html_ids),
            "javascript_id_reference_count": len(js_refs),
            "duplicate_ids": duplicate_ids,
            "missing_references": missing_refs,
        }
    )

    environment = {**os.environ, "PYTHONPATH": str(root / "src"), "MQTT_ENABLED": "false"}
    compile_check = _subprocess_check(
        "python_compileall",
        [sys.executable, "-m", "compileall", "-q", "src", "scripts", "services", "components", "tests"],
        root=root,
        env=environment,
    )
    checks.append(compile_check)

    node = shutil.which("node")
    if node:
        checks.append(
            _subprocess_check(
                "browser_javascript_syntax",
                [node, "--check", str(root / "src" / "twinstudio" / "static" / "app.js")],
                root=root,
                env=environment,
            )
        )
    else:
        checks.append({"name": "browser_javascript_syntax", "status": "skipped", "reason": "node not installed"})

    cli_check = _subprocess_check(
        "cli_discovery",
        [sys.executable, "-m", "twinstudio.cli", "--help"],
        root=root,
        env=environment,
    )
    cli_check["commands_present"] = all(
        command in cli_check.get("stdout", "")
        for command in ("dsl-parse", "dsl-preview", "dsl-apply", "evolution-runs", "lifecycles")
    )
    if cli_check["status"] == "passed" and not cli_check["commands_present"]:
        cli_check["status"] = "failed"
    checks.append(cli_check)

    if run_tests:
        pytest_check = _subprocess_check(
            "pytest",
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"],
            root=root,
            env=environment,
        )
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--collect-only"],
            cwd=root,
            text=True,
            capture_output=True,
            env=environment,
        )
        match = re.search(r"(\d+) tests collected", collected.stdout)
        pytest_check["collected_tests"] = int(match.group(1)) if match else None
        checks.append(pytest_check)

    return {
        "product": "TwinStudio",
        "version": "0.5.0",
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
