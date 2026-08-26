import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from twinstudio.kicad_dsl import (
    EdaChangeDocument,
    EdaTarget,
    KicadDslError,
    MoveOperation,
    SetPropertyOperation,
    apply_changes,
    eda_llm_status,
    inspect_file,
    inspect_source,
    local_nl_to_dsl,
    nl_to_dsl,
    resolve_source,
    write_candidate,
)

SCH = """(kicad_sch (version 20211123) (generator eeschema)
  (lib_symbols (symbol "local:R" (property "Reference" "R")))
  (symbol (lib_id "local:R") (at 10.00 20.00 90) (unit 1)
    (uuid 11111111-1111-1111-1111-111111111111)
    (property "Reference" "R1" (id 0) (at 10 20 0))
    (property "Value" "1k" (id 1) (at 10 21 0))
    (property "Footprint" "local:R_0603" (id 2) (at 10 22 0) hide)
    (pin "1" (uuid 22222222-2222-2222-2222-222222222222)))
)\n"""


PCB = """(kicad_pcb (version 20221018) (generator pcbnew)
  (footprint "local:R_0603" (layer "B.Cu") (tstamp aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa)
    (at 100.000 50.000)
    (fp_text reference "R1" (at 0 -2) (layer "B.SilkS"))
    (fp_text value "1k" (at 0 2) (layer "B.SilkS") hide)
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "B.Cu")))
)\n"""


def test_sch2dsl_reads_only_placed_symbols() -> None:
    document = inspect_source(SCH, "panel.kicad_sch")

    assert document.source.kind == "schematic"
    assert document.source.kicad_version == 20211123
    assert len(document.items) == 1
    assert document.items[0].reference == "R1"
    assert document.items[0].position.rotation == 90


def test_dsl2sch_changes_only_selected_property() -> None:
    source = inspect_source(SCH, "panel.kicad_sch").source
    change = EdaChangeDocument(
        source=source,
        operations=[
            SetPropertyOperation(
                op="set_property",
                target=EdaTarget(reference="R1"),
                property="Value",
                value="10k",
            )
        ],
    )

    candidate = apply_changes(SCH, change)

    assert '(property "Value" "10k"' in candidate
    assert '(property "Value" "1k"' not in candidate
    assert '(pin "1" (uuid 22222222-2222-2222-2222-222222222222))' in candidate


def test_pcb2dsl_and_move_preserve_footprint_children() -> None:
    document = inspect_source(PCB, "panel.kicad_pcb")
    change = EdaChangeDocument(
        source=document.source,
        operations=[
            MoveOperation(
                op="move",
                entity="footprint",
                target=EdaTarget(uuid=document.items[0].uuid, reference="R1"),
                x=120,
                y=75.5,
            )
        ],
    )

    candidate = apply_changes(PCB, change)

    assert "(at 120 75.5 0)" in candidate
    assert '(pad "1" smd rect' in candidate


def test_stale_source_is_rejected() -> None:
    document = inspect_source(SCH, "panel.kicad_sch")
    change = local_nl_to_dsl("ustaw wartość R1 na 10k", document)

    with pytest.raises(KicadDslError, match="source hash changed"):
        apply_changes(SCH.replace('"1k"', '"2k"'), change)


def test_local_nl_to_dsl_supports_polish_value_and_move() -> None:
    sch = inspect_source(SCH, "panel.kicad_sch")
    pcb = inspect_source(PCB, "panel.kicad_pcb")

    value = local_nl_to_dsl("ustaw wartość R1 na 10k", sch)
    move = local_nl_to_dsl("przesuń R1 do x=120 y=75,5", pcb)

    assert value.operations[0].value == "10k"
    assert move.operations[0].x == 120
    assert move.operations[0].y == 75.5


def test_file_boundary_and_candidate_copy(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    output = tmp_path / "output"
    root.mkdir()
    source_path = root / "panel.kicad_sch"
    source_path.write_text(SCH, encoding="utf-8")
    document = inspect_file(root, "panel.kicad_sch")
    change = local_nl_to_dsl("ustaw wartość R1 na 10k", document)

    result = write_candidate(root, output, change)

    assert source_path.read_text(encoding="utf-8") == SCH
    assert (output / result["candidate_path"]).is_file()
    assert (output / result["candidate_path"]).with_name("change.json").is_file()
    with pytest.raises(KicadDslError):
        resolve_source(root, "../outside.kicad_sch")


def test_subllm_route_drives_strict_eda_compilation(monkeypatch: pytest.MonkeyPatch) -> None:
    document = inspect_source(SCH, "panel.kicad_sch")
    expected = local_nl_to_dsl("ustaw wartość R1 na 10k", document)
    captured = {}

    class Route:
        application = "twinstudio"
        function = "eda-nl2dsl"
        provider = "zai"
        model = "glm-5.3"
        transport = "openai-compatible"

        @staticmethod
        def litellm_kwargs():
            return {"model": "zai/glm-5.3", "api_key": "test-secret", "api_base": "https://example.test"}

    def completion(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content=expected.model_dump_json())
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setitem(sys.modules, "subllm", SimpleNamespace(resolve=lambda *_args: Route()))
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    settings = SimpleNamespace(
        subllm_enabled=True,
        subllm_application="twinstudio",
        subllm_function="eda-nl2dsl",
        litellm_model="",
        litellm_api_base="",
        litellm_api_key="",
    )

    result, mode = nl_to_dsl("ustaw wartość R1 na 10k", document, settings)

    assert mode == "subllm:zai/glm-5.3"
    assert result == expected
    assert captured["model"] == "zai/glm-5.3"
    assert "response_format" not in captured
    request_payload = json.loads(captured["messages"][1]["content"])
    assert request_payload["output_schema"]["title"] == "EdaChangeDocument"
    assert eda_llm_status(settings)["available"] is True
