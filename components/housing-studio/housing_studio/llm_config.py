from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .config_diff import diff_as_dicts
from .models import ProjectConfig

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


@dataclass(slots=True)
class InterpretationResult:
    config: ProjectConfig
    mode: str
    message: str
    raw_response: str | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)


def _normalise_number(value: str) -> float:
    return float(value.replace(",", "."))


def _find_number(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _normalise_number(match.group(1))
    return None


def _set_nested(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    target: dict[str, Any] = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def fallback_interpret(prompt: str, current: ProjectConfig) -> InterpretationResult:
    """Deterministic, no-network parser for common dimensional and layer changes.

    This is intentionally conservative. Unrecognised or ambiguous phrases leave the current
    configuration unchanged instead of guessing.
    """

    data = current.model_dump(mode="json")
    changes: list[str] = []

    number_rules: list[tuple[tuple[str, ...], list[str], str]] = [
        (
            ("dimensions", "wall_thickness"),
            [
                r"(?:wall\s+thickness|grubo(?:ść|sc)\s+(?:wszystkich\s+)?(?:ścian|scian|ścianki|scianki))\D{0,20}(\d+(?:[\.,]\d+)?)",
                r"(\d+(?:[\.,]\d+)?)\s*mm\s+(?:wall|ścian|scian)",
            ],
            "wall thickness",
        ),
        (
            ("dimensions", "external_width"),
            [
                r"(?:external\s+width|szeroko(?:ść|sc)\s+zewnętrzna)\D{0,20}(\d+(?:[\.,]\d+)?)",
                r"(?:ustaw|zachowaj)\s+szeroko(?:ść|sc)\D{0,12}(\d+(?:[\.,]\d+)?)",
            ],
            "external width",
        ),
        (
            ("dimensions", "external_depth"),
            [r"(?:external\s+depth|głęboko(?:ść|sc)\s+zewnętrzna|glebokosc\s+zewnetrzna)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "external depth",
        ),
        (
            ("dimensions", "base_height"),
            [r"(?:base\s+height|wysoko(?:ść|sc)\s+podstawy)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "base height",
        ),
        (
            ("dimensions", "total_height"),
            [
                r"(?:total\s+height|całkowita\s+wysoko(?:ść|sc)|calkowita\s+wysokosc)\D{0,20}(\d+(?:[\.,]\d+)?)",
                r"(?:wysoko(?:ść|sc)\s+całkowit(?:a|ą)|wysokosc\s+calkowit(?:a|a))\D{0,20}(\d+(?:[\.,]\d+)?)",
            ],
            "total height",
        ),
        (
            ("dimensions", "lid_front_inset"),
            [r"(?:front\s+inset|odsunięcie\s+przodu|odsuniecie\s+przodu)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "lid front inset",
        ),
        (
            ("dimensions", "lid_side_inset"),
            [r"(?:side\s+inset|odsunięcie\s+boku|odsuniecie\s+boku)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "lid side inset",
        ),
        (
            ("hinge", "opening_angle_deg"),
            [
                r"(?:opening\s+angle|kąt\s+otwarcia|kat\s+otwarcia)\D{0,20}(\d+(?:[\.,]\d+)?)",
                r"(?:zawias\s+ma\s+)?otwiera(?:ć|c)\s+się\s+do\D{0,10}(\d+(?:[\.,]\d+)?)",
                r"hinge\s+(?:should\s+)?open\s+to\D{0,10}(\d+(?:[\.,]\d+)?)",
            ],
            "hinge opening angle",
        ),
        (
            ("hinge", "pin_diameter"),
            [r"(?:hinge\s+pin\s+diameter|średnica\s+sworznia|srednica\s+sworznia)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "hinge pin diameter",
        ),
        (
            ("board", "standoff", "height"),
            [r"(?:standoff\s+height|wysoko(?:ść|sc)\s+słupk(?:a|ów)|wysokosc\s+slupk(?:a|ow))\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "standoff height",
        ),
        (
            ("dimensions", "floor_thickness"),
            [r"(?:floor\s+thickness|bottom\s+thickness|grubo(?:ść|sc)\s+(?:dna|podłogi|podlogi))\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "floor thickness",
        ),
        (
            ("dimensions", "lid_top_thickness"),
            [r"(?:lid\s+top\s+thickness|roof\s+thickness|grubo(?:ść|sc)\s+(?:dachu|górnej\s+ściany|gornej\s+sciany))\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "lid top thickness",
        ),
        (
            ("dimensions", "lid_vertical_lower_section"),
            [r"(?:vertical\s+lid\s+section|pionow(?:y|a)\s+odcinek\s+klapy|ostatnie)\D{0,20}(\d+(?:[\.,]\d+)?)\s*mm"],
            "vertical lid section",
        ),
        (
            ("dimensions", "edge_radius"),
            [r"(?:edge\s+radius|promień\s+krawędzi|promien\s+krawedzi)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "edge radius",
        ),
        (
            ("mating", "fit_clearance"),
            [r"(?:fit\s+clearance|assembly\s+clearance|luz\s+montażowy|luz\s+montazowy)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "fit clearance",
        ),
        (
            ("hinge", "outer_diameter"),
            [r"(?:hinge\s+(?:outer\s+)?diameter|średnica\s+(?:zewnętrzna\s+)?zawiasu|srednica\s+(?:zewnetrzna\s+)?zawiasu)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "hinge outer diameter",
        ),
        (
            ("hinge", "pin_bore_clearance"),
            [r"(?:hinge\s+(?:bore\s+)?clearance|luz\s+otworu\s+zawiasu)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "hinge bore clearance",
        ),
        (
            ("hinge", "base_front_chamfer_angle_deg"),
            [r"(?:front\s+(?:base\s+)?chamfer\s+angle|kąt\s+ścięcia|kat\s+sciecia|faz(?:a|ę)\s+pod)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "front chamfer angle",
        ),
        (
            ("hinge", "base_front_chamfer_size"),
            [r"(?:front\s+(?:base\s+)?chamfer\s+size|wielko(?:ść|sc)\s+ścięcia|wielkosc\s+sciecia)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "front chamfer size",
        ),
        (
            ("hinge", "base_wall_relief"),
            [r"(?:base\s+wall\s+relief|obniżenie\s+ściany\s+podstawy|obnizenie\s+sciany\s+podstawy)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "base wall relief",
        ),
        (
            ("hinge", "lid_edge_relief"),
            [r"(?:lid\s+edge\s+relief|obniżenie\s+krawędzi\s+klapy|obnizenie\s+krawedzi\s+klapy)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "lid edge relief",
        ),
        (
            ("board", "standoff", "outer_diameter"),
            [r"(?:standoff\s+(?:outer\s+)?diameter|średnic(?:a|ę|y)\s+zewnętrzn(?:a|ą|ej)\s+słupk(?:a|ów)|srednic(?:a|e|y)\s+zewnetrzn(?:a|a|ej)\s+slupk(?:a|ow))\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "standoff outer diameter",
        ),
        (
            ("board", "standoff", "pilot_hole_diameter"),
            [r"(?:standoff\s+(?:pilot\s+)?hole\s+diameter|średnic(?:a|ę|y)\s+otworu\s+słupk(?:a|ów)|srednic(?:a|e|y)\s+otworu\s+slupk(?:a|ow))\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "standoff pilot diameter",
        ),
        (
            ("board", "position_a", "front_clearance"),
            [r"(?:position\s+a\s+front\s+clearance|pozycj(?:a|i)\s+a.*?od\s+przedniej)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "position A front clearance",
        ),
        (
            ("board", "position_a", "right_clearance"),
            [r"(?:position\s+a\s+right\s+clearance|pozycj(?:a|i)\s+a.*?od\s+prawej)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "position A right clearance",
        ),
        (
            ("board", "position_b", "right_clearance"),
            [r"(?:position\s+b\s+right\s+clearance|pozycj(?:a|i)\s+b.*?od\s+prawej)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "position B right clearance",
        ),
        (
            ("board", "position_b", "expected_left_clearance"),
            [r"(?:position\s+b\s+left\s+clearance|pozycj(?:a|i)\s+b.*?od\s+lewej)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "position B requested left clearance",
        ),
        (
            ("camera_mounts", "boss_height_after_reduction"),
            [r"(?:camera\s+boss\s+height|wysoko(?:ść|sc)\s+mocowań\s+kamery|wysokosc\s+mocowan\s+kamery)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "camera boss height",
        ),
        (
            ("auxiliary_lid_bosses", "top_z_from_base_mating_plane"),
            [r"(?:auxiliary\s+boss\s+top|top\s+of\s+(?:the\s+)?bosses|górna\s+powierzchnia\s+(?:dodatkowych\s+)?(?:punktów|słupków)|gorna\s+powierzchnia\s+(?:dodatkowych\s+)?(?:punktow|slupkow))\D{0,25}(\d+(?:[\.,]\d+)?)"],
            "auxiliary boss top datum",
        ),
        (
            ("auxiliary_lid_bosses", "outer_diameter"),
            [r"(?:auxiliary\s+boss\s+(?:outer\s+)?diameter|średnica\s+(?:dodatkowych\s+)?punktów\s+montażowych|srednica\s+(?:dodatkowych\s+)?punktow\s+montazowych)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "auxiliary boss outer diameter",
        ),
        (
            ("auxiliary_lid_bosses", "hole_diameter"),
            [r"(?:auxiliary\s+boss\s+hole\s+diameter|otwór\s+(?:dodatkowego\s+)?punktu\s+montażowego|otwor\s+(?:dodatkowego\s+)?punktu\s+montazowego)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "auxiliary boss hole diameter",
        ),
        (
            ("rear_tabs", "clearance_to_inner_wall"),
            [r"(?:rear\s+tab\s+clearance|odległo(?:ść|sc)\s+tylnych\s+łapek\s+od\s+wewnętrznej\s+ściany|odleglosc\s+tylnych\s+lapek\s+od\s+wewnetrznej\s+sciany)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "rear tab clearance",
        ),
        (
            ("rear_tabs", "middle_wall_reduction"),
            [r"(?:middle\s+wall\s+reduction|ściana\s+pomiędzy\s+łapkami\s+niższa|sciana\s+pomiedzy\s+lapkami\s+nizsza)\D{0,20}(\d+(?:[\.,]\d+)?)"],
            "rear middle wall reduction",
        ),
    ]

    for path, patterns, label in number_rules:
        value = _find_number(prompt, patterns)
        if value is not None:
            _set_nested(data, path, value)
            changes.append(f"{label}={value:g}")

    lower = prompt.lower()

    all_shell_thickness = _find_number(
        prompt,
        [
            r"(?:all\s+(?:shell\s+)?thicknesses|wall,?\s+floor\s+and\s+lid\s+thickness|grubo(?:ść|sc)\s+(?:całej|calej)\s+obudowy|grubo(?:ść|sc)\s+ścian,?\s*dna\s+i\s+dachu)\D{0,20}(\d+(?:[\.,]\d+)?)",
        ],
    )
    if all_shell_thickness is not None:
        for path in (
            ("dimensions", "wall_thickness"),
            ("dimensions", "floor_thickness"),
            ("dimensions", "lid_top_thickness"),
        ):
            _set_nested(data, path, all_shell_thickness)
        changes.append(f"all shell thicknesses={all_shell_thickness:g}")

    both_pcb_phrases = (
        "włącz oba zestawy słupków",
        "wlacz oba zestawy slupkow",
        "włącz oba warianty mocowania",
        "wlacz oba warianty mocowania",
        "enable both pcb mounting patterns",
        "enable both raspberry pi mounting patterns",
    )
    if any(phrase in lower for phrase in both_pcb_phrases):
        data["feature_layers"]["pcb_mount_a"]["enabled"] = True
        data["feature_layers"]["pcb_mount_b"]["enabled"] = True
        changes.append("layers pcb_mount_a/pcb_mount_b=on")

    layer_aliases = {
        "base_shell": ["base shell", "podstawa", "lower base"],
        "lid_shell": ["lid shell", "klapa", "pokrywa", "upper lid"],
        "hinge": ["hinge", "zawias"],
        "pcb_mount_a": ["pcb mount a", "mounting pattern a", "pozycja a"],
        "pcb_mount_b": [
            "pcb mount b",
            "mounting pattern b",
            "pcb position b",
            "position b",
            "pozycja b",
            "drugi wariant pcb",
        ],
        "camera_mounts": ["camera mounts", "mocowania kamery"],
        "lid_aux_bosses": ["auxiliary bosses", "dodatkowe słupki", "dodatkowe slupki"],
        "rear_tabs": ["rear tabs", "tylne łapki", "tylne lapki"],
        "connector_openings": ["connector openings", "otwory złączy", "otwory zlaczy"],
        "locating_lip": ["locating lip", "kołnierz ustalający", "kolnierz ustalajacy"],
        "pcb_reference": ["pcb reference", "referencja pcb"],
    }
    for layer_name, aliases in layer_aliases.items():
        for alias in aliases:
            disable_patterns = [f"disable {alias}", f"turn off {alias}", f"wyłącz {alias}", f"wylacz {alias}"]
            enable_patterns = [f"enable {alias}", f"turn on {alias}", f"włącz {alias}", f"wlacz {alias}"]
            if any(pattern in lower for pattern in disable_patterns):
                data["feature_layers"][layer_name]["enabled"] = False
                changes.append(f"layer {layer_name}=off")
                break
            if any(pattern in lower for pattern in enable_patterns):
                data["feature_layers"][layer_name]["enabled"] = True
                changes.append(f"layer {layer_name}=on")
                break

    drawing_layer_aliases = {
        "visible_edges": ["visible edges", "krawędzie widoczne", "krawedzie widoczne"],
        "hidden_edges": ["hidden edges", "krawędzie ukryte", "krawedzie ukryte"],
        "centerlines": ["centerlines", "center lines", "linie osiowe"],
        "dimensions": ["dimensions", "wymiary"],
        "notes": ["notes", "opisy"],
        "section_hatch": ["section hatch", "kreskowanie przekroju"],
        "pcb_reference": ["pcb reference", "referencja pcb"],
        "construction": ["construction", "linie konstrukcyjne"],
        "datums": ["datums", "bazy wymiarowe"],
    }
    keep_layer_context = any(
        phrase in lower
        for phrase in ("zachowaj warstwy", "włącz warstwy", "wlacz warstwy", "keep layers", "enable layers")
    )
    for field_name, aliases in drawing_layer_aliases.items():
        if any(f"without {alias}" in lower or f"bez {alias}" in lower or f"wyłącz {alias}" in lower or f"wylacz {alias}" in lower for alias in aliases):
            data["drawing"]["layers"][field_name]["enabled"] = False
            changes.append(f"drawing layer {field_name}=off")
        elif keep_layer_context and any(alias in lower for alias in aliases):
            data["drawing"]["layers"][field_name]["enabled"] = True
            changes.append(f"drawing layer {field_name}=on")

    artifact_aliases = {
        "export_step": ["step"],
        "export_stl": ["stl"],
        "export_obj": ["obj"],
        "export_glb": ["glb"],
        "export_dxf": ["dxf"],
        "export_svg": ["svg"],
        "export_pdf": ["pdf"],
        "create_zip": ["zip", "paczka zip"],
    }
    for field_name, aliases in artifact_aliases.items():
        disable = any(
            phrase in lower
            for alias in aliases
            for phrase in (
                f"without {alias}",
                f"disable {alias}",
                f"disable export {alias}",
                f"turn off {alias}",
                f"turn off {alias} export",
                f"wyłącz {alias}",
                f"wylacz {alias}",
                f"wyłącz eksport {alias}",
                f"wylacz eksport {alias}",
                f"bez {alias}",
                f"bez eksportu {alias}",
            )
        )
        enable = any(
            phrase in lower
            for alias in aliases
            for phrase in (
                f"include {alias}",
                f"include {alias} export",
                f"enable {alias}",
                f"enable export {alias}",
                f"turn on {alias}",
                f"włącz {alias}",
                f"wlacz {alias}",
                f"włącz eksport {alias}",
                f"wlacz eksport {alias}",
                f"dodaj {alias}",
                f"dodaj eksport {alias}",
            )
        )
        if disable:
            data["artifacts"][field_name] = False
            changes.append(f"artifact {field_name}=off")
        elif enable:
            data["artifacts"][field_name] = True
            changes.append(f"artifact {field_name}=on")

    drawing_view_aliases = {
        "include_front": ["front view", "widok z przodu"],
        "include_top": ["top view", "widok z góry", "widok z gory"],
        "include_side": ["side view", "widok z boku"],
    }
    keep_views_context = any(
        phrase in lower
        for phrase in ("zachowaj widoki", "włącz widoki", "wlacz widoki", "keep views", "include views")
    )
    for field_name, aliases in drawing_view_aliases.items():
        if any(f"without {a}" in lower or f"bez {a}" in lower for a in aliases):
            data["drawing"][field_name] = False
            changes.append(f"drawing {field_name}=off")
        if any(f"include {a}" in lower or f"dodaj {a}" in lower for a in aliases) or (
            keep_views_context and any(a in lower for a in aliases)
        ):
            data["drawing"][field_name] = True
            changes.append(f"drawing {field_name}=on")

    config = ProjectConfig.model_validate(data)
    if changes:
        message = "Fallback parser applied: " + ", ".join(changes)
    else:
        message = (
            "No supported deterministic instruction was recognised. "
            "Configure LITELLM_MODEL and a provider API key for full natural-language interpretation."
        )
    return InterpretationResult(
        config=config,
        mode="fallback",
        message=message,
        changes=diff_as_dicts(current, config),
    )


def _json_schema_response_format() -> dict[str, Any]:
    schema = ProjectConfig.model_json_schema(mode="serialization")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "housing_project_config",
            "strict": True,
            "schema": schema,
        },
    }


def _response_content(response: Any) -> str:
    content = response.choices[0].message.content
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def interpret_with_litellm(
    prompt: str,
    current: ProjectConfig,
    *,
    model: str | None = None,
) -> InterpretationResult:
    """Convert a Polish or English natural-language change request into a full config.

    The model never emits executable CAD code. It emits JSON constrained by the Pydantic
    ProjectConfig schema, which is validated before any geometry is generated.
    """

    selected_model = model or os.getenv("LITELLM_MODEL", "").strip()
    if not selected_model:
        return fallback_interpret(prompt, current)

    try:
        from litellm import completion
    except ImportError:
        result = fallback_interpret(prompt, current)
        result.message = "LiteLLM is not installed; " + result.message
        return result

    system_message = (
        "You are a configuration compiler for a parametric 2D/3D CAD housing generator. "
        "The user may write in Polish or English. Return a COMPLETE ProjectConfig JSON object. "
        "Preserve every current value that the user did not explicitly change. Never invent a missing dimension. "
        "If a statement is ambiguous or contradictory, keep the current value. Feature layers control whether "
        "a geometry feature is generated; drawing.layers control DXF/SVG/PDF layer names and styles. "
        "Do not return explanations, Markdown, code, comments, units inside numeric fields, or additional keys."
    )
    user_message = (
        "CURRENT CONFIGURATION:\n"
        + current.model_dump_json(indent=2)
        + "\n\nREQUESTED CHANGES:\n"
        + prompt
    )

    call_kwargs: dict[str, Any] = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "timeout": float(os.getenv("LITELLM_TIMEOUT", "60")),
    }
    api_base = os.getenv("LITELLM_API_BASE", "").strip()
    api_key = os.getenv("LITELLM_API_KEY", "").strip()
    if api_base:
        call_kwargs["api_base"] = api_base
    if api_key:
        call_kwargs["api_key"] = api_key

    strict_error: Exception | None = None
    try:
        response = completion(
            **call_kwargs,
            response_format=_json_schema_response_format(),
        )
        content = _response_content(response)
        config = ProjectConfig.model_validate_json(content)
        return InterpretationResult(
            config=config,
            mode="litellm_json_schema",
            message=f"Configuration compiled with LiteLLM model {selected_model}.",
            raw_response=content,
            changes=diff_as_dicts(current, config),
        )
    except Exception as exc:  # Provider/model structured-output support varies.
        strict_error = exc

    try:
        response = completion(
            **call_kwargs,
            response_format={"type": "json_object"},
        )
        content = _response_content(response)
        config = ProjectConfig.model_validate_json(content)
        return InterpretationResult(
            config=config,
            mode="litellm_json_object",
            message=(
                f"Configuration compiled with LiteLLM model {selected_model} using JSON mode "
                "because strict JSON Schema mode was unavailable."
            ),
            raw_response=content,
            changes=diff_as_dicts(current, config),
        )
    except Exception as json_error:
        fallback = fallback_interpret(prompt, current)
        fallback.message = (
            "LiteLLM failed; deterministic fallback was used. "
            f"Structured-output error: {strict_error!s}. JSON-mode error: {json_error!s}. "
            + fallback.message
        )
        return fallback
