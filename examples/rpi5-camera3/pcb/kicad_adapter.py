from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


class KiCadUnavailable(RuntimeError):
    pass


def _cli() -> str:
    executable = shutil.which("kicad-cli")
    if not executable:
        raise KiCadUnavailable("kicad-cli is not installed or is not on PATH")
    return executable


def run(args: Iterable[str], *, cwd: Path | None = None) -> dict:
    command = [_cli(), *args]
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def export_review_artifacts(source: Path, output: Path) -> list[dict]:
    """Export/check a supplied KiCad source through explicit, reviewable CLI calls.

    The exact available subcommands depend on the installed KiCad version. Results are
    returned rather than silently treated as successful.
    """
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    suffix = source.suffix.lower()
    if suffix == ".kicad_sch":
        results.append(run(["sch", "erc", str(source), "--output", str(output / "erc.rpt")]))
        results.append(run(["sch", "export", "pdf", str(source), "--output", str(output / "schematic.pdf")]))
    elif suffix == ".kicad_pcb":
        results.append(run(["pcb", "drc", str(source), "--output", str(output / "drc.rpt")]))
        results.append(run(["pcb", "export", "gerbers", str(source), "--output", str(output / "gerbers")]))
        results.append(run(["pcb", "export", "drill", str(source), "--output", str(output / "drill")]))
    else:
        raise ValueError("Expected .kicad_sch or .kicad_pcb")
    (output / "adapter-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
