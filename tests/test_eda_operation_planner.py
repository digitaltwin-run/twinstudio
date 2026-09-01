from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from twinstudio.eda_operation_planner import propose_eda_operation
from twinstudio.kicad_dsl import KicadDslError


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        subllm_enabled=False,
        litellm_model="test/model",
        litellm_api_base="",
        litellm_api_key="",
    )


def _response(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_operation_planner_returns_only_an_advertised_read_only_proposal(monkeypatch) -> None:
    captured: dict = {}

    def completion(**kwargs):
        captured.update(kwargs)
        return _response("""```json
{"decision":"propose","operation":"reroute_component_nets","input":{},"why":"Reduce routing cost.","interpretation":"Reroute the board.","limitations":["Placement is unchanged."]}
```""")

    fake = SimpleNamespace(completion=completion)
    monkeypatch.setitem(sys.modules, "litellm", fake)

    proposal, mode = propose_eda_operation(
        prompt="Zoptymalizuj routing i zmniejsz liczbę przelotek",
        source={"path": "pcb/panel9.kicad_pcb", "sha256": "a" * 64, "kind": "pcb"},
        operations=[{"id": "reroute_component_nets", "scope": "pcb", "implemented": True}],
        project_context={"default_component": "U1"},
        settings=_settings(),
    )

    assert proposal.operation == "reroute_component_nets"
    assert proposal.input == {}
    assert proposal.limitations == ["Placement is unchanged."]
    assert mode == "litellm:test/model"
    assert captured["max_tokens"] == 4_000
    assert captured["temperature"] == 0


def test_operation_planner_repairs_an_omitted_id_only_for_one_advertised_operation(
    monkeypatch,
) -> None:
    fake = SimpleNamespace(completion=lambda **_kwargs: _response(
        '{"decision":"propose","input":{},"why":"Reduce routing cost.",'
        '"interpretation":"Reroute the board.","limitations":[]}'
    ))
    monkeypatch.setitem(sys.modules, "litellm", fake)

    proposal, _mode = propose_eda_operation(
        prompt="Optimize routing",
        source={"path": "pcb/panel9.kicad_pcb"},
        operations=[{"id": "reroute_component_nets"}],
        project_context={},
        settings=_settings(),
    )

    assert proposal.operation == "reroute_component_nets"


@pytest.mark.parametrize(
    "content",
    [
        '{"decision":"propose","operation":"unknown","input":{},"why":"x","interpretation":"x","limitations":[]}',
        '{"decision":"propose","operation":"reroute_component_nets","input":{"approved":true},"why":"x","interpretation":"x","limitations":[]}',
        '{"decision":"propose","operation":"reroute_component_nets","input":{"via_cost":1.5},"why":"x","interpretation":"x","limitations":[]}',
    ],
)
def test_operation_planner_rejects_untrusted_capability_fields(monkeypatch, content: str) -> None:
    fake = SimpleNamespace(completion=lambda **_kwargs: _response(content))
    monkeypatch.setitem(sys.modules, "litellm", fake)

    with pytest.raises(KicadDslError):
        propose_eda_operation(
            prompt="route",
            source={"path": "pcb/panel9.kicad_pcb"},
            operations=[{"id": "reroute_component_nets"}],
            project_context={},
            settings=_settings(),
        )


def test_operation_planner_reports_an_empty_provider_response_explicitly(monkeypatch) -> None:
    response = _response("")
    response.choices[0].finish_reason = "length"
    response.choices[0].message.reasoning_content = "reasoning omitted"
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(completion=lambda **_kwargs: response),
    )

    with pytest.raises(KicadDslError, match="LLM-EMPTY-RESPONSE-001"):
        propose_eda_operation(
            prompt="route",
            source={"path": "pcb/panel9.kicad_pcb"},
            operations=[{"id": "reroute_component_nets"}],
            project_context={},
            settings=_settings(),
        )
