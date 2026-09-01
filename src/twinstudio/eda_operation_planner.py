"""Read-only LLM selection of one operation from a caller-supplied EDA vocabulary.

The model never receives an execution capability here.  It may only translate
the user's intent into one operation that the caller already advertised; the
caller remains responsible for building a hash-bound plan and obtaining human
approval before execution.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import Field, model_validator

from twinstudio.kicad_dsl import DslModel, KicadDslError, eda_litellm_route

logger = logging.getLogger(__name__)


class EdaOperationProposal(DslModel):
    schema_id: Literal["twinstudio.eda-operation-proposal/v1"] = (
        "twinstudio.eda-operation-proposal/v1"
    )
    decision: Literal["propose", "unsupported"]
    operation: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    input: dict[str, Any] = Field(default_factory=dict)
    why: str = Field(min_length=1, max_length=4_000)
    interpretation: str = Field(min_length=1, max_length=4_000)
    limitations: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def decision_matches_operation(self) -> "EdaOperationProposal":
        if self.decision == "propose" and not self.operation:
            raise ValueError("a proposed operation requires its identifier")
        if self.decision == "unsupported" and (self.operation is not None or self.input):
            raise ValueError("an unsupported request cannot smuggle an operation or input")
        return self


def _parse_proposal(
    content: Any, *, sole_operation: str | None = None
) -> EdaOperationProposal:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    document = json.loads(text)
    # Some providers omit an echoed enum even after explicitly deciding to
    # propose.  Filling it is safe only when the caller advertised exactly one
    # capability; unlike fuzzy name repair this cannot broaden authority.
    if (
        sole_operation is not None
        and isinstance(document, dict)
        and document.get("decision") == "propose"
        and document.get("operation") in (None, "")
    ):
        document["operation"] = sole_operation
    return EdaOperationProposal.model_validate(document)


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    return False


def _routes(settings: Any) -> list[tuple[dict[str, Any], str, bool]]:
    if getattr(settings, "subllm_enabled", False):
        from subllm import available_routes

        routes = available_routes(settings.subllm_application, settings.subllm_function)
        return [
            (route.litellm_kwargs(), f"subllm:{route.provider}/{route.model}", route.provider != "zai")
            for route in routes
            if route.transport == "openai-compatible"
        ]
    resolved = eda_litellm_route(settings)
    return [resolved] if resolved is not None else []


def propose_eda_operation(
    *,
    prompt: str,
    source: dict[str, Any],
    operations: list[dict[str, Any]],
    project_context: dict[str, Any],
    settings: Any,
) -> tuple[EdaOperationProposal, str]:
    """Select one advertised operation without planning or executing it."""
    operation_ids = {
        str(item.get("id"))
        for item in operations
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if not operation_ids:
        raise KicadDslError("EDA operation planner received no supported operations")
    encoded = json.dumps(
        {"source": source, "operations": operations, "project_context": project_context},
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    if len(encoded.encode("utf-8")) > 240_000:
        raise KicadDslError("EDA operation planning context exceeds 240000 bytes")
    try:
        routes = _routes(settings)
    except Exception as exc:
        raise KicadDslError(
            f"EDA LLM operation route is unavailable: {type(exc).__name__}"
        ) from exc
    if not routes:
        raise KicadDslError("EDA LLM operation route is not configured")

    failures: list[Exception] = []
    schema = EdaOperationProposal.model_json_schema()
    for route_kwargs, mode, supports_response_schema in routes:
        try:
            from litellm import completion

            kwargs: dict[str, Any] = {
                **route_kwargs,
                "timeout": 45,
                "num_retries": 0,
                # GLM 5.x rozlicza tokeny rozumowania z tego samego budżetu.
                # Przy 1000 tokenów poprawna odpowiedź kończyła się
                # finish_reason=length i pustym contentem dla rzeczywistego
                # kontekstu panel9. 4000 pozostaje małym, ograniczonym budżetem,
                # ale zostawia miejsce na krótki obiekt po analizie słownika.
                "max_tokens": 4_000,
                # The planner translates intent into a closed operation enum;
                # creative sampling only makes repeated review attempts drift.
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a read-only EDA operation planner. Select exactly one operation "
                            "from the supplied implemented vocabulary only when it can materially "
                            "satisfy the user's request. Never execute, approve, promote, or invent an "
                            "operation. Do not include an approved field. Do not invent coordinates; "
                            "omit optional input when the user did not supply it. Integers in at_um are "
                            "micrometres and JSON floating-point values are forbidden. If no advertised "
                            "operation fits, return decision=unsupported. State partial coverage and "
                            "unperformed placement search in limitations. Permission to move components "
                            "does not itself make movement mandatory. Prefer the advertised operation "
                            "that covers the explicit objectives most completely. When the user permits "
                            "placement and an advertised placement-plus-routing operation can improve the "
                            "requested routing metrics, select it; otherwise disclose the missing search. "
                            "Return one JSON object only."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "prompt": prompt,
                                "source": source,
                                "implemented_operations": operations,
                                "project_context": project_context,
                                "output_schema": schema,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            allow_nan=False,
                        ),
                    },
                ],
            }
            if supports_response_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "eda_operation_proposal",
                        "strict": True,
                        "schema": schema,
                    },
                }
            response = completion(**kwargs)
            content = response.choices[0].message.content
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            if not str(content or "").strip():
                finish_reason = str(getattr(response.choices[0], "finish_reason", "unknown"))
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                raise ValueError(
                    "LLM-EMPTY-RESPONSE-001: provider returned an empty completion "
                    f"(finish_reason={finish_reason}, reasoning_chars={len(reasoning or '')})"
                )
            proposal = _parse_proposal(
                content,
                sole_operation=next(iter(operation_ids)) if len(operation_ids) == 1 else None,
            )
            if proposal.decision == "propose" and proposal.operation not in operation_ids:
                raise ValueError(f"operation is outside the advertised vocabulary: {proposal.operation}")
            if "approved" in proposal.input:
                raise ValueError("model input cannot grant human approval")
            if _contains_float(proposal.input):
                raise ValueError("operation input contains a forbidden JSON float")
            return proposal, mode
        except Exception as exc:
            failures.append(exc)
            logger.warning("EDA operation planner route %s rejected: %s", mode, exc)
    last = failures[-1] if failures else RuntimeError("no LLM route was attempted")
    raise KicadDslError(
        f"EDA LLM operation proposal was rejected: {type(last).__name__}: {last}"
    ) from last
