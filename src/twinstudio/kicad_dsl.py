from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .kicad_copper import Bounds, Box, Capsule, Obstacle, RoutingError, Track, route_net, track_is_clear


class KicadDslError(ValueError):
    """Błąd walidacji granicy prompt → bezpieczny DSL EDA.

    Kod jest częścią publicznego kontraktu obserwowalności.  Tekst komunikatu
    może być pokazany użytkownikowi, a kod pozostaje stabilny dla Viewer,
    wellmanifest/logs i klientów MCP/A2A.
    """

    def __init__(self, message: str, *, code: str = "EDA-DSL-VALIDATION-001") -> None:
        super().__init__(message)
        self.code = code


class DslModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EdaPosition(DslModel):
    x: float
    y: float
    rotation: float = 0.0


class EdaPad(DslModel):
    number: str
    uuid: str = ""
    net: str = ""
    net_code: int = Field(default=0, ge=0)
    # Offset within the footprint; the connectivity planner needs it to keep
    # a repinned connector's net order aligned with the copper already routed.
    x: float = 0.0
    y: float = 0.0


class EdaNet(DslModel):
    code: int = Field(ge=0)
    name: str


class EdaItem(DslModel):
    entity: Literal["symbol", "footprint"]
    uuid: str
    reference: str
    library_id: str
    value: str = ""
    footprint: str = ""
    layer: str | None = None
    position: EdaPosition
    pads: list[EdaPad] = Field(default_factory=list)


class EdaSource(DslModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["schematic", "pcb"]
    kicad_version: int | None = None


class EdaDocument(DslModel):
    schema_id: Literal["twinstudio.eda/v1"] = "twinstudio.eda/v1"
    source: EdaSource
    items: list[EdaItem]
    nets: list[EdaNet] = Field(default_factory=list)


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


class AssignPadNetOperation(DslModel):
    op: Literal["assign_pad_net"]
    entity: Literal["footprint"] = "footprint"
    target: EdaTarget
    pad: str = Field(min_length=1, max_length=100)
    net: str = Field(min_length=1, max_length=200)
    create_if_missing: bool = False


EdaOperation = Annotated[
    SetPropertyOperation | MoveOperation | AssignPadNetOperation, Field(discriminator="op")
]


class EdaChangeDocument(DslModel):
    schema_id: Literal["twinstudio.eda-change/v1"] = "twinstudio.eda-change/v1"
    source: EdaSource
    prompt: str = Field(default="", max_length=30_000)
    operations: list[EdaOperation] = Field(min_length=1, max_length=50)
    requires_approval: bool = True


def schematic_state(
    document: EdaDocument, paired_board: EdaDocument | None = None
) -> dict[str, Any]:
    """Return bounded, deterministic repair guidance for a KiCad schematic.

    This is intentionally an inventory and consistency check, not a replacement
    for KiCad ERC.  The current v1 parser does not infer a wire/net graph from
    a schematic, so that limitation is always stated explicitly.
    """
    if document.source.kind != "schematic":
        raise KicadDslError("schematic state requires a .kicad_sch document")
    references = [item.reference.strip() for item in document.items]
    counts = Counter(reference.casefold() for reference in references if reference)
    duplicate_references = sorted(
        reference for reference, count in counts.items() if count > 1
    )
    missing_references = [item.uuid for item in document.items if not item.reference.strip()]
    missing_footprints = sorted(
        item.reference for item in document.items if not item.footprint.strip()
    )
    codes: list[str] = []
    findings: list[dict[str, Any]] = []

    def finding(code: str, severity: str, message: str, remediation: str, **details: Any) -> None:
        codes.append(code)
        findings.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
                "remediation": remediation,
                "details": details,
            }
        )

    if not document.items:
        finding(
            "EDA-SCH-EMPTY-001",
            "ERROR",
            "Schemat nie zawiera umieszczonych symboli.",
            "Otwórz plik w KiCad i dodaj lub przywróć symbole przed planowaniem zmian.",
        )
    if missing_references or duplicate_references:
        finding(
            "EDA-SCH-REFERENCE-001",
            "ERROR",
            "Oznaczenia elementów są niepełne albo niejednoznaczne.",
            "Uzupełnij i ponownie zaanotuj symbole w KiCad; każde oznaczenie musi być unikalne.",
            missing_reference_symbol_uuids=missing_references,
            duplicate_references=duplicate_references,
        )
    if missing_footprints:
        finding(
            "EDA-SCH-REFERENCE-001",
            "WARNING",
            "Część symboli nie wskazuje footprintu, więc synchronizacja z PCB nie jest pełna.",
            "Przypisz footprinty w KiCad i zaktualizuj PCB ze schematu.",
            references=missing_footprints,
        )

    pcb_only_references: list[str] = []
    schematic_only_references: list[str] = []
    if paired_board is not None:
        schematic_refs = {reference for reference in references if reference}
        board_refs = {item.reference.strip() for item in paired_board.items if item.reference.strip()}
        pcb_only_references = sorted(board_refs - schematic_refs)
        schematic_only_references = sorted(schematic_refs - board_refs)
        if pcb_only_references or schematic_only_references:
            finding(
                "EDA-SCH-PCB-SYNC-001",
                "WARNING",
                "Schemat i sąsiednia płytka PCB nie mają tego samego zestawu oznaczeń.",
                "Zsynchronizuj PCB ze schematu i sprawdź, czy elementy celowo nie są DNP.",
                pcb_only_references=pcb_only_references,
                schematic_only_references=schematic_only_references,
            )

    finding(
        "EDA-SCH-NETGRAPH-001",
        "WARNING",
        "Adapter v1 nie wyprowadza grafu przewodów i sieci ze schematu.",
        "Przed zmianą połączeń uruchom ERC w KiCad i użyj pełnego eksportu netlisty.",
    )
    blocking = any(item["severity"] == "ERROR" for item in findings)
    return {
        "schema_id": "twinstudio.eda-schematic-state/v1",
        "status": "blocked" if blocking else "requires_follow_up" if codes else "ready",
        "source": document.source.model_dump(mode="json"),
        "summary": {
            "placed_symbols": len(document.items),
            "symbols_with_footprint": len(document.items) - len(missing_footprints),
            "paired_pcb_found": paired_board is not None,
            "pcb_only_references": pcb_only_references,
            "schematic_only_references": schematic_only_references,
        },
        "codes": list(dict.fromkeys(codes)),
        "findings": findings,
    }


_PCB_DRC_RULES: dict[str, tuple[str, str, str, str]] = {
    "drc_unavailable": ("EDA-PCB-DRC-001", "ERROR", "Nie uzyskano wiarygodnego raportu DRC z KiCad.", "Napraw środowisko KiCad/DRC i uruchom analizę ponownie przed utworzeniem kandydata."),
    "clearance": ("EDA-PCB-CLEARANCE-001", "ERROR", "Ścieżka lub pad różnych sieci nie zachowuje wymaganej przerwy izolacyjnej.", "Nie zmieniaj automatycznie netów. Przeprowadź ścieżkę ponownie, zachowaj regułę clearance i uruchom DRC."),
    "solder_mask_bridge": ("EDA-PCB-MASK-BRIDGE-001", "ERROR", "Otwory w masce lutowniczej różnych sieci łączą się.", "Zwiększ odstęp ścieżki od pada albo ustaw świadomie regułę maski; po zmianie uruchom DRC."),
    "unconnected_items": ("EDA-PCB-UNCONNECTED-001", "ERROR", "KiCad wykrył niepołączone elementy tej samej sieci.", "Porównaj PCB z netlistą SCH, poprowadź brakujące połączenia i zweryfikuj wynik przez DRC."),
    "via_dangling": ("EDA-PCB-VIA-001", "WARNING", "Przelotka nie ma potwierdzonego połączenia na obu warstwach.", "Połącz przelotkę z miedzią na wymaganych warstwach albo usuń ją, jeśli nie jest potrzebna."),
    "silk_over_copper": ("EDA-PCB-SILK-001", "WARNING", "Opis na warstwie silk nachodzi na obszar miedzi lub maski.", "Przesuń lub skróć opis silk poza pady i otwory maski."),
    "silk_edge_clearance": ("EDA-PCB-SILK-EDGE-001", "WARNING", "Opis silk jest zbyt blisko krawędzi płytki.", "Przesuń opis do środka obrysu Edge.Cuts zgodnie z wymaganiem produkcyjnym."),
    "trace_under_part": ("EDA-PCB-TRACE-UNDER-PART-001", "ERROR", "Obca ścieżka przechodzi tranzytem pod obudową elementu wrażliwego na zwarcie.", "Poprowadź ścieżkę dookoła elementu albo przenieś sygnał na wyprowadzenie po tej samej stronie; miedź pod kopułką przycisku zwiera się przy montażu."),
    "lib_footprint_issues": ("EDA-PCB-FOOTPRINT-LIB-001", "WARNING", "Projekt odwołuje się do footprintów z biblioteki niedostępnej w bieżącej konfiguracji.", "Dodaj bibliotekę do tabeli footprintów albo zapisz footprinty lokalnie w projekcie."),
}


def pcb_state(
    document: EdaDocument,
    drc: dict[str, Any],
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain KiCad DRC data and return a non-executable, approval-required repair draft."""
    if document.source.kind != "pcb":
        raise KicadDslError("pcb state requires a .kicad_pcb document")
    categories_raw = drc.get("categories")
    categories = categories_raw if isinstance(categories_raw, dict) else {}
    details_raw = drc.get("details")
    details = details_raw if isinstance(details_raw, dict) else {}
    violations = drc.get("violations", 0)
    unconnected = drc.get("unconnected", 0)
    violations = violations if isinstance(violations, int) else 0
    unconnected = unconnected if isinstance(unconnected, int) else 0
    findings: list[dict[str, Any]] = []
    codes: list[str] = []

    def finding(category: str, count: int) -> None:
        code, severity, message, remediation = _PCB_DRC_RULES.get(
            category,
            ("EDA-PCB-DRC-001", "WARNING", "KiCad zgłosił dodatkową kategorię DRC wymagającą przeglądu.", "Otwórz pełny raport DRC w KiCad, ustal regułę oraz popraw element przed akceptacją kandydata."),
        )
        detail = details.get(category)
        samples = detail.get("samples", []) if isinstance(detail, dict) else []
        codes.append(code)
        findings.append({"code": code, "severity": severity, "category": category, "count": count, "message": message, "remediation": remediation, "samples": samples[:3] if isinstance(samples, list) else []})

    for category, count in sorted(categories.items()):
        if isinstance(category, str) and isinstance(count, int) and count > 0:
            finding(category, count)
    if unconnected and "unconnected_items" not in categories:
        finding("unconnected_items", unconnected)
    # Kontrola geometryczna liczona po stronie Viewera: DRC sprawdza odstępy
    # i łączność, ale nigdy nie pyta, pod czym biegnie ścieżka.
    under = (geometry or {}).get("traces_under_parts") or []
    if under:
        grouped: dict[str, set[str]] = {}
        for item in under:
            grouped.setdefault(str(item.get("reference", "?")), set()).add(str(item.get("net", "?")))
        finding("trace_under_part", len(under))
        findings[-1]["samples"] = [
            f"{reference}: {', '.join(sorted(nets))}" for reference, nets in sorted(grouped.items())
        ]
    blocking = any(item["severity"] == "ERROR" for item in findings)
    repair_steps = [f"{item['code']}: {item['remediation']}" for item in findings if item["severity"] == "ERROR"]
    if not repair_steps:
        repair_steps.append("Przejrzyj ostrzeżenia DRC i uruchom DRC ponownie przed wydaniem płytki.")
    return {
        "schema_id": "twinstudio.eda-pcb-state/v1",
        "status": "blocked" if blocking else "requires_follow_up" if findings else "ready",
        "source": document.source.model_dump(mode="json"),
        "summary": {"footprints": len(document.items), "pads": sum(len(item.pads) for item in document.items), "nets": len(document.nets), "drc_violations": violations, "unconnected_pads": unconnected},
        "codes": list(dict.fromkeys(codes)),
        "findings": findings,
        "draft": {
            "schema_id": "twinstudio.eda-repair-draft/v1",
            "status": "draft",
            "requires_approval": True,
            "requires_manual_routing": blocking,
            "message": (
                "To jest plan diagnostyczny, niezmieniający PCB. Błędy elektryczne wymagają "
                "ręcznego routingu w KiCad: DSL v1 nie tworzy ścieżek ani stref miedzi. "
                "Dopiero poprawiona kopia PCB może być kandydatem do porównania, akceptacji lub odrzucenia."
                if blocking
                else "To jest plan diagnostyczny, niezmieniający PCB. Dopiero wygenerowany kandydat może być porównany, zaakceptowany albo odrzucony."
            ),
            "repair_steps": repair_steps,
            "prompt": "Przygotuj wyłącznie kandydat naprawy PCB: " + " ".join(repair_steps),
        },
    }


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


def _pcb_pad(node: _Node) -> EdaPad:
    stamp = _child(node, "uuid") or _child(node, "tstamp")
    net = _child(node, "net")
    at = _child(node, "at")
    return EdaPad(
        number=_text(node, 1),
        uuid=_text(stamp, 1) if stamp else "",
        net=_text(net, 2) if net else "",
        net_code=int(_text(net, 1, "0") or "0") if net else 0,
        x=_number(at, 1) if at else 0.0,
        y=_number(at, 2) if at else 0.0,
    )


def inspect_source(source: str, path: str) -> EdaDocument:
    root = _parse(source)
    root_kind = _head(root)
    if root_kind not in {"kicad_sch", "kicad_pcb"}:
        raise KicadDslError("only .kicad_sch and .kicad_pcb S-expressions are supported")
    kind: Literal["schematic", "pcb"] = "schematic" if root_kind == "kicad_sch" else "pcb"
    nets = [
        EdaNet(code=int(_text(node, 1)), name=_text(node, 2))
        for node in (value for value in root.values if isinstance(value, _Node))
        if kind == "pcb" and _head(node) == "net" and _text(node, 1).isdigit()
    ]
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
                    pads=[
                        _pcb_pad(pad)
                        for pad in (value for value in node.values if isinstance(value, _Node))
                        if _head(pad) == "pad"
                    ],
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
        nets=nets,
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


# KiCad's default netclass clearance; the router adds a margin on top so a
# candidate never lands exactly on the limit that DRC then rounds against us.
_COPPER_CLEARANCE = 0.2
_COPPER_MARGIN = 0.05
_DEFAULT_TRACK_WIDTH = 0.25
_POINT_TOLERANCE = 1e-4
_SLIDE_LIMIT = 16


@dataclass(slots=True)
class _PadSite:
    node: _Node
    number: str
    reference: str
    x: float
    y: float
    half_x: float
    half_y: float
    layers: tuple[str, ...]
    footprint_index: int
    net_before: int
    net_after: int


@dataclass(slots=True)
class _SegmentSite:
    node: _Node | None
    layer: str
    net: int
    width: float
    x0: float
    y0: float
    x1: float
    y1: float
    moved: bool = False


def _rotate_offset(x: float, y: float, degrees: float) -> tuple[float, float]:
    """KiCad rotates footprint children counter-clockwise on a y-down canvas."""
    if not degrees:
        return x, y
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    return x * cos + y * sin, -x * sin + y * cos


def _node_layers(node: _Node) -> tuple[str, ...]:
    layers = _child(node, "layers")
    if layers is not None:
        return tuple(
            value.value for value in layers.values[1:] if isinstance(value, _Token)
        )
    single = _child(node, "layer")
    return (_text(single, 1),) if single is not None else ()


def _copper_layers(layers: Iterable[str]) -> set[str]:
    return {layer for layer in layers if layer.endswith(".Cu")}


def _same_point(ax: float, ay: float, bx: float, by: float) -> bool:
    return abs(ax - bx) <= _POINT_TOLERANCE and abs(ay - by) <= _POINT_TOLERANCE


def _pad_sites(root: _Node) -> list[_PadSite]:
    sites: list[_PadSite] = []
    for index, footprint in enumerate(_root_child_entities(root, "footprint")):
        at = _child(footprint, "at")
        origin_x, origin_y = (_number(at, 1), _number(at, 2)) if at else (0.0, 0.0)
        rotation = _number(at, 3) if at else 0.0
        reference = _fp_text(footprint, "reference")
        for pad in (
            value for value in footprint.values
            if isinstance(value, _Node) and _head(value) == "pad"
        ):
            pad_at = _child(pad, "at")
            local_x, local_y = (_number(pad_at, 1), _number(pad_at, 2)) if pad_at else (0.0, 0.0)
            offset_x, offset_y = _rotate_offset(local_x, local_y, rotation)
            size = _child(pad, "size")
            width = _number(size, 1) if size else 0.0
            height = _number(size, 2) if size else 0.0
            spin = math.radians(rotation + (_number(pad_at, 3) if pad_at else 0.0))
            net = _child(pad, "net")
            code = int(_text(net, 1, "0") or "0") if net else 0
            sites.append(
                _PadSite(
                    node=pad,
                    number=_text(pad, 1),
                    reference=reference,
                    x=origin_x + offset_x,
                    y=origin_y + offset_y,
                    # Bounding box of the rotated pad: never smaller than the pad.
                    half_x=(abs(width * math.cos(spin)) + abs(height * math.sin(spin))) / 2.0,
                    half_y=(abs(width * math.sin(spin)) + abs(height * math.cos(spin))) / 2.0,
                    layers=_node_layers(pad),
                    footprint_index=index,
                    net_before=code,
                    net_after=code,
                )
            )
    return sites


def _segment_sites(root: _Node) -> list[_SegmentSite]:
    sites: list[_SegmentSite] = []
    for node in (value for value in root.values if isinstance(value, _Node)):
        if _head(node) != "segment":
            continue
        start, end = _child(node, "start"), _child(node, "end")
        layer, net, width = _child(node, "layer"), _child(node, "net"), _child(node, "width")
        if start is None or end is None or layer is None:
            continue
        sites.append(
            _SegmentSite(
                node=node,
                layer=_text(layer, 1),
                net=int(_text(net, 1, "0") or "0") if net else 0,
                width=_number(width, 1, _DEFAULT_TRACK_WIDTH) if width else _DEFAULT_TRACK_WIDTH,
                x0=_number(start, 1),
                y0=_number(start, 2),
                x1=_number(end, 1),
                y1=_number(end, 2),
            )
        )
    return sites


def _via_obstacles(root: _Node, layer: str) -> list[Obstacle]:
    obstacles: list[Obstacle] = []
    for node in (value for value in root.values if isinstance(value, _Node)):
        if _head(node) != "via" or layer not in _node_layers(node):
            continue
        at, size, net = _child(node, "at"), _child(node, "size"), _child(node, "net")
        if at is None:
            continue
        x, y = _number(at, 1), _number(at, 2)
        radius = (_number(size, 1, 0.8) if size else 0.8) / 2.0
        obstacles.append(
            Capsule(
                net=int(_text(net, 1, "0") or "0") if net else 0,
                ax=x, ay=y, bx=x, by=y, radius=radius,
            )
        )
    return obstacles


def _board_bounds(root: _Node) -> Bounds:
    xs: list[float] = []
    ys: list[float] = []
    for node in (value for value in root.values if isinstance(value, _Node)):
        if _head(node) not in {"gr_line", "gr_rect"} or "Edge.Cuts" not in _node_layers(node):
            continue
        for corner in ("start", "end"):
            point = _child(node, corner)
            if point is not None:
                xs.append(_number(point, 1))
                ys.append(_number(point, 2))
    if not xs or not ys:
        raise KicadDslError("PCB has no Edge.Cuts outline; cannot bound the router")
    return Bounds(x0=min(xs), y0=min(ys), x1=max(xs), y1=max(ys))


def _track_width(segments: list[_SegmentSite], layer: str) -> float:
    widths = Counter(item.width for item in segments if item.layer == layer)
    return widths.most_common(1)[0][0] if widths else _DEFAULT_TRACK_WIDTH


def _obstacles(
    root: _Node, sites: list[_PadSite], segments: list[_SegmentSite], layer: str
) -> list[Obstacle]:
    obstacles: list[Obstacle] = _via_obstacles(root, layer)
    obstacles += [
        Capsule(net=item.net, ax=item.x0, ay=item.y0, bx=item.x1, by=item.y1,
                radius=item.width / 2.0)
        for item in segments
        if item.layer == layer
    ]
    obstacles += [
        Box(net=site.net_after, x0=site.x - site.half_x, y0=site.y - site.half_y,
            x1=site.x + site.half_x, y1=site.y + site.half_y)
        for site in sites
        if layer in site.layers
    ]
    return obstacles


def _slide_stub(
    site: _PadSite, home: _PadSite, segments: list[_SegmentSite], layer: str
) -> int:
    """Przesuwa kikut ścieżki z opuszczonego pada na jego nowy pad.

    Sam koniec ścieżki przeniósłby ją na skos; dlatego wraz z nim jedzie
    każdy sąsiedni wierzchołek, dla którego przesunięcie złamałoby oś
    odcinka. Bieg zatrzymuje się na pierwszym odcinku równoległym do
    przesunięcia, więc długi feeder zostaje na miejscu.
    """
    delta_x, delta_y = home.x - site.x, home.y - site.y
    vertices: list[tuple[float, float]] = [(site.x, site.y)]
    candidates = [item for item in segments if item.net == site.net_before and item.layer == layer]
    changed = True
    while changed:
        changed = False
        for item in candidates:
            head = any(_same_point(item.x0, item.y0, x, y) for x, y in vertices)
            tail = any(_same_point(item.x1, item.y1, x, y) for x, y in vertices)
            if head == tail:
                continue
            horizontal = abs(item.y0 - item.y1) <= _POINT_TOLERANCE
            vertical = abs(item.x0 - item.x1) <= _POINT_TOLERANCE
            parallel = (
                (horizontal and abs(delta_y) <= _POINT_TOLERANCE)
                or (vertical and abs(delta_x) <= _POINT_TOLERANCE)
            )
            if parallel or not (horizontal or vertical):
                continue
            far = (item.x1, item.y1) if head else (item.x0, item.y0)
            if any(_same_point(far[0], far[1], x, y) for x, y in vertices):
                continue
            if len(vertices) >= _SLIDE_LIMIT:
                raise KicadDslError(
                    f"repinning {site.reference}.{site.number} would drag more than "
                    f"{_SLIDE_LIMIT} track vertices; route this net manually"
                )
            vertices.append(far)
            changed = True
    touched = 0
    for item in candidates:
        for attribute_x, attribute_y in (("x0", "y0"), ("x1", "y1")):
            x, y = getattr(item, attribute_x), getattr(item, attribute_y)
            if any(_same_point(x, y, vx, vy) for vx, vy in vertices):
                setattr(item, attribute_x, x + delta_x)
                setattr(item, attribute_y, y + delta_y)
                item.moved = True
                touched += 1
    return touched


def _new_track_text(track: Track, net: int, layer: str, width: float) -> str:
    identity = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"twinstudio:track:{net}:{layer}:{track.x0},{track.y0},{track.x1},{track.y1}",
    )
    return (
        f"\n  (segment (start {_format_number(track.x0)} {_format_number(track.y0)})"
        f" (end {_format_number(track.x1)} {_format_number(track.y1)})"
        f" (width {_format_number(width)}) (layer {json.dumps(layer)})"
        f" (net {net}) (tstamp {identity}))"
    )


def _copper_repair(
    root: _Node,
    pad_targets: list[tuple[_Node, int]],
    created_nets: dict[int, str],
    net_names: dict[int, str],
) -> tuple[list[tuple[int, int, str]], dict[str, Any]]:
    """Doprowadza miedź do zgodności z nowym przypisaniem netów na padach."""
    sites = _pad_sites(root)
    by_node = {id(site.node): site for site in sites}
    for node, code in pad_targets:
        site = by_node.get(id(node))
        if site is not None:
            site.net_after = code
    segments = _segment_sites(root)
    retargeted: list[dict[str, Any]] = []

    for site in sites:
        if site.net_after == site.net_before or not site.net_before:
            continue
        homes = [
            other for other in sites
            if other.footprint_index == site.footprint_index
            and other.net_after == site.net_before
            and other.net_before != site.net_before
        ]
        if len(homes) != 1:
            continue
        home = homes[0]
        for layer in _copper_layers(site.layers) & _copper_layers(home.layers):
            stubs = [
                item for item in segments
                if item.net == site.net_before and item.layer == layer
                and (_same_point(item.x0, item.y0, site.x, site.y)
                     or _same_point(item.x1, item.y1, site.x, site.y))
            ]
            if not stubs:
                continue
            touched = _slide_stub(site, home, segments, layer)
            retargeted.append({
                "net": net_names.get(site.net_before, str(site.net_before)),
                "from_pad": f"{site.reference}.{site.number}",
                "to_pad": f"{home.reference}.{home.number}",
                "layer": layer,
                "vertices": touched,
            })

    replacements: list[tuple[int, int, str]] = []
    for item in segments:
        if not item.moved:
            continue
        start, end = _child(item.node, "start"), _child(item.node, "end")
        replacements.append((start.start, start.end,
                             f"(start {_format_number(item.x0)} {_format_number(item.y0)})"))
        replacements.append((end.start, end.end,
                             f"(end {_format_number(item.x1)} {_format_number(item.y1)})"))

    routed: list[dict[str, Any]] = []
    insertion = ""
    bounds: Bounds | None = None
    for code, name in sorted(created_nets.items()):
        terminals = [site for site in sites if site.net_after == code]
        if len(terminals) < 2:
            continue
        layers = set.intersection(*(_copper_layers(site.layers) for site in terminals))
        if len(layers) != 1:
            raise KicadDslError(
                f"net {name!r} spans {len(layers)} shared copper layers; "
                "a via plan is outside the deterministic router"
            )
        layer = layers.pop()
        if bounds is None:
            bounds = _board_bounds(root)
        width = _track_width(segments, layer)
        obstacles = _obstacles(root, sites, segments, layer)
        try:
            tracks = route_net(
                [(site.x, site.y) for site in terminals],
                code,
                obstacles,
                bounds,
                width,
                _COPPER_CLEARANCE + _COPPER_MARGIN,
            )
        except RoutingError as exc:
            raise KicadDslError(
                f"cannot auto-route new net {name!r} on {layer}: {exc}"
            ) from exc
        for track in tracks:
            insertion += _new_track_text(track, code, layer, width)
        routed.append({
            "net": name,
            "layer": layer,
            "pads": [f"{site.reference}.{site.number}" for site in terminals],
            "segments": len(tracks),
            "length_mm": round(
                sum(math.hypot(item.x1 - item.x0, item.y1 - item.y0) for item in tracks), 3
            ),
        })
        segments += [
            _SegmentSite(node=None, layer=layer, net=code, width=width,
                         x0=track.x0, y0=track.y0, x1=track.x1, y1=track.y1)
            for track in tracks
        ]

    if insertion:
        anchors = [
            value for value in root.values
            if isinstance(value, _Node) and _head(value) in {"segment", "via"}
        ]
        position = anchors[-1].end if anchors else root.end - 1
        replacements.append((position, position, insertion))

    # A repaired candidate must not be worse than what a human would draw.
    moved_tracks = [item for item in segments if item.moved]
    if moved_tracks:
        for layer in {item.layer for item in moved_tracks}:
            obstacles = _obstacles(root, sites, segments, layer)
            width = _track_width(segments, layer)
            for item in moved_tracks:
                if item.layer != layer:
                    continue
                track = Track(item.x0, item.y0, item.x1, item.y1)
                if not track_is_clear(
                    track, item.net, obstacles, item.width / 2.0, _COPPER_CLEARANCE
                ):
                    raise KicadDslError(
                        f"repinned track on net {net_names.get(item.net, item.net)!r} "
                        f"would violate clearance on {layer}; route this net manually"
                    )
    return replacements, {"retargeted": retargeted, "routed": routed}


def apply_changes(source: str, document: EdaChangeDocument) -> str:
    return apply_changes_with_repair(source, document)[0]


def apply_changes_with_repair(
    source: str, document: EdaChangeDocument
) -> tuple[str, dict[str, Any]]:
    if _sha256(source) != document.source.sha256:
        raise KicadDslError("source hash changed; refresh sch2dsl/pcb2dsl before applying")
    parsed = inspect_source(source, document.source.path)
    if parsed.source.kind != document.source.kind:
        raise KicadDslError("DSL source kind does not match the KiCad file")
    root = _parse(source)
    replacements: list[tuple[int, int, str]] = []
    pad_targets: list[tuple[_Node, int]] = []
    created_nets: dict[int, str] = {}
    net_nodes = [
        value for value in root.values if isinstance(value, _Node) and _head(value) == "net"
    ]
    net_codes = {_text(node, 2): int(_text(node, 1)) for node in net_nodes}
    missing_nets = sorted(
        {
            operation.net
            for operation in document.operations
            if isinstance(operation, AssignPadNetOperation) and operation.net not in net_codes
        }
    )
    for net_name in missing_nets:
        operation = next(
            item
            for item in document.operations
            if isinstance(item, AssignPadNetOperation) and item.net == net_name
        )
        if not operation.create_if_missing:
            raise KicadDslError(f"PCB net {net_name!r} does not exist")
    if missing_nets:
        if not net_nodes:
            raise KicadDslError("PCB has no net table; cannot safely create a net")
        next_code = max((int(_text(node, 1)) for node in net_nodes), default=0) + 1
        insertion = ""
        for net_name in missing_nets:
            net_codes[net_name] = next_code
            created_nets[next_code] = net_name
            insertion += f"\n  (net {next_code} {json.dumps(net_name)})"
            next_code += 1
        replacements.append((net_nodes[-1].end, net_nodes[-1].end, insertion))
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
        elif isinstance(operation, AssignPadNetOperation):
            if parsed.source.kind != "pcb":
                raise KicadDslError("pad net assignment requires a PCB source")
            pads = [
                value
                for value in node.values
                if isinstance(value, _Node)
                and _head(value) == "pad"
                and _text(value, 1).casefold() == operation.pad.casefold()
            ]
            if len(pads) != 1:
                raise KicadDslError(
                    f"target pad {operation.pad!r} matched {len(pads)} objects in the footprint"
                )
            pad = pads[0]
            pad_targets.append((pad, net_codes[operation.net]))
            replacement = f"(net {net_codes[operation.net]} {json.dumps(operation.net)})"
            current_net = _child(pad, "net")
            if current_net is None:
                replacements.append((pad.end - 1, pad.end - 1, f" {replacement}"))
            else:
                replacements.append((current_net.start, current_net.end, replacement))
    repair: dict[str, Any] = {"retargeted": [], "routed": []}
    if parsed.source.kind == "pcb" and pad_targets:
        extra, repair = _copper_repair(
            root,
            pad_targets,
            created_nets,
            {code: name for name, code in net_codes.items()},
        )
        replacements += extra
    spans = sorted(replacements, reverse=True)
    for index, (start, end, replacement) in enumerate(spans):
        if index and end > spans[index - 1][0]:
            raise KicadDslError("overlapping operations are not allowed")
        source = source[:start] + replacement + source[end:]
    return source, repair


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


def change_validation(
    document: EdaChangeDocument, repair: dict[str, Any] | None = None
) -> dict[str, Any]:
    connectivity_changed = any(
        isinstance(operation, AssignPadNetOperation) for operation in document.operations
    )
    if connectivity_changed:
        if document.source.kind == "schematic":
            # PCB DRC has no meaning for a schematic candidate.  The caller
            # must run the schematic/netlist connectivity check instead.
            return {
                "status": "requires_follow_up",
                "codes": ["EDA_CONNECTIVITY_NOT_RUN"],
                "requires_routing": False,
                "connectivity": "not_run",
            }
        repaired = bool(repair and (repair.get("retargeted") or repair.get("routed")))
        return {
            "status": "requires_follow_up",
            "codes": ["EDA_DRC_NOT_RUN"] if repaired else
                     ["EDA_ROUTING_REQUIRED", "EDA_DRC_NOT_RUN"],
            "requires_routing": not repaired,
            "drc": "not_run",
            "copper_repair": repair or {"retargeted": [], "routed": []},
        }
    return {
        "status": "structurally_valid",
        "codes": [],
        "requires_routing": False,
        "drc": "not_required",
    }


def write_candidate(root: Path, output_root: Path, document: EdaChangeDocument) -> dict[str, Any]:
    path = resolve_source(root, document.source.path)
    original = path.read_text(encoding="utf-8")
    candidate, repair = apply_changes_with_repair(original, document)
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
        "validation": change_validation(document, repair),
        "copper_repair": repair,
        "created_at": datetime.now(UTC).isoformat(),
    }
    (target_dir / "change.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _prompt_item(prompt: str, document: EdaDocument) -> EdaItem:
    identity_tokens = re.findall(r"\b([a-z]{1,4}\d{1,6})\b", prompt, re.IGNORECASE)
    for token in identity_tokens:
        matches = [item for item in document.items if item.reference.casefold() == token.casefold()]
        if len(matches) == 1:
            return matches[0]
    for token in identity_tokens:
        token_folded = token.casefold()
        matches = [
            item
            for item in document.items
            if token_folded in item.value.casefold() or token_folded in item.library_id.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
    raise KicadDslError(
        "Prompt musi wskazać dokładnie jeden element, np. R1, SW3 lub RJ45.",
        code="EDA-DSL-TARGET-REQUIRED-001",
    )


def _pin_group(prompt: str, label_pattern: str) -> list[str]:
    match = re.search(
        rf"(?:{label_pattern})[^.;:]{{0,50}}?\bna"
        r"(?:\s+(?:pin(?:y|ach)?|pad(?:y|ach)?))?\s+"
        r"((?:\d+\s*(?:,|\bi\b|\boraz\b)\s*)*\d+)",
        prompt,
        re.IGNORECASE,
    )
    return re.findall(r"\d+", match.group(1)) if match else []


def _order_signal_nets(
    nets: list[str], pads: list[str], item: EdaItem
) -> list[str]:
    """Układa sieci sygnałowe zgodnie z geometrią już poprowadzonej miedzi.

    Kolejność deklaracji ("ENC_A, ENC_B, ENC_SW") jest przypadkowa wobec
    płytki. Jeśli każdą z tych sieci widać dziś na dokładnie jednym padzie
    złącza, przypisujemy je do nowych pinów w tej samej kolejności wzdłuż
    rzędu padów — wtedy przepięcie jest równoległym przesunięciem kikutów
    zamiast krzyżowania ścieżek.
    """
    pad_by_number = {pad.number: pad for pad in item.pads}
    origins: dict[str, EdaPad] = {}
    for net in nets:
        carriers = [pad for pad in item.pads if pad.net == net]
        if len(carriers) != 1:
            return nets
        origins[net] = carriers[0]
    involved = [origins[net] for net in nets] + [pad_by_number[number] for number in pads]
    spread_x = max(pad.x for pad in involved) - min(pad.x for pad in involved)
    spread_y = max(pad.y for pad in involved) - min(pad.y for pad in involved)
    axis = (lambda pad: pad.x) if spread_x >= spread_y else (lambda pad: pad.y)
    pad_order = sorted(range(len(pads)), key=lambda index: axis(pad_by_number[pads[index]]))
    by_position = sorted(nets, key=lambda net: axis(origins[net]))
    ordered = list(nets)
    for rank, index in enumerate(pad_order):
        ordered[index] = by_position[rank]
    return ordered


def _connectivity_operations(
    prompt: str, document: EdaDocument, item: EdaItem, target: EdaTarget
) -> list[EdaOperation]:
    if document.source.kind != "pcb" or item.entity != "footprint":
        return []
    ground_pads = _pin_group(prompt, r"mas(?:a|e|ę)|gnd")
    signal_pads = _pin_group(prompt, r"sygna(?:ł|l)(?:y|ów|ow)?")
    power_pads = _pin_group(prompt, r"plus(?:\s+z\w+)?|zasilan\w*|zaislan\w*|\+5v")
    if not any((ground_pads, signal_pads, power_pads)):
        return []
    if not all((ground_pads, signal_pads, power_pads)):
        raise KicadDslError(
            "connectivity request must specify the ground, signal and power pin groups"
        )
    selected_pads = ground_pads + signal_pads + power_pads
    if len(selected_pads) != len(set(selected_pads)):
        raise KicadDslError("the same pin cannot be assigned to more than one net group")
    available_pads = {pad.number for pad in item.pads}
    unknown_pads = sorted(set(selected_pads) - available_pads)
    if unknown_pads:
        raise KicadDslError(f"footprint {item.reference} has no pads: {', '.join(unknown_pads)}")
    available_nets = {net.name for net in document.nets}
    if "GND" not in available_nets:
        raise KicadDslError("PCB does not contain the required GND net")
    signal_nets = [name for name in ("ENC_A", "ENC_B", "ENC_SW") if name in available_nets]
    if len(signal_pads) != len(signal_nets):
        raise KicadDslError(
            "signal pin count must match the existing ENC_A, ENC_B and ENC_SW nets"
        )
    signal_nets = _order_signal_nets(signal_nets, signal_pads, item)
    assignments = (
        [(pad, "GND", False) for pad in ground_pads]
        + [(pad, net, False) for pad, net in zip(signal_pads, signal_nets, strict=True)]
        + [(pad, "+5V", "+5V" not in available_nets) for pad in power_pads]
    )
    operations: list[EdaOperation] = [
        AssignPadNetOperation(
            op="assign_pad_net",
            target=target,
            pad=pad,
            net=net,
            create_if_missing=create_if_missing,
        )
        for pad, net, create_if_missing in assignments
    ]
    if "+5V" not in available_nets:
        power_anchors = [
            (candidate, pad)
            for candidate in document.items
            for pad in candidate.pads
            if candidate.entity == "footprint"
            and candidate.uuid != item.uuid
            and pad.number.casefold() in {"5v", "+5v"}
        ]
        if len(power_anchors) != 1:
            raise KicadDslError(
                f"new +5V net requires one unambiguous 5V source pad; found {len(power_anchors)}"
            )
        anchor, anchor_pad = power_anchors[0]
        operations.append(
            AssignPadNetOperation(
                op="assign_pad_net",
                target=EdaTarget(uuid=anchor.uuid, reference=anchor.reference),
                pad=anchor_pad.number,
                net="+5V",
                create_if_missing=True,
            )
        )
    return operations


def local_nl_to_dsl(prompt: str, document: EdaDocument) -> EdaChangeDocument:
    lowered = prompt.casefold()
    item = _prompt_item(prompt, document)
    target = EdaTarget(uuid=item.uuid, reference=item.reference)
    operations = _connectivity_operations(prompt, document, item, target)
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


def _canonicalize_llm_targets(
    candidate: EdaChangeDocument, document: EdaDocument
) -> tuple[EdaChangeDocument, bool]:
    """Bind each LLM target to one unambiguous item from the supplied document.

    UUIDs are the authoritative identity during application.  Models sometimes
    reproduce a reference correctly while inventing or omitting its UUID, so we
    may fill in that UUID only when the supplied identity resolves to exactly
    one item.  Conflicting UUID/reference pairs and unknown identities remain
    rejected; this does not widen the document boundary.
    """
    canonical_operations: list[EdaOperation] = []
    repaired = False
    for operation in candidate.operations:
        target = operation.target
        uuid_matches = [
            item
            for item in document.items
            if item.entity == operation.entity and target.uuid and item.uuid == target.uuid
        ]
        reference_matches = [
            item
            for item in document.items
            if item.entity == operation.entity
            and target.reference
            and item.reference.casefold() == target.reference.casefold()
        ]
        if uuid_matches and reference_matches and uuid_matches[0] != reference_matches[0]:
            raise KicadDslError("LLM selected a component outside the supplied document")
        matches = uuid_matches or reference_matches
        if len(matches) != 1:
            raise KicadDslError("LLM selected a component outside the supplied document")
        item = matches[0]
        canonical_target = EdaTarget(uuid=item.uuid, reference=item.reference)
        if target != canonical_target:
            repaired = True
            operation = operation.model_copy(update={"target": canonical_target})
        canonical_operations.append(operation)
    if not repaired:
        return candidate, False
    return candidate.model_copy(update={"operations": canonical_operations}), True


def _ensure_effective_operations(candidate: EdaChangeDocument, document: EdaDocument) -> None:
    """Reject an LLM plan that only restates the current document state."""
    items = {item.uuid: item for item in document.items}
    for operation in candidate.operations:
        item = items[operation.target.uuid or ""]
        if isinstance(operation, SetPropertyOperation):
            current = item.value if operation.property == "Value" else item.footprint
            if current != operation.value:
                return
        elif isinstance(operation, MoveOperation):
            rotation = item.position.rotation if operation.rotation is None else operation.rotation
            if (item.position.x, item.position.y, item.position.rotation) != (
                operation.x,
                operation.y,
                rotation,
            ):
                return
        elif isinstance(operation, AssignPadNetOperation):
            pad = next((pad for pad in item.pads if pad.number == operation.pad), None)
            if pad is None or pad.net != operation.net:
                return
    raise KicadDslError(
        "LLM generated a no-op plan; every requested value already matches the supplied document"
    )


def _finalize_llm_candidate(
    candidate: EdaChangeDocument, document: EdaDocument, route_mode: str
) -> tuple[EdaChangeDocument, str]:
    if candidate.source != document.source:
        raise KicadDslError("LLM changed the immutable source identity")
    candidate, target_repaired = _canonicalize_llm_targets(candidate, document)
    _ensure_effective_operations(candidate, document)
    return candidate, f"{route_mode}:target-repaired" if target_repaired else route_mode


def _requests_connectivity_edit(prompt: str) -> bool:
    """Identify requests that require the deterministic pin/net compiler."""
    return bool(
        re.search(
            r"\b(?:pin(?:y|ach)?|pad(?:y|ach)?|net(?:y|ach)?|połączen(?:ie|ia|iu)|"
            r"connectivity|złącz(?:e|za|zu)|rj45|masa|masę|gnd|sygna(?:ł|l)(?:y|ów|ow)?|"
            r"zasilan(?:ie|ia|iu))\b",
            prompt,
            re.IGNORECASE,
        )
    )


# Prośby o poprowadzenie miedzi. DSL v1 zna tylko `set_property`, `move`
# i `assign_pad_net` — ścieżki tworzy deterministyczna naprawa, nie model.
# Bez tego rozpoznania model mieli takie zadanie minutami i kończy timeoutem
# albo odpowiedzią, której schemat nie przyjmuje.
_ROUTING_INTENT = re.compile(
    r"\b(przeprowad\w*|poprowad\w*|przetrasu\w*|trasu\w*|routing\w*|reroute\w*|"
    r"ście\w*k\w*|ścieżk\w*|sciezk\w*|linie|linii|przelotk\w*|via)\b",
    re.IGNORECASE,
)
_ROUTING_PLACE = re.compile(
    r"\b(pod|obok|dooko\w*|na oko\w*|omi\w*|z dala|inn\w+ (?:pin|gpio)|warstw\w*)\b",
    re.IGNORECASE,
)


def _requests_routing_edit(prompt: str) -> bool:
    return bool(_ROUTING_INTENT.search(prompt) and _ROUTING_PLACE.search(prompt))


def nl_to_dsl(
    prompt: str,
    document: EdaDocument,
    settings: Any,
    context_sources: list[dict[str, Any]] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[EdaChangeDocument, str]:
    """Kompiluje prompt do DSL; `diagnostics` zbiera powód odrzucenia.

    Gdy odpowiedź modelu nie przechodzi schematu, zostawała po niej sama
    nazwa wyjątku — `local-fallback:…:ValidationError`. Nie dało się z tego
    wywnioskować, czy model pomylił pole, czy odpowiedział prozą, więc
    poprawianie promptu było zgadywaniem. Kto chce znać szczegół, podaje
    słownik; reszta wywołań nic nie zmienia.
    """
    if _requests_connectivity_edit(prompt):
        # Klasyfikator łapie każdą wzmiankę o padzie, pinie czy sieci, ale
        # kompilator deterministyczny rozumie jeden kształt zdania. Gdy go nie
        # rozpozna, prompt ma trafić do modelu — wcześniej kończył się błędem
        # o R1 i SW1, a model nie był w ogóle pytany.
        try:
            candidate = local_nl_to_dsl(prompt, document)
        except KicadDslError:
            pass
        else:
            return _finalize_llm_candidate(candidate, document, "deterministic:connectivity")
    if _requests_routing_edit(prompt):
        raise KicadDslError(
            "Prowadzenie ścieżek nie należy do DSL v1 — dopuszcza on tylko "
            "set_property, move i assign_pad_net. Miedź układa deterministyczna "
            "naprawa, nie model. Zmień przypisanie sieci na padach (np. przenieś "
            "sygnał na inny pin GPIO), a trasowanie wykona się samo i przejdzie "
            "przez DRC; albo poprowadź ścieżkę ręcznie w KiCad."
        )
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
            "Never emit code and never change unselected components. "
            "For assign_pad_net, use only listed pads and nets unless create_if_missing is explicitly "
            "required by the request. "
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
                            "project_context": context_sources or [],
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
        if diagnostics is not None:
            diagnostics.update({
                "stage": "request", "route": route_mode, "error": str(exc)[:2000],
            })
        candidate = local_nl_to_dsl(prompt, document)
        return candidate, f"local-fallback:{route_mode}:{type(exc).__name__}"
    content = response.choices[0].message.content
    if isinstance(content, list):
        content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    try:
        candidate = EdaChangeDocument.model_validate_json(str(content))
    except Exception as exc:
        if diagnostics is not None:
            diagnostics.update({
                "stage": "schema",
                "route": route_mode,
                "error": str(exc)[:2000],
                "response": str(content)[:4000],
            })
        # ZAI's OpenAI-compatible endpoint cannot use response_format.  When it
        # nevertheless returns prose or an incomplete object, retain a useful
        # plan only if the deterministic, allow-listed compiler understands the
        # same request.  Unsupported requests remain a 422 rather than becoming
        # an unvalidated LLM change.
        try:
            candidate = local_nl_to_dsl(prompt, document)
        except KicadDslError:
            raise KicadDslError("LLM response does not conform to the strict EDA change schema") from exc
        return _finalize_llm_candidate(
            candidate, document, f"local-fallback:{route_mode}:{type(exc).__name__}"
        )
    return _finalize_llm_candidate(candidate, document, route_mode)
