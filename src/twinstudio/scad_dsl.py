"""Bezpieczny, parametryczny DSL dla artefaktów OpenSCAD.

Model nie otrzymuje prawa do generowania kodu.  Może wskazać wyłącznie jedną
istniejącą, liczbową zmienną na najwyższym poziomie pliku i nadać jej nową
wartość.  Zmiana jest związana z hashem źródła, a kandydat przechodzi parser
OpenSCAD, gdy program jest dostępny w środowisku TwinStudio.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .kicad_dsl import eda_litellm_route


class ScadDslError(ValueError):
    pass


class ScadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScadSource(ScadModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["scad"] = "scad"


class ScadVariable(ScadModel):
    target: str = Field(pattern=r"^scad:variable:[A-Za-z_][A-Za-z0-9_]*$")
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: float
    literal: str
    line: int = Field(ge=1)


class ScadDocument(ScadModel):
    schema_id: Literal["twinstudio.scad/v1"] = "twinstudio.scad/v1"
    source: ScadSource
    variables: list[ScadVariable]


class ScadSetVariableOperation(ScadModel):
    op: Literal["set_variable"]
    target: str = Field(pattern=r"^scad:variable:[A-Za-z_][A-Za-z0-9_]*$")
    value: float = Field(ge=-1_000_000, le=1_000_000)


class ScadChangeDocument(ScadModel):
    schema_id: Literal["twinstudio.scad-change/v1"] = "twinstudio.scad-change/v1"
    source: ScadSource
    prompt: str = Field(default="", max_length=30_000)
    operations: list[ScadSetVariableOperation] = Field(min_length=1, max_length=1)
    requires_approval: bool = True


# Only direct numeric assignments are editable.  Expressions, arrays, strings,
# imports and module bodies intentionally remain outside the DSL boundary.
_VARIABLE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<literal>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?P<trailer>\s*;)"
)


def _sha(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def resolve_scad_source(root: Path, relative: str) -> Path:
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        raise ScadDslError("SCAD source path must be relative")
    path = (root / relative).resolve()
    root = root.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink() or path.suffix.lower() != ".scad":
        raise ScadDslError("SCAD source is outside the configured artifact root or does not exist")
    return path


def _variables(source: str) -> list[tuple[ScadVariable, re.Match[str]]]:
    raw: list[tuple[ScadVariable, re.Match[str]]] = []
    depth = 0
    for line_number, line in enumerate(source.splitlines(keepends=True), start=1):
        # A direct parameter is allowed only outside module/control blocks.
        if depth == 0:
            for match in _VARIABLE.finditer(line):
                literal = match.group("literal")
                value = float(literal)
                if math.isfinite(value):
                    name = match.group("name")
                    raw.append((ScadVariable(
                        target=f"scad:variable:{name}", name=name, value=value,
                        literal=literal, line=line_number,
                    ), match))
        # The grammar is deliberately conservative: braces inside strings are
        # not relevant because strings are never accepted as editable lines.
        depth += line.count("{") - line.count("}")
        depth = max(depth, 0)
    counts: dict[str, int] = {}
    for variable, _match in raw:
        counts[variable.name] = counts.get(variable.name, 0) + 1
    # An overridden OpenSCAD variable is ambiguous by design, so it is not
    # exposed as an editable target.
    return [(variable, match) for variable, match in raw if counts[variable.name] == 1]


def inspect_scad(source: str, path: str) -> ScadDocument:
    return ScadDocument(
        source=ScadSource(path=path, sha256=_sha(source)),
        variables=[item for item, _match in _variables(source)],
    )


def inspect_scad_file(root: Path, relative: str) -> ScadDocument:
    path = resolve_scad_source(root, relative)
    return inspect_scad(path.read_text(encoding="utf-8"), relative)


def _format_number(value: float) -> str:
    if not math.isfinite(value):
        raise ScadDslError("SCAD variable value must be finite")
    text = format(value, ".12g")
    if text in {"-0", "-0.0"}:
        return "0"
    return text


def apply_scad_changes(source: str, document: ScadChangeDocument) -> str:
    if _sha(source) != document.source.sha256:
        raise ScadDslError("source hash changed; refresh scad2dsl before applying")
    operation = document.operations[0]
    variables = {item.target: (item, match) for item, match in _variables(source)}
    found = variables.get(operation.target)
    if found is None:
        raise ScadDslError("SCAD operation target is missing or no longer editable")
    variable, _match = found
    lines = source.splitlines(keepends=True)
    line = lines[variable.line - 1]
    match = next((item for item in _VARIABLE.finditer(line) if item.group("name") == variable.name), None)
    if match is None:  # Defensive check against line/target drift.
        raise ScadDslError("SCAD operation target is no longer a direct numeric assignment")
    start, end = match.span("literal")
    lines[variable.line - 1] = line[:start] + _format_number(operation.value) + line[end:]
    return "".join(lines)


def validate_scad(source: str) -> dict[str, Any]:
    """Run OpenSCAD without persisting geometry or exposing a host file path.

    ``TWINSTUDIO_OPENSCAD_COMMAND`` may name a local binary (the default) or a
    command prefix for an isolated CAD runtime.  The SCAD source is always sent
    over stdin and the resulting CSG is read from stdout, so a local TwinStudio
    server can safely use the Viewer container without mounting its temp files.
    """
    raw_command = os.getenv("TWINSTUDIO_OPENSCAD_COMMAND", "openscad").strip()
    try:
        command = shlex.split(raw_command)
    except ValueError as exc:
        raise ScadDslError("TWINSTUDIO_OPENSCAD_COMMAND has invalid quoting") from exc
    if not command or shutil.which(command[0]) is None:
        return {
            "status": "structurally_valid",
            "codes": ["SCAD-OPENSCAD-UNAVAILABLE"],
            "requires_openscad_verification": True,
            "openscad": "unavailable",
        }
    try:
        process = subprocess.run(
            [*command, "--export-format", "csg", "-o", "-", "-"],
            input=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "structurally_valid",
            "codes": ["SCAD-OPENSCAD-UNAVAILABLE"],
            "requires_openscad_verification": True,
            "openscad": type(exc).__name__,
        }
    valid = process.returncode == 0 and bool(process.stdout.strip())
    detail = (process.stderr or process.stdout).strip()[-1200:]
    if not valid:
        raise ScadDslError(f"OpenSCAD validation failed: {detail or process.returncode}")
    return {
        "status": "validated",
        "codes": [],
        "requires_openscad_verification": False,
        "openscad": "valid",
    }


def _local_scad_plan(prompt: str, document: ScadDocument) -> ScadChangeDocument:
    match = re.search(
        r"(?:ustaw|zmień)\s+(?:parametr\s+|wartość\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+(?:na|to)\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        prompt, re.IGNORECASE,
    )
    if match is None:
        raise ScadDslError('prompt must identify one numeric parameter, e.g. "ustaw T na 4"')
    name, raw_value = match.groups()
    target = next((item for item in document.variables if item.name.casefold() == name.casefold()), None)
    if target is None:
        raise ScadDslError(f"SCAD parameter {name!r} is not an editable top-level numeric variable")
    return ScadChangeDocument(
        source=document.source, prompt=prompt,
        operations=[ScadSetVariableOperation(op="set_variable", target=target.target, value=float(raw_value))],
    )


def nl_to_scad_dsl(prompt: str, document: ScadDocument, settings: Any) -> tuple[ScadChangeDocument, str]:
    try:
        route = eda_litellm_route(settings)
    except Exception:
        route = None
    if route is None:
        return _local_scad_plan(prompt, document), "local"
    route_kwargs, route_mode, supports_schema = route
    try:
        from litellm import completion
        schema = ScadChangeDocument.model_json_schema()
        kwargs: dict[str, Any] = {
            **route_kwargs,
            "messages": [
                {"role": "system", "content": "Return one JSON SCAD parameter change only. Select exactly one listed top-level numeric variable. Never return OpenSCAD code, expressions, imports or modules."},
                {"role": "user", "content": json.dumps({"prompt": prompt, "document": document.model_dump(mode="json"), "output_schema": schema}, ensure_ascii=False)},
            ],
        }
        if supports_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "scad_change", "strict": True, "schema": schema}}
        response = completion(**kwargs)
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        candidate = ScadChangeDocument.model_validate_json(str(content))
    except Exception as exc:
        try:
            return _local_scad_plan(prompt, document), f"local-fallback:{route_mode}:{type(exc).__name__}"
        except ScadDslError:
            raise ScadDslError("LLM response does not conform to the strict SCAD change schema") from exc
    allowed = {item.target for item in document.variables}
    if candidate.source != document.source or len(candidate.operations) != 1 or candidate.operations[0].target not in allowed:
        raise ScadDslError("LLM selected an invalid SCAD source or variable")
    return candidate, route_mode


def write_scad_candidate(root: Path, output_root: Path, document: ScadChangeDocument) -> dict[str, Any]:
    source_path = resolve_scad_source(root, document.source.path)
    candidate = apply_scad_changes(source_path.read_text(encoding="utf-8"), document)
    validation = validate_scad(candidate)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = _sha(candidate)[:12]
    relative = Path(document.source.path)
    target_dir = output_root / f"{stamp}-{digest}" / relative.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / relative.name
    target.write_text(candidate, encoding="utf-8")
    manifest = {
        "schema_id": "twinstudio.scad-result/v1",
        "source": document.source.model_dump(mode="json"),
        "candidate_sha256": _sha(candidate),
        "candidate_path": target.relative_to(output_root).as_posix(),
        "operations": [item.model_dump(mode="json") for item in document.operations],
        "validation": validation,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "change.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
