from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from pydantic import ValidationError

from twinstudio.change_planner import ChangePlanner
from twinstudio.domain import (
    ChangeOperationKind,
    ChangePlanLlmRequest,
    ChangePlanProposal,
    ProjectSnapshot,
    RegionSelection,
)
from twinstudio.settings import settings

ROOT = Path(__file__).resolve().parents[1]


def _wellmanifest_checker() -> Path:
    configured = os.environ.get("WELLMANIFEST_DSL_ROOT")
    candidates = [
        Path(configured) if configured else None,
        ROOT.parent.parent / "wellmanifest" / "dsl",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "src" / "dsl_check.py").is_file():
            return candidate / "src" / "dsl_check.py"
    raise RuntimeError(
        "wellmanifest/dsl is required; set WELLMANIFEST_DSL_ROOT or check it out beside digitaltwin-run"
    )


def _validate_examples() -> dict[str, int]:
    example_root = ROOT / "examples" / "change-planner"
    ChangePlanLlmRequest.model_validate_json((example_root / "valid-request.json").read_text())
    ChangePlanProposal.model_validate_json((example_root / "valid-proposal.json").read_text())
    rejected = 0
    for name, model in (
        ("invalid-request-bad-digest.json", ChangePlanLlmRequest),
        ("invalid-proposal-runtime-authority.json", ChangePlanProposal),
    ):
        try:
            model.model_validate_json((example_root / name).read_text())
        except ValidationError:
            rejected += 1
        else:
            raise AssertionError(f"invalid conformance example was accepted: {name}")
    return {"valid": 2, "invalid_rejected": rejected}


def _validate_nl_matrix() -> list[dict[str, object]]:
    project = ProjectSnapshot.model_validate_json(
        (ROOT / "examples" / "rpi5-camera3" / "project.json").read_text()
    )
    selection = RegionSelection.model_validate_json(
        (ROOT / "examples" / "rpi5-camera3" / "selections" / "example-selection.json").read_text()
    )
    planner = ChangePlanner(replace(settings, litellm_model=""))
    cases = (
        ("zmniejsz wysokość o 4 mm", "set_parameter", "height", 21.0, True),
        ("zwiększ wysokość o 4 mm", "set_parameter", "height", 29.0, True),
        ("ustaw wysokość na 21 mm", "set_parameter", "height", 21.0, True),
        ("ustaw głębokość na 10 cm", "set_parameter", "depth", 100.0, True),
        ("dodaj otwór o średnicy 3 mm", "boolean_cut", "hole", 3.0, False),
        ("dodaj fazę 45 stopni", "add_feature", "chamfer", 45.0, False),
    )
    results: list[dict[str, object]] = []
    for prompt, expected_kind, expected_name, expected_value, expected_applyable in cases:
        plan = planner.plan(prompt, selection, project, "conformance@twinstudio.local").plan
        if len(plan.operations) != 1:
            raise AssertionError(f"expected one operation for: {prompt}")
        operation = plan.operations[0]
        observed_name = operation.arguments.get("parameter") or operation.arguments.get("feature_type")
        observed_value = (
            operation.arguments.get("value")
            if "value" in operation.arguments
            else operation.arguments.get("diameter_mm", operation.arguments.get("angle_deg"))
        )
        payload = planner.compile_apply_payload(plan, project)
        applyable = bool(payload["parameter_patches"])
        observed = (operation.kind, observed_name, observed_value, applyable)
        expected = (expected_kind, expected_name, expected_value, expected_applyable)
        if observed != expected:
            raise AssertionError(f"NL mismatch for {prompt!r}: expected {expected}, observed {observed}")
        results.append(
            {
                "nl": prompt,
                "kind": operation.kind,
                "target": operation.target_uri,
                "arguments": operation.arguments,
                "runtime": "safe-parameter-patch" if applyable else "deferred-cad-operation",
            }
        )
    lid_uri = "poa://demo/demo-rpi5@main/part/lid"
    lid_selection = selection.model_copy(
        update={
            "source_view": "2d",
            "tool": "pencil",
            "screen_path": [{"x": 1130, "y": 611}],
            "ray_hits": [],
            "world_aabb": None,
            "camera": None,
            "target_object_uris": [lid_uri],
            "projection_entity_ids": ["front.lid.outer-slope"],
        }
    )
    contextual_prompt = "obniż do 14 mm"
    contextual_plan = planner.plan(
        contextual_prompt,
        lid_selection,
        project,
        "conformance@twinstudio.local",
    ).plan
    contextual_operation = contextual_plan.operations[0]
    contextual_payload = planner.compile_apply_payload(contextual_plan, project)
    observed_contextual = (
        contextual_operation.kind,
        contextual_operation.target_uri,
        contextual_operation.arguments,
        contextual_payload["parameter_patches"][0]["previous_parameter"]["value"],
    )
    expected_contextual = (
        "set_parameter",
        lid_uri,
        {"parameter": "height", "value": 14.0, "unit": "mm"},
        15.0,
    )
    if observed_contextual != expected_contextual:
        raise AssertionError(
            f"contextual NL mismatch for {contextual_prompt!r}: "
            f"expected {expected_contextual}, observed {observed_contextual}"
        )
    results.append(
        {
            "nl": contextual_prompt,
            "kind": contextual_operation.kind,
            "target": contextual_operation.target_uri,
            "arguments": contextual_operation.arguments,
            "runtime": "safe-parameter-patch-with-cad-preflight",
        }
    )
    return results


def _validate_catalog() -> list[str]:
    manifest = json.loads((ROOT / "dsl-manifest.json").read_text())
    declared = set(manifest["documentation"]["commands"])
    runtime = {item.value.upper() for item in ChangeOperationKind}
    if declared != runtime:
        raise AssertionError(
            f"operation catalog mismatch: missing={sorted(runtime - declared)}, extra={sorted(declared - runtime)}"
        )
    return sorted(declared)


def _run_standard(checker: Path, arguments: list[str]) -> str:
    completed = subprocess.run(
        [sys.executable, str(checker), *arguments],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode:
        sys.stderr.write(completed.stdout + completed.stderr)
        raise SystemExit(completed.returncode)
    return completed.stdout


def main() -> None:
    checker = _wellmanifest_checker()
    examples = _validate_examples()
    commands = _validate_catalog()
    nl_matrix = _validate_nl_matrix()
    _run_standard(
        checker,
        [
            "validate",
            "--root",
            str(ROOT),
            str(ROOT / "dsl-manifest.json"),
        ],
    )
    _run_standard(
        checker,
        [
            "changes",
            "--root",
            str(ROOT),
            "--base",
            "HEAD",
            "--head",
            "HEAD",
            "--include-worktree",
        ],
    )
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    findings = {
        "schema": "wellmanifest.dsl/findings/v1",
        "producer": {
            "id": "twinstudio.dsl-conformance",
            "version": "0.5.0",
            "adapter": "scripts/verify_dsl_conformance.py",
        },
        "subject": {
            "repository": "https://github.com/digitaltwin-run/twinstudio",
            "revision": revision,
            "manifest": "dsl-manifest.json",
        },
        "evaluable": True,
        "failureReason": None,
        "findings": [],
    }
    with tempfile.TemporaryDirectory(prefix="twinstudio-dsl-findings-") as temporary:
        report_path = Path(temporary) / "findings.json"
        report_path.write_text(json.dumps(findings, indent=2) + "\n")
        _run_standard(
            checker,
            [
                "gate",
                "--root",
                str(ROOT),
                "--revision",
                revision,
                "--findings",
                str(report_path),
                str(ROOT / "dsl-manifest.json"),
            ],
        )
    report = {
        "status": "passed",
        "standard": "wellmanifest.dsl/manifest/v1",
        "checker": str(checker),
        "manifest": "dsl-manifest.json",
        "change_gate": "passed",
        "findings_gate": "passed",
        "examples": examples,
        "commands": commands,
        "nl_matrix": nl_matrix,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
