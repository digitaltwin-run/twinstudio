"""Ściśle ograniczony DSL do edycji wektorowych artefaktów SVG.

Nie serializujemy XML przez ElementTree: zmieniłoby to cały plik i zatarło
podgląd różnic. Operacje są małymi patchami tekstowymi, związanymi z hashem
źródła oraz stabilnym numerem elementu w SVG.
"""
from __future__ import annotations

import hashlib
import json
import re
from base64 import b64encode
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from .kicad_dsl import eda_litellm_route


class SvgDslError(ValueError):
    pass


class SvgModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SvgSource(SvgModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["svg"] = "svg"


class SvgElement(SvgModel):
    target: str
    tag: str
    ordinal: int = Field(ge=0)
    attributes: dict[str, str] = Field(default_factory=dict)
    text: str = ""


class SvgDocument(SvgModel):
    schema_id: Literal["twinstudio.svg/v1"] = "twinstudio.svg/v1"
    source: SvgSource
    elements: list[SvgElement]


class SvgSetTextOperation(SvgModel):
    op: Literal["set_text"]
    target: str = Field(min_length=3, max_length=160)
    value: str = Field(min_length=1, max_length=2_000)


class SvgSetAttributeOperation(SvgModel):
    op: Literal["set_attribute"]
    target: str = Field(min_length=3, max_length=160)
    attribute: Literal[
        "class", "fill", "stroke", "stroke-width", "opacity", "visibility",
        "x", "y", "x1", "x2", "y1", "y2", "width", "height", "d", "transform",
    ]
    value: str = Field(min_length=1, max_length=4_000)


SvgOperation = SvgSetTextOperation | SvgSetAttributeOperation


class SvgChangeDocument(SvgModel):
    schema_id: Literal["twinstudio.svg-change/v1"] = "twinstudio.svg-change/v1"
    source: SvgSource
    prompt: str = Field(default="", max_length=30_000)
    operations: list[SvgOperation] = Field(min_length=1, max_length=1)
    requires_approval: bool = True


class SvgFinding(SvgModel):
    code: str = Field(pattern=r"^SVG-[A-Z0-9-]+$")
    severity: Literal["info", "warning", "error"]
    target: str | None = None
    message: str
    evidence: str = ""
    suggestion: str = ""


class SvgAnalysis(SvgModel):
    schema_id: Literal["twinstudio.svg-analysis/v1"] = "twinstudio.svg-analysis/v1"
    source: SvgSource
    status: Literal["ready", "needs_review"]
    renderer: Literal["svg-structure", "svg-vision"]
    summary: dict[str, int]
    findings: list[SvgFinding] = Field(default_factory=list)
    vision: dict[str, Any] | None = None


_OPEN_TAG = re.compile(r"<(?P<tag>[A-Za-z][\w:.-]*)(?P<attrs>\s+[^<>]*?)?\s*/?>", re.DOTALL)
_ATTR = re.compile(r'''(?P<name>[\w:.-]+)\s*=\s*(?P<quote>["'])(?P<value>.*?)(?P=quote)''', re.DOTALL)
_EDITABLE = {"text", "rect", "path", "circle", "ellipse", "line", "polygon", "polyline", "g"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def resolve_svg_source(root: Path, relative: str) -> Path:
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        raise SvgDslError("SVG source path must be relative")
    path = (root / relative).resolve()
    root = root.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink() or path.suffix.lower() != ".svg":
        raise SvgDslError("SVG source is outside the configured artifact root or does not exist")
    return path


def _elements(source: str) -> list[tuple[SvgElement, re.Match[str]]]:
    try:
        ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise SvgDslError(f"invalid SVG XML: {exc}") from exc
    output: list[tuple[SvgElement, re.Match[str]]] = []
    ordinal = 0
    for match in _OPEN_TAG.finditer(source):
        tag = match.group("tag").split(":")[-1]
        if tag not in _EDITABLE:
            continue
        raw_attrs = match.group("attrs") or ""
        attributes = {item.group("name"): item.group("value") for item in _ATTR.finditer(raw_attrs)}
        text = ""
        if tag == "text" and not match.group(0).rstrip().endswith("/>"):
            close = re.search(r"</(?:[\w.-]+:)?text\s*>", source[match.end():], re.IGNORECASE)
            if close:
                text = source[match.end():match.end() + close.start()]
        target = f"svg:{tag}:{ordinal}"
        output.append((SvgElement(target=target, tag=tag, ordinal=ordinal, attributes=attributes, text=text), match))
        ordinal += 1
    return output


def inspect_svg(source: str, path: str) -> SvgDocument:
    return SvgDocument(
        source=SvgSource(path=path, sha256=_sha(source)),
        elements=[element for element, _match in _elements(source)],
    )


def inspect_svg_file(root: Path, relative: str) -> SvgDocument:
    path = resolve_svg_source(root, relative)
    return inspect_svg(path.read_text(encoding="utf-8"), relative)


def analyze_svg(source: str, path: str) -> SvgAnalysis:
    """Deterministyczna kontrola pliku, stanowiąca twardą podstawę dla wizji LLM."""
    document = inspect_svg(source, path)
    tags = Counter(item.tag for item in document.elements)
    findings: list[SvgFinding] = []
    try:
        root = ElementTree.fromstring(source)
        if "viewBox" not in root.attrib:
            findings.append(SvgFinding(
                code="SVG-VIEWBOX-001", severity="warning", message="SVG nie ma viewBox; skalowanie podglądu może być niejednoznaczne.",
                suggestion="Dodaj viewBox zgodny z obszarem rysunku.",
            ))
        if not any(node.tag.rsplit("}", 1)[-1] == "title" for node in root.iter()):
            findings.append(SvgFinding(
                code="SVG-A11Y-TITLE-001", severity="info", message="Brak tytułu SVG dla czytników i historii artefaktów.",
                suggestion="Dodaj krótki element title opisujący rysunek.",
            ))
    except ElementTree.ParseError:  # inspect_svg already gives a better error
        pass
    by_text: dict[str, list[SvgElement]] = {}
    for item in document.elements:
        if item.tag == "text" and item.text.strip():
            by_text.setdefault(item.text.strip(), []).append(item)
    for text, items in by_text.items():
        if len(items) > 1:
            findings.append(SvgFinding(
                code="SVG-TEXT-DUPLICATE-001", severity="info", target=items[0].target,
                message="Ten sam napis występuje wielokrotnie; przed zmianą wybierz właściwy element.",
                evidence=f"{text!r} × {len(items)}: {', '.join(item.target for item in items)}",
                suggestion="Wybierz pojedynczy target SVG i utwórz osobny kandydat set_text.",
            ))
    status: Literal["ready", "needs_review"] = "needs_review" if findings else "ready"
    return SvgAnalysis(
        source=document.source, status=status, renderer="svg-structure",
        summary={"elements": len(document.elements), "text": tags["text"], "paths": tags["path"], "shapes": sum(tags[key] for key in ("rect", "circle", "ellipse", "line", "polygon", "polyline"))},
        findings=findings,
    )


def _svg_image_data_url(source: str) -> str | None:
    """Optional raster for vision models; SVG source remains the authority."""
    try:
        import cairosvg
        png = cairosvg.svg2png(bytestring=source.encode("utf-8"), output_width=1600)
    except Exception:
        return None
    return "data:image/png;base64," + b64encode(png).decode("ascii")


def analyze_svg_with_llm(source: str, path: str, settings: Any, *, use_llm: bool) -> SvgAnalysis:
    analysis = analyze_svg(source, path)
    if not use_llm:
        return analysis
    try:
        route = eda_litellm_route(settings)
        if route is None:
            return analysis.model_copy(update={"vision": {"status": "unavailable", "reason": "SubLLM is not configured"}})
        route_kwargs, route_mode, supports_schema = route
        document = inspect_svg(source, path)
        image = _svg_image_data_url(source)
        schema = {"type": "object", "additionalProperties": False, "properties": {"findings": {"type": "array", "maxItems": 20, "items": SvgFinding.model_json_schema()}}, "required": ["findings"]}
        content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps({"task": "Inspect this SVG drawing. Return visual defects only. Do not propose XML or mutations; every finding must reference at most one supplied target.", "document": document.model_dump(mode="json"), "output_schema": schema}, ensure_ascii=False)}]
        if image:
            content.append({"type": "image_url", "image_url": {"url": image}})
        from litellm import completion
        kwargs: dict[str, Any] = {**route_kwargs, "messages": [{"role": "system", "content": "Return JSON only. Never invent element targets."}, {"role": "user", "content": content}]}
        if supports_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "svg_visual_review", "strict": True, "schema": schema}}
        response = completion(**kwargs)
        raw = response.choices[0].message.content
        if isinstance(raw, list):
            raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
        parsed = json.loads(str(raw))
        findings = [SvgFinding.model_validate(item) for item in parsed.get("findings", [])]
        allowed = {item.target for item in document.elements}
        findings = [item for item in findings if item.target is None or item.target in allowed]
        return analysis.model_copy(update={
            "renderer": "svg-vision", "status": "needs_review" if analysis.findings or findings else "ready",
            "findings": [*analysis.findings, *findings],
            "vision": {"status": "ok", "mode": route_mode, "image": "raster" if image else "structure_only"},
        })
    except Exception as exc:
        return analysis.model_copy(update={"vision": {"status": "unavailable", "reason": type(exc).__name__}})


def _target(source: str, target: str) -> tuple[SvgElement, re.Match[str]]:
    matches = [(element, match) for element, match in _elements(source) if element.target == target]
    if len(matches) != 1:
        raise SvgDslError("SVG operation target is missing or ambiguous")
    return matches[0]


def _quote(value: str) -> str:
    if any(char in value for char in "\x00\r\n"):
        raise SvgDslError("SVG attribute must not contain control characters")
    return json.dumps(value, ensure_ascii=False)


def apply_svg_changes(source: str, document: SvgChangeDocument) -> str:
    if _sha(source) != document.source.sha256:
        raise SvgDslError("source hash changed; refresh svg2dsl before applying")
    output = source
    for operation in document.operations:
        element, open_tag = _target(output, operation.target)
        if isinstance(operation, SvgSetTextOperation):
            if element.tag != "text" or open_tag.group(0).rstrip().endswith("/>"):
                raise SvgDslError("set_text requires a non-empty <text> element")
            close = re.search(r"</(?:[\w.-]+:)?text\s*>", output[open_tag.end():], re.IGNORECASE)
            if close is None:
                raise SvgDslError("SVG text element has no closing tag")
            start, end = open_tag.end(), open_tag.end() + close.start()
            output = output[:start] + operation.value + output[end:]
            continue
        raw_tag = open_tag.group(0)
        attribute_match = next((item for item in _ATTR.finditer(raw_tag) if item.group("name") == operation.attribute), None)
        if attribute_match:
            start = open_tag.start() + attribute_match.start("value") - 1
            end = open_tag.start() + attribute_match.end("value") + 1
            output = output[:start] + _quote(operation.value) + output[end:]
        else:
            insertion = open_tag.end() - (2 if raw_tag.rstrip().endswith("/>") else 1)
            output = output[:insertion] + f" {operation.attribute}={_quote(operation.value)}" + output[insertion:]
    # Ensure no malformed candidate is ever persisted.
    try:
        ElementTree.fromstring(output)
    except ElementTree.ParseError as exc:
        raise SvgDslError(f"SVG operation would create invalid XML: {exc}") from exc
    return output


def _local_svg_plan(prompt: str, document: SvgDocument) -> SvgChangeDocument:
    text_match = re.search(r"(?:zmień|ustaw)\s+(?:tekst|napis)\s+[\"„](.+?)[\"”]\s+(?:na|to)\s+[\"„](.+?)[\"”]", prompt, re.IGNORECASE)
    if text_match:
        before, after = text_match.groups()
        targets = [item for item in document.elements if item.tag == "text" and item.text.strip() == before]
        if len(targets) == 1:
            return SvgChangeDocument(source=document.source, prompt=prompt, operations=[SvgSetTextOperation(op="set_text", target=targets[0].target, value=after)])
    attribute_match = re.search(r"(?:ustaw|zmień)\s+(fill|stroke|opacity|class)\s+(?:elementu\s+)?(svg:[\w:-]+)\s+(?:na|to)\s+[\"']?([^\"'\s]+)", prompt, re.IGNORECASE)
    if attribute_match:
        attribute, target, value = attribute_match.groups()
        if any(item.target == target for item in document.elements):
            return SvgChangeDocument(source=document.source, prompt=prompt, operations=[SvgSetAttributeOperation(op="set_attribute", target=target, attribute=attribute, value=value)])
    raise SvgDslError('prompt must identify one SVG text exactly, e.g. zmień napis "A" na "B"')


def nl_to_svg_dsl(prompt: str, document: SvgDocument, settings: Any) -> tuple[SvgChangeDocument, str]:
    try:
        # SVG uses the same centrally configured SubLLM route as KiCad.  The
        # output schema, not a separate model alias, determines the dialect.
        route = eda_litellm_route(settings)
    except Exception:
        route = None
    if route is None:
        return _local_svg_plan(prompt, document), "local"
    route_kwargs, route_mode, supports_schema = route
    try:
        from litellm import completion
        schema = SvgChangeDocument.model_json_schema()
        kwargs: dict[str, Any] = {
            **route_kwargs,
            "messages": [
                {"role": "system", "content": "Return one JSON SVG change only. Use exactly one listed target and one allow-listed operation. Never return XML or code."},
                {"role": "user", "content": json.dumps({"prompt": prompt, "document": document.model_dump(mode="json"), "output_schema": schema}, ensure_ascii=False)},
            ],
        }
        if supports_schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "svg_change", "strict": True, "schema": schema}}
        response = completion(**kwargs)
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        candidate = SvgChangeDocument.model_validate_json(str(content))
    except Exception as exc:
        try:
            return _local_svg_plan(prompt, document), f"local-fallback:{route_mode}:{type(exc).__name__}"
        except SvgDslError:
            raise SvgDslError("LLM response does not conform to the strict SVG change schema") from exc
    if candidate.source != document.source or len(candidate.operations) != 1:
        raise SvgDslError("LLM selected an invalid SVG source or more than one operation")
    allowed = {item.target for item in document.elements}
    if candidate.operations[0].target not in allowed:
        raise SvgDslError("LLM selected an SVG element outside the supplied document")
    return candidate, route_mode


def write_svg_candidate(root: Path, output_root: Path, document: SvgChangeDocument) -> dict[str, Any]:
    source_path = resolve_svg_source(root, document.source.path)
    source = source_path.read_text(encoding="utf-8")
    candidate = apply_svg_changes(source, document)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = _sha(candidate)[:12]
    relative = Path(document.source.path)
    target_dir = output_root / f"{stamp}-{digest}" / relative.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / relative.name
    target.write_text(candidate, encoding="utf-8")
    manifest = {
        "schema_id": "twinstudio.svg-result/v1",
        "source": document.source.model_dump(mode="json"),
        "candidate_sha256": _sha(candidate),
        "candidate_path": target.relative_to(output_root).as_posix(),
        "operations": [item.model_dump(mode="json") for item in document.operations],
        "validation": {"status": "structurally_valid", "codes": [], "requires_routing": False, "svg_xml": "valid"},
        "created_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "change.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
