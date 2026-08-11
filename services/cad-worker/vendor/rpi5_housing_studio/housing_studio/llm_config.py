from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .models import ProjectConfig


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


@dataclass(slots=True)
class InterpretationResult:
    config: ProjectConfig
    mode: str
    message: str
    raw_response: str | None = None


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
    ]

    for path, patterns, label in number_rules:
        value = _find_number(prompt, patterns)
        if value is not None:
            _set_nested(data, path, value)
            changes.append(f"{label}={value:g}")

    lower = prompt.lower()

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
    for field, aliases in drawing_layer_aliases.items():
        if any(f"without {alias}" in lower or f"bez {alias}" in lower or f"wyłącz {alias}" in lower or f"wylacz {alias}" in lower for alias in aliases):
            data["drawing"]["layers"][field]["enabled"] = False
            changes.append(f"drawing layer {field}=off")
        elif keep_layer_context and any(alias in lower for alias in aliases):
            data["drawing"]["layers"][field]["enabled"] = True
            changes.append(f"drawing layer {field}=on")

    drawing_view_aliases = {
        "include_front": ["front view", "widok z przodu"],
        "include_top": ["top view", "widok z góry", "widok z gory"],
        "include_side": ["side view", "widok z boku"],
    }
    keep_views_context = any(
        phrase in lower
        for phrase in ("zachowaj widoki", "włącz widoki", "wlacz widoki", "keep views", "include views")
    )
    for field, aliases in drawing_view_aliases.items():
        if any(f"without {a}" in lower or f"bez {a}" in lower for a in aliases):
            data["drawing"][field] = False
            changes.append(f"drawing {field}=off")
        if any(f"include {a}" in lower or f"dodaj {a}" in lower for a in aliases) or (
            keep_views_context and any(a in lower for a in aliases)
        ):
            data["drawing"][field] = True
            changes.append(f"drawing {field}=on")

    config = ProjectConfig.model_validate(data)
    if changes:
        message = "Fallback parser applied: " + ", ".join(changes)
    else:
        message = (
            "No supported deterministic instruction was recognised. "
            "Configure LITELLM_MODEL and a provider API key for full natural-language interpretation."
        )
    return InterpretationResult(config=config, mode="fallback", message=message)


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
        )
    except Exception as json_error:
        fallback = fallback_interpret(prompt, current)
        fallback.message = (
            "LiteLLM failed; deterministic fallback was used. "
            f"Structured-output error: {strict_error!s}. JSON-mode error: {json_error!s}. "
            + fallback.message
        )
        return fallback
