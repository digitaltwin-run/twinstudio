from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KicadDslError(ValueError):
    pass


class DslModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EdaPosition(DslModel):
    x: float
    y: float
    rotation: float = 0.0


class EdaItem(DslModel):
    entity: Literal["symbol", "footprint"]
    uuid: str
    reference: str
    library_id: str
    value: str = ""
    footprint: str = ""
    layer: str | None = None
    position: EdaPosition


class EdaSource(DslModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["schematic", "pcb"]
    kicad_version: int | None = None


class EdaDocument(DslModel):
    schema_id: Literal["twinstudio.eda/v1"] = "twinstudio.eda/v1"
    source: EdaSource
    items: list[EdaItem]


class EdaTarget(DslModel):
    uuid: str | None = None
    reference: str | None = None

    @model_validator(mode="after")
    def require_identity(self) -> "EdaTarget":
        if not self.uuid and not self.reference:
            raise ValueError("target requires uuid or reference")
        return self


class SetPropertyOperation(DslModel):
    op: Literal["set_property"]
    entity: Literal["symbol"] = "symbol"
    target: EdaTarget
    property: Literal["Value", "Footprint"]
    value: str = Field(min_length=1, max_length=500)


class MoveOperation(DslModel):
    op: Literal["move"]
    # Moving a schematic symbol safely also requires reconnecting wires and
    # relocating properties. That is intentionally outside the v1 allow-list.
    entity: Literal["footprint"]
    target: EdaTarget
    x: float
    y: float
    rotation: float | None = None


EdaOperation = Annotated[SetPropertyOperation | MoveOperation, Field(discriminator="op")]


class EdaChangeDocument(DslModel):
    schema_id: Literal["twinstudio.eda-change/v1"] = "twinstudio.eda-change/v1"
    source: EdaSource
    prompt: str = Field(default="", max_length=30_000)
    operations: list[EdaOperation] = Field(min_length=1, max_length=50)
    requires_approval: bool = True


@dataclass(slots=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int


@dataclass(slots=True)
class _Node:
    start: int
    end: int
    values: list[_Token | "_Node"]


def _tokens(source: str) -> list[_Token]:
    result: list[_Token] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == ";":
            newline = source.find("\n", index)
            index = len(source) if newline < 0 else newline + 1
            continue
        if char in "()":
            result.append(_Token(char, char, index, index + 1))
            index += 1
            continue
        if char == '"':
            start = index
            index += 1
            escaped = False
            while index < len(source):
                current = source[index]
                index += 1
                if current == '"' and not escaped:
                    break
                escaped = current == "\\" and not escaped
                if current != "\\":
                    escaped = False
            else:
                raise KicadDslError("unterminated string in KiCad file")
            raw = source[start:index]
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise KicadDslError("invalid quoted string in KiCad file") from exc
            result.append(_Token("string", value, start, index))
            continue
        start = index
        while index < len(source) and not source[index].isspace() and source[index] not in "()":
            index += 1
        result.append(_Token("atom", source[start:index], start, index))
    return result


def _parse(source: str) -> _Node:
    stack: list[_Node] = []
    root: _Node | None = None
    for token in _tokens(source):
        if token.kind == "(":
            stack.append(_Node(token.start, -1, []))
        elif token.kind == ")":
            if not stack:
                raise KicadDslError("unexpected closing parenthesis")
            node = stack.pop()
            node.end = token.end
            if stack:
                stack[-1].values.append(node)
            elif root is None:
                root = node
            else:
                raise KicadDslError("multiple root expressions")
        elif not stack:
            raise KicadDslError("atom outside root expression")
        else:
            stack[-1].values.append(token)
    if stack or root is None:
        raise KicadDslError("unbalanced KiCad S-expression")
    return root


def _head(node: _Node) -> str | None:
    first = node.values[0] if node.values else None
    return first.value if isinstance(first, _Token) else None


def _child(node: _Node, name: str) -> _Node | None:
    return next((value for value in node.values if isinstance(value, _Node) and _head(value) == name), None)


def _token(node: _Node, index: int) -> _Token | None:
    atoms = [value for value in node.values if isinstance(value, _Token)]
    return atoms[index] if len(atoms) > index else None


def _text(node: _Node, index: int, default: str = "") -> str:
    item = _token(node, index)
    return item.value if item else default


def _number(node: _Node, index: int, default: float = 0.0) -> float:
    try:
        return float(_text(node, index))
    except ValueError:
        return default


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _source_version(root: _Node) -> int | None:
    version = _child(root, "version")
    try:
        return int(_text(version, 1)) if version else None
    except ValueError:
        return None


def _properties(node: _Node) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in node.values:
        if isinstance(value, _Node) and _head(value) == "property":
            result[_text(value, 1)] = _text(value, 2)
    return result


def _fp_text(node: _Node, kind: str) -> str:
    for value in node.values:
        if isinstance(value, _Node) and _head(value) == "fp_text" and _text(value, 1) == kind:
            return _text(value, 2)
    return ""


def inspect_source(source: str, path: str) -> EdaDocument:
    root = _parse(source)
    root_kind = _head(root)
    if root_kind not in {"kicad_sch", "kicad_pcb"}:
        raise KicadDslError("only .kicad_sch and .kicad_pcb S-expressions are supported")
    kind: Literal["schematic", "pcb"] = "schematic" if root_kind == "kicad_sch" else "pcb"
    items: list[EdaItem] = []
    for node in (value for value in root.values if isinstance(value, _Node)):
        if kind == "schematic" and _head(node) == "symbol" and _child(node, "lib_id"):
            props = _properties(node)
            at = _child(node, "at")
            uuid = _child(node, "uuid")
            items.append(
                EdaItem(
                    entity="symbol",
                    uuid=_text(uuid, 1),
                    reference=props.get("Reference", ""),
                    library_id=_text(_child(node, "lib_id"), 1),
                    value=props.get("Value", ""),
                    footprint=props.get("Footprint", ""),
                    position=EdaPosition(
                        x=_number(at, 1), y=_number(at, 2), rotation=_number(at, 3)
                    ),
                )
            )
        elif kind == "pcb" and _head(node) == "footprint":
            at = _child(node, "at")
            stamp = _child(node, "uuid") or _child(node, "tstamp")
            layer = _child(node, "layer")
            items.append(
                EdaItem(
                    entity="footprint",
                    uuid=_text(stamp, 1),
                    reference=_fp_text(node, "reference"),
                    library_id=_text(node, 1),
                    value=_fp_text(node, "value"),
                    layer=_text(layer, 1) or None,
                    position=EdaPosition(
                        x=_number(at, 1), y=_number(at, 2), rotation=_number(at, 3)
                    ),
                )
            )
    return EdaDocument(
        source=EdaSource(
            path=path,
            sha256=_sha256(source),
            kind=kind,
            kicad_version=_source_version(root),
        ),
        items=items,
    )


def _root_child_entities(root: _Node, entity: str) -> list[_Node]:
    result: list[_Node] = []
    for node in (value for value in root.values if isinstance(value, _Node)):
        if entity == "symbol" and _head(node) == "symbol" and _child(node, "lib_id"):
            result.append(node)
        elif entity == "footprint" and _head(node) == "footprint":
            result.append(node)
    return result


def _identity(node: _Node, entity: str) -> tuple[str, str]:
    if entity == "symbol":
        return _text(_child(node, "uuid"), 1), _properties(node).get("Reference", "")
    stamp = _child(node, "uuid") or _child(node, "tstamp")
    return _text(stamp, 1), _fp_text(node, "reference")


def _target_node(root: _Node, entity: str, target: EdaTarget) -> _Node:
    matches: list[_Node] = []
    for node in _root_child_entities(root, entity):
        uuid, reference = _identity(node, entity)
        if target.uuid and uuid != target.uuid:
            continue
        if target.reference and reference.casefold() != target.reference.casefold():
            continue
        matches.append(node)
    if len(matches) != 1:
        identity = target.uuid or target.reference
        raise KicadDslError(f"target {entity} {identity!r} matched {len(matches)} objects")
    return matches[0]


def _format_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def apply_changes(source: str, document: EdaChangeDocument) -> str:
    if _sha256(source) != document.source.sha256:
        raise KicadDslError("source hash changed; refresh sch2dsl/pcb2dsl before applying")
    parsed = inspect_source(source, document.source.path)
    if parsed.source.kind != document.source.kind:
        raise KicadDslError("DSL source kind does not match the KiCad file")
    root = _parse(source)
    replacements: list[tuple[int, int, str]] = []
    for operation in document.operations:
        node = _target_node(root, operation.entity, operation.target)
        if isinstance(operation, SetPropertyOperation):
            prop = next(
                (
                    item
                    for item in node.values
                    if isinstance(item, _Node)
                    and _head(item) == "property"
                    and _text(item, 1) == operation.property
                ),
                None,
            )
            value_token = _token(prop, 2) if prop else None
            if value_token is None:
                raise KicadDslError(f"property {operation.property!r} is missing")
            replacements.append((value_token.start, value_token.end, json.dumps(operation.value)))
        elif isinstance(operation, MoveOperation):
            at = _child(node, "at")
            if at is None:
                raise KicadDslError("target has no position")
            current_rotation = _number(at, 3)
            rotation = current_rotation if operation.rotation is None else operation.rotation
            replacements.append(
                (
                    at.start,
                    at.end,
                    f"(at {_format_number(operation.x)} {_format_number(operation.y)} "
                    f"{_format_number(rotation)})",
                )
            )
    spans = sorted(replacements, reverse=True)
    for index, (start, end, replacement) in enumerate(spans):
        if index and end > spans[index - 1][0]:
            raise KicadDslError("overlapping operations are not allowed")
        source = source[:start] + replacement + source[end:]
    return source


def resolve_source(root: Path, relative: str) -> Path:
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        raise KicadDslError("source path must be relative to the configured KiCad root")
    path = (root / relative).resolve()
    root = root.resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise KicadDslError("source is outside the configured KiCad root or does not exist")
    if path.suffix.lower() not in {".kicad_sch", ".kicad_pcb"}:
        raise KicadDslError("source must be .kicad_sch or .kicad_pcb")
    return path


def inspect_file(root: Path, relative: str) -> EdaDocument:
    path = resolve_source(root, relative)
    return inspect_source(path.read_text(encoding="utf-8"), relative)


def write_candidate(root: Path, output_root: Path, document: EdaChangeDocument) -> dict[str, Any]:
    path = resolve_source(root, document.source.path)
    original = path.read_text(encoding="utf-8")
    candidate = apply_changes(original, document)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = _sha256(candidate)[:12]
    relative = Path(document.source.path)
    target_dir = output_root / f"{stamp}-{digest}" / relative.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / relative.name
    target.write_text(candidate, encoding="utf-8")
    for sibling_suffix in (".kicad_pro", ".kicad_pcb", ".kicad_sch"):
        sibling = path.with_suffix(sibling_suffix)
        if sibling != path and sibling.is_file():
            shutil.copy2(sibling, target.with_suffix(sibling_suffix))
    manifest = {
        "schema_id": "twinstudio.eda-result/v1",
        "source": document.source.model_dump(mode="json"),
        "candidate_sha256": _sha256(candidate),
        "candidate_path": target.relative_to(output_root).as_posix(),
        "operations": [item.model_dump(mode="json") for item in document.operations],
        "created_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "change.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def local_nl_to_dsl(prompt: str, document: EdaDocument) -> EdaChangeDocument:
    lowered = prompt.casefold()
    reference_match = re.search(r"\b([a-z]{1,4}\d{1,6})\b", prompt, re.IGNORECASE)
    if not reference_match:
        raise KicadDslError("prompt must identify a component reference, for example R1 or SW3")
    reference = reference_match.group(1).upper()
    item = next((candidate for candidate in document.items if candidate.reference.upper() == reference), None)
    if item is None:
        raise KicadDslError(f"component {reference} does not exist in the selected document")
    target = EdaTarget(uuid=item.uuid, reference=item.reference)
    operations: list[EdaOperation] = []
    value_match = re.search(
        r"(?:warto(?:ść|sc)|value).*?\b(?:na|to|=)\s*[\"']?([^\s,;\"']+)",
        prompt,
        re.IGNORECASE,
    )
    footprint_match = re.search(
        r"(?:footprint|obudow(?:ę|e|a)).*?\b(?:na|to|=)\s*[\"']?([^\s,;\"']+)",
        prompt,
        re.IGNORECASE,
    )
    move_match = re.search(
        r"(?:przesuń|przesun|move).*?\b(?:x\s*[=:]?\s*)?(-?\d+(?:[.,]\d+)?)"
        r"\s*(?:mm)?\s*[,;/ ]+\s*(?:y\s*[=:]?\s*)?(-?\d+(?:[.,]\d+)?)",
        lowered,
    )
    if value_match and item.entity == "symbol":
        operations.append(
            SetPropertyOperation(
                op="set_property", target=target, property="Value", value=value_match.group(1).rstrip(".")
            )
        )
    if footprint_match and item.entity == "symbol":
        operations.append(
            SetPropertyOperation(
                op="set_property", target=target, property="Footprint", value=footprint_match.group(1)
            )
        )
    if move_match and item.entity == "footprint":
        operations.append(
            MoveOperation(
                op="move",
                entity=item.entity,
                target=target,
                x=float(move_match.group(1).replace(",", ".")),
                y=float(move_match.group(2).replace(",", ".")),
                rotation=None,
            )
        )
    if not operations:
        raise KicadDslError(
            "unsupported request; use 'ustaw wartość R1 na 10k', "
            "'ustaw footprint R1 na Device:R_0603' or 'przesuń SW1 do x=120 y=75'"
        )
    return EdaChangeDocument(source=document.source, prompt=prompt, operations=operations)


def eda_llm_status(settings: Any) -> dict[str, Any]:
    if not getattr(settings, "subllm_enabled", False):
        return {
            "enabled": False,
            "mode": "litellm" if settings.litellm_model else "local",
        }
    try:
        from subllm import resolve

        route = resolve(settings.subllm_application, settings.subllm_function)
        if route.transport != "openai-compatible":
            raise KicadDslError(f"unsupported SubLLM transport: {route.transport}")
        return {
            "enabled": True,
            "available": True,
            "application": route.application,
            "function": route.function,
            "provider": route.provider,
            "model": route.model,
            "transport": route.transport,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "available": False,
            "application": settings.subllm_application,
            "function": settings.subllm_function,
            "error_type": type(exc).__name__,
        }


def eda_litellm_route(
    settings: Any, function: str | None = None
) -> tuple[dict[str, Any], str, bool] | None:
    if getattr(settings, "subllm_enabled", False):
        from subllm import resolve

        route = resolve(settings.subllm_application, function or settings.subllm_function)
        if route.transport != "openai-compatible":
            raise KicadDslError(f"unsupported SubLLM transport: {route.transport}")
        return (
            route.litellm_kwargs(),
            f"subllm:{route.provider}/{route.model}",
            route.provider != "zai",
        )
    if settings.litellm_model:
        kwargs: dict[str, Any] = {"model": settings.litellm_model}
        if settings.litellm_api_base:
            kwargs["api_base"] = settings.litellm_api_base
        if settings.litellm_api_key:
            kwargs["api_key"] = settings.litellm_api_key
        return kwargs, f"litellm:{settings.litellm_model}", True
    return None


def nl_to_dsl(prompt: str, document: EdaDocument, settings: Any) -> tuple[EdaChangeDocument, str]:
    try:
        resolved = eda_litellm_route(settings)
    except Exception as exc:
        return local_nl_to_dsl(prompt, document), f"local-fallback:subllm:{type(exc).__name__}"
    if resolved is None:
        return local_nl_to_dsl(prompt, document), "local"
    route_kwargs, route_mode, supports_response_schema = resolved
    try:
        from litellm import completion

        schema = EdaChangeDocument.model_json_schema()
        system = (
            "Compile the request to the supplied strict EDA change DSL. Return one JSON object only. "
            "Use only listed component UUID/reference pairs and allow-listed operations. "
            "Never emit code, never add connectivity, and never change unselected components. "
            "Copy source identity exactly from the input."
        )
        kwargs: dict[str, Any] = {
            **route_kwargs,
            "messages": [
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "prompt": prompt,
                            "document": document.model_dump(mode="json"),
                            "output_schema": schema,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        if supports_response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "eda_change", "strict": True, "schema": schema},
            }
        response = completion(**kwargs)
    except Exception as exc:
        candidate = local_nl_to_dsl(prompt, document)
        return candidate, f"local-fallback:{route_mode}:{type(exc).__name__}"
    content = response.choices[0].message.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    try:
        candidate = EdaChangeDocument.model_validate_json(str(content))
    except Exception as exc:
        raise KicadDslError("LLM response does not conform to the strict EDA change schema") from exc
    if candidate.source != document.source:
        raise KicadDslError("LLM changed the immutable source identity")
    valid = {(item.uuid, item.reference, item.entity) for item in document.items}
    for operation in candidate.operations:
        if (operation.target.uuid, operation.target.reference, operation.entity) not in valid:
            raise KicadDslError("LLM selected a component outside the supplied document")
    return candidate, route_mode
