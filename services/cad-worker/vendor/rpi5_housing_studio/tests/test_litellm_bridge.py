from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

from housing_studio.llm_config import interpret_with_litellm
from housing_studio.models import default_project_config


def test_litellm_structured_output_bridge(monkeypatch) -> None:
    current = default_project_config()
    expected = current.model_dump(mode="json")
    expected["dimensions"]["wall_thickness"] = 2.6

    def fake_completion(**kwargs):
        assert kwargs["model"] == "test/provider-model"
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["strict"] is True
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(expected)))]
        )

    fake_module = ModuleType("litellm")
    fake_module.completion = fake_completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    result = interpret_with_litellm(
        "Set wall thickness to 2.6 mm",
        current,
        model="test/provider-model",
    )

    assert result.mode == "litellm_json_schema"
    assert result.config.dimensions.wall_thickness == 2.6
    assert result.raw_response is not None
