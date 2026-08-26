from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import twinstudio.cli as cli_module
from twinstudio.eda_firmware_audit import audit_firmware, static_firmware_audit
from twinstudio.kicad_dsl import inspect_file

SCH = """(kicad_sch (version 20211123) (generator eeschema)
  (global_label "GP1" (shape input) (at 10 10 0) (fields_autoplaced))
  (global_label "GPIO_11" (shape input) (at 20 10 0) (fields_autoplaced))
  (symbol (lib_id "local:R") (at 10 20 0) (unit 1)
    (uuid 11111111-1111-1111-1111-111111111111)
    (property "Reference" "R1" (id 0) (at 10 20 0))
    (property "Value" "1k" (id 1) (at 10 21 0))
    (property "Footprint" "local:R_0603" (id 2) (at 10 22 0) hide))
)\n"""


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        kicad_root=tmp_path / "sources",
        data_dir=tmp_path / "data",
        subllm_enabled=False,
        subllm_application="twinstudio",
        subllm_function="eda-nl2dsl",
        subllm_audit_function="eda-firmware-audit",
        litellm_model="",
        litellm_api_base="",
        litellm_api_key="",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "sources"
    root.mkdir()
    schematic = root / "panel.kicad_sch"
    firmware = tmp_path / "code.py"
    generator = tmp_path / "generator.py"
    schematic.write_text(SCH, encoding="utf-8")
    firmware.write_text("import board\nkeys = [board.GP1, board.GP11, board.GP12]\n", encoding="utf-8")
    generator.write_text("AVAILABLE_GPIOS = list(range(30))\n", encoding="utf-8")
    return root, schematic, firmware, generator


def test_static_firmware_audit_reports_labels_and_limits(tmp_path: Path) -> None:
    root, _schematic, firmware, generator = _fixture(tmp_path)
    document = inspect_file(root, "panel.kicad_sch")
    report = static_firmware_audit(
        document,
        SCH,
        [firmware, generator],
        "Porównaj GPIO.",
    )
    assert report.firmware_gpio == [1, 11, 12]
    assert report.schematic_gpio_labels == [1, 11]
    assert report.missing_from_schematic == [12]
    assert report.unexpected_in_schematic == []
    assert "nieopisanych przewodów" in report.limitations[1]


def test_firmware_audit_uses_glm_5_3_route(monkeypatch, tmp_path: Path) -> None:
    root, _schematic, firmware, _generator = _fixture(tmp_path)
    document = inspect_file(root, "panel.kicad_sch")
    captured: dict[str, object] = {}

    class Route:
        provider = "zai"
        model = "glm-5.3"
        transport = "openai-compatible"

        @staticmethod
        def litellm_kwargs():
            return {"model": "zai/glm-5.3", "api_key": "test", "api_base": "https://example.test"}

    review = {
        "schema_id": "twinstudio.eda-firmware-review/v1",
        "verdict": "review",
        "summary": "Wymagana weryfikacja ERC.",
        "findings": [],
        "requires_human_review": True,
    }

    def completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(review)))])

    monkeypatch.setitem(sys.modules, "subllm", SimpleNamespace(resolve=lambda *_args: Route()))
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    configured = _settings(tmp_path)
    configured.subllm_enabled = True
    report = audit_firmware(document, SCH, [firmware], "Porównaj GPIO.", configured)

    assert report.mode == "subllm:zai/glm-5.3"
    assert report.review and report.review.verdict == "review"
    assert captured["model"] == "zai/glm-5.3"
    assert "response_format" not in captured


def test_eda_cli_plan_shell_and_static_audit(monkeypatch, tmp_path: Path) -> None:
    root, _schematic, firmware, generator = _fixture(tmp_path)
    configured = _settings(tmp_path)
    monkeypatch.setattr(cli_module, "settings", configured)
    runner = CliRunner()

    plan = runner.invoke(cli_module.app, ["eda", "plan", "panel.kicad_sch", "ustaw wartość R1 na 10k", "--kicad-root", str(root)])
    assert plan.exit_code == 0, plan.output
    assert '"mode": "local"' in plan.output

    audit = runner.invoke(
        cli_module.app,
        [
            "eda", "audit-firmware", "panel.kicad_sch", "--kicad-root", str(root),
            "--firmware", str(firmware), "--firmware", str(generator), "--no-llm",
        ],
    )
    assert audit.exit_code == 0, audit.output
    assert '"missing_from_schematic": [' in audit.output

    shell = runner.invoke(
        cli_module.app,
        ["eda", "shell", "panel.kicad_sch", "--kicad-root", str(root)],
        input="ustaw wartość R1 na 10k\n:check\n:apply\n:quit\n",
    )
    assert shell.exit_code == 0, shell.output
    assert "OK: plan matches the current source" in shell.output
    assert list((configured.data_dir / "artifacts" / "kicad-edits").rglob("panel.kicad_sch"))
