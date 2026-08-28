"""Read-only conversational review of deterministic SCH/PCB facts.

The model never receives authority to mutate KiCad files.  Viewer computes the
facts with the same parity/style/netlist validators used by candidate gates;
this module only explains them, asks for missing design intent and suggests a
next candidate operation.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import Field

from twinstudio.kicad_dsl import DslModel, eda_litellm_route

logger = logging.getLogger(__name__)


class EdaChatMessage(DslModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=30_000)


class EdaChatFact(DslModel):
    severity: Literal["info", "warning", "error"] = "info"
    code: str = Field(min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=2_000)
    evidence_paths: list[str] = Field(default_factory=list, max_length=20)


class EdaChatChoice(DslModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=500)


class EdaChatQuestion(DslModel):
    id: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=2_000)
    required: bool = True
    choices: list[EdaChatChoice] = Field(default_factory=list, max_length=12)
    affects: list[str] = Field(default_factory=list, max_length=20)


class EdaChatAction(DslModel):
    title: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2_000)
    paths: list[str] = Field(default_factory=list, max_length=20)
    operation: str | None = Field(default=None, max_length=160)
    requires_candidate: bool = True


class EdaChatResponse(DslModel):
    schema_id: Literal["twinstudio.eda-chat-response/v1"] = "twinstudio.eda-chat-response/v1"
    mode: str = "subllm"
    summary: str = Field(min_length=1, max_length=4_000)
    facts: list[EdaChatFact] = Field(default_factory=list, max_length=50)
    questions: list[EdaChatQuestion] = Field(default_factory=list, max_length=20)
    proposed_actions: list[EdaChatAction] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    requires_human_review: bool = True


def _report_summary(context: dict[str, Any], name: str) -> tuple[bool, int, list[str]]:
    report = context.get(name)
    if not isinstance(report, dict):
        return False, 0, []
    blocking = bool(report.get("blocking"))
    codes = [str(value) for value in report.get("codes", []) if isinstance(value, str)]
    count = 0
    counts = report.get("counts")
    if isinstance(counts, dict):
        for key in ("violations", "mismatches", "mismatched", "incomplete", "total", "blocking"):
            value = counts.get(key)
            if isinstance(value, int):
                count = max(count, value)
    categories = report.get("categories")
    if isinstance(categories, dict):
        count = max(count, sum(value for value in categories.values() if isinstance(value, int)))
    rules = report.get("rules")
    if isinstance(rules, list):
        count = max(count, sum(
            int(rule.get("count", 0)) for rule in rules if isinstance(rule, dict)
        ))
    findings = report.get("findings")
    if isinstance(findings, list):
        count = max(count, len(findings))
    violations = report.get("violations")
    if isinstance(violations, int):
        count = max(count, violations)
    elif isinstance(violations, list):
        count = max(count, len(violations))
    return blocking, count, codes


def _local_response(context: dict[str, Any]) -> EdaChatResponse:
    paths = [str(value) for value in context.get("paths", []) if isinstance(value, str)]
    facts: list[EdaChatFact] = []
    for key, label in (
        ("parity", "zgodność SCH–PCB"),
        ("schematic_style", "czytelność schematu"),
        ("pcb_style", "profil PCB"),
        ("drc", "DRC"),
    ):
        blocking, count, codes = _report_summary(context, key)
        severity: Literal["info", "warning", "error"] = "error" if blocking else ("warning" if count else "info")
        facts.append(EdaChatFact(
            severity=severity,
            code=(codes[0] if codes else f"{key}_measured"),
            message=f"{label}: {'blokada' if blocking else f'{count} ustaleń' if count else 'bez wykrytych naruszeń'}.",
            evidence_paths=paths,
        ))
    errors = context.get("errors")
    if isinstance(errors, list):
        for error in errors[:10]:
            if isinstance(error, dict):
                facts.append(EdaChatFact(
                    severity="error",
                    code=f"{error.get('check', 'check')}_not_run",
                    message=str(error.get("error") or "kontrola nie została wykonana"),
                    evidence_paths=paths,
                ))
    return EdaChatResponse(
        mode="local-fallback",
        summary=(
            "Kontrole deterministyczne zostały policzone, ale trasa rozmowy SubLLM "
            "nie była dostępna. Poniższe fakty pozostają miarodajne; sugestie wymagają ręcznej decyzji."
        ),
        facts=facts,
        proposed_actions=[EdaChatAction(
            title="Wybierz jedno ustalenie i utwórz osobnego kandydata",
            reason="Atomowa zmiana pozwala odróżnić poprawę od regresji w parity, profilu i DRC.",
            paths=paths,
        )],
        limitations=[
            "Tryb lokalny nie interpretuje celu zapisanego językiem naturalnym.",
            "Żadna odpowiedź rozmowy nie akceptuje ani nie promuje kandydata.",
        ],
    )


def _parse_response(content: Any) -> EdaChatResponse:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    parsed = EdaChatResponse.model_validate_json(text)
    meaningful_summary = parsed.summary.strip(" .,…—-_\n\t")
    if len(meaningful_summary) < 20:
        raise ValueError("LLM-DEGENERATE-RESPONSE-001: summary contains no useful explanation")
    if not (parsed.facts or parsed.questions or parsed.proposed_actions):
        raise ValueError("LLM-DEGENERATE-RESPONSE-002: response contains no facts, questions or actions")
    return parsed


def _routes(settings: Any) -> list[tuple[dict[str, Any], str, bool]]:
    chat_function = getattr(settings, "subllm_chat_function", "eda-conflict-chat")
    fallback_function = getattr(settings, "subllm_function", "eda-nl2dsl")
    functions = list(dict.fromkeys((chat_function, fallback_function)))
    if getattr(settings, "subllm_enabled", False):
        from subllm import available_routes

        for function in functions:
            try:
                routes = available_routes(settings.subllm_application, function)
            except Exception as exc:
                logger.info("EDA chat SubLLM route %s unavailable: %s", function, exc)
                continue
            permitted = [
                (
                    route.litellm_kwargs(),
                    f"subllm:{function}:{route.provider}/{route.model}",
                    route.provider != "zai",
                )
                for route in routes
                if route.transport == "openai-compatible"
            ]
            if permitted:
                return permitted
        return []
    for function in functions:
        try:
            resolved = eda_litellm_route(settings, function)
        except Exception:
            continue
        if resolved is not None:
            return [resolved]
    return []


def respond_to_eda_chat(
    deterministic_context: dict[str, Any],
    messages: list[EdaChatMessage],
    settings: Any,
) -> EdaChatResponse:
    """Explain measured facts without turning chat into a mutation channel."""
    fallback = _local_response(deterministic_context)
    try:
        routes = _routes(settings)
    except Exception as exc:
        logger.warning("EDA chat could not resolve SubLLM route: %s", exc)
        return fallback.model_copy(update={"mode": f"local-fallback:{type(exc).__name__}"})
    if not routes:
        return fallback
    schema = EdaChatResponse.model_json_schema()
    failures: list[Exception] = []
    for route_kwargs, mode, supports_response_schema in routes:
        try:
            from litellm import completion

            kwargs: dict[str, Any] = {
                **route_kwargs,
                "timeout": 90,
                "num_retries": 0,
                "max_tokens": 2_400,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a read-only PCB/schematic design review assistant. The deterministic_context "
                            "is measured evidence and must override guesses. Reply in the user's language as exactly "
                            "one JSON object matching output_schema. Separate facts from suggestions. When the user "
                            "has not said what must remain fixed, ask a bounded question with explicit choices. Never "
                            "claim an edit, approval, promotion, ERC, DRC or parity check that is absent from context. "
                            "A proposed mutation must require the candidate flow."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "deterministic_context": deterministic_context,
                                "conversation": [item.model_dump(mode="json") for item in messages[-30:]],
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
                    "json_schema": {"name": "eda_chat_response", "strict": True, "schema": schema},
                }
            response = completion(**kwargs)
            content = response.choices[0].message.content
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            parsed = _parse_response(content)
            return parsed.model_copy(update={"mode": mode, "requires_human_review": True})
        except Exception as exc:
            failures.append(exc)
            logger.warning("EDA chat route %s rejected: %s", mode, exc)
    last = failures[-1] if failures else RuntimeError("no route attempted")
    return fallback.model_copy(update={"mode": f"local-fallback:{type(last).__name__}"})
