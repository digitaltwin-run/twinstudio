"""Conservative firmware-to-schematic GPIO audit for the TwinStudio EDA CLI."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from twinstudio.kicad_dsl import DslModel, EdaDocument, EdaSource, eda_litellm_route


class FirmwareSource(DslModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gpio: list[int]
    parse_error: str | None = None


class FirmwareAuditFinding(DslModel):
    severity: Literal["info", "warning", "error"]
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,80}$")
    message: str = Field(min_length=1, max_length=2_000)
    evidence: list[str] = Field(default_factory=list, max_length=30)


class FirmwareAuditReview(DslModel):
    schema_id: Literal["twinstudio.eda-firmware-review/v1"] = "twinstudio.eda-firmware-review/v1"
    verdict: Literal["pass", "review", "fail"]
    summary: str = Field(min_length=1, max_length=4_000)
    findings: list[FirmwareAuditFinding] = Field(default_factory=list, max_length=50)
    requires_human_review: bool = True


class FirmwareAuditReport(DslModel):
    schema_id: Literal["twinstudio.eda-firmware-audit/v1"] = "twinstudio.eda-firmware-audit/v1"
    source: EdaSource
    prompt: str
    firmware: list[FirmwareSource]
    firmware_gpio: list[int]
    schematic_gpio_labels: list[int]
    missing_from_schematic: list[int]
    unexpected_in_schematic: list[int]
    limitations: list[str]
    mode: str
    review: FirmwareAuditReview | None = None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _firmware_source(path: Path) -> FirmwareSource:
    raw = path.read_bytes()
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return FirmwareSource(path=str(path), sha256=_sha256(raw), gpio=[], parse_error=str(exc))
    gpio: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "board"
        ):
            match = re.fullmatch(r"GP(\d{1,2})", node.attr)
            if match:
                gpio.add(int(match.group(1)))
    return FirmwareSource(path=str(path), sha256=_sha256(raw), gpio=sorted(gpio))


def _schematic_gpio_labels(source: str) -> list[int]:
    # This recognizes explicit KiCad net labels such as GP1 and GPIO_1. It is
    # deliberately not a wire-graph extractor: unlabeled wires need ERC/netlist
    # evidence and must not be claimed as a verified firmware connection.
    return sorted({int(value) for value in re.findall(r"\b(?:GPIO|GP)[_-]?(\d{1,2})\b", source, re.I)})


def static_firmware_audit(
    schematic: EdaDocument,
    schematic_source: str,
    firmware_paths: list[Path],
    prompt: str,
) -> FirmwareAuditReport:
    firmware = [_firmware_source(path) for path in firmware_paths]
    firmware_gpio = sorted({gpio for item in firmware for gpio in item.gpio})
    labels = _schematic_gpio_labels(schematic_source)
    missing = sorted(set(firmware_gpio) - set(labels))
    unexpected = sorted(set(labels) - set(firmware_gpio))
    return FirmwareAuditReport(
        source=schematic.source,
        prompt=prompt,
        firmware=firmware,
        firmware_gpio=firmware_gpio,
        schematic_gpio_labels=labels,
        missing_from_schematic=missing,
        unexpected_in_schematic=unexpected,
        limitations=[
            "Porównanie opiera się na jawnych etykietach GP/GPIO w schemacie.",
            "Nie potwierdza ciągłości nieopisanych przewodów ani reguł ERC/DRC.",
            "Pliki generatorów opisują możliwości lub szablony; tylko wykryte board.GP<n> są traktowane jako użycie firmware.",
        ],
        mode="static",
    )


def _local_review(report: FirmwareAuditReport) -> FirmwareAuditReview:
    if report.missing_from_schematic or report.unexpected_in_schematic:
        verdict: Literal["pass", "review", "fail"] = "review"
        summary = "Wykryto różnice między GPIO firmware i jawnymi etykietami schematu."
    else:
        verdict = "review"
        summary = "Etykiety GPIO są zgodne, lecz należy potwierdzić połączenia przewodów przez ERC/netlistę."
    findings: list[FirmwareAuditFinding] = []
    if report.missing_from_schematic:
        findings.append(
            FirmwareAuditFinding(
                severity="warning",
                code="firmware_gpio_missing_label",
                message="GPIO użyte przez firmware nie ma jawnej etykiety w schemacie.",
                evidence=[f"GP{gpio}" for gpio in report.missing_from_schematic],
            )
        )
    if report.unexpected_in_schematic:
        findings.append(
            FirmwareAuditFinding(
                severity="info",
                code="schematic_gpio_not_in_firmware",
                message="Schemat zawiera dodatkowe jawne etykiety GPIO.",
                evidence=[f"GP{gpio}" for gpio in report.unexpected_in_schematic],
            )
        )
    return FirmwareAuditReview(
        verdict=verdict,
        summary=summary,
        findings=findings,
        requires_human_review=True,
    )


def audit_firmware(
    schematic: EdaDocument,
    schematic_source: str,
    firmware_paths: list[Path],
    prompt: str,
    settings: Any,
    *,
    review_with_llm: bool = True,
) -> FirmwareAuditReport:
    report = static_firmware_audit(schematic, schematic_source, firmware_paths, prompt)
    if not review_with_llm:
        return report.model_copy(update={"review": _local_review(report)})
    function = getattr(settings, "subllm_audit_function", "eda-firmware-audit")
    try:
        resolved = eda_litellm_route(settings, function)
    except Exception as exc:
        return report.model_copy(
            update={"mode": f"local-fallback:subllm:{type(exc).__name__}", "review": _local_review(report)}
        )
    if resolved is None:
        return report.model_copy(update={"mode": "local", "review": _local_review(report)})
    route_kwargs, route_mode, supports_response_schema = resolved
    try:
        from litellm import completion

        schema = FirmwareAuditReview.model_json_schema()
        kwargs: dict[str, Any] = {
            **route_kwargs,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Review a deterministic firmware-to-schematic GPIO audit. Return one JSON object only. "
                        "Do not claim that an unlabeled wire is connected. Treat every stated limitation as binding. "
                        "Do not propose or execute a KiCad edit."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"prompt": prompt, "static_audit": report.model_dump(mode="json"), "output_schema": schema},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        if supports_response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "firmware_audit", "strict": True, "schema": schema},
            }
        response = completion(**kwargs)
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        review = FirmwareAuditReview.model_validate_json(str(content))
    except Exception as exc:
        return report.model_copy(
            update={"mode": f"local-fallback:{route_mode}:{type(exc).__name__}", "review": _local_review(report)}
        )
    return report.model_copy(update={"mode": route_mode, "review": review})
