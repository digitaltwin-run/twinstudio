import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from twinstudio import kicad_dsl
from twinstudio.kicad_dsl import (
    EdaChangeDocument,
    EdaTarget,
    KicadDslError,
    MoveOperation,
    SetPropertyOperation,
    apply_changes,
    apply_changes_with_repair,
    change_validation,
    eda_llm_status,
    inspect_file,
    inspect_source,
    local_nl_to_dsl,
    nl_to_dsl,
    pcb_state,
    resolve_source,
    schematic_state,
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


PCB_RJ45 = """(kicad_pcb (version 20221018) (generator pcbnew)
  (net 0 "")
  (net 1 "GND")
  (net 2 "ENC_A")
  (net 3 "ENC_B")
  (net 4 "ENC_SW")
  (footprint "local:RJ45_SMD" (layer "B.Cu")
    (tstamp 140e85f0-ef55-4c14-a0bd-8fb6aa1af1cb)
    (at 237.600 92.000)
    (fp_text reference "J1" (at 0 -9.35) (layer "B.SilkS"))
    (fp_text value "RJ45 8P8C" (at 0 9.35) (layer "B.SilkS"))
    (pad "1" smd rect (at -8.4 -5.25) (size 1 1) (layers "B.Cu") (net 4 "ENC_SW"))
    (pad "2" smd rect (at -8.4 -3.75) (size 1 1) (layers "B.Cu") (net 1 "GND"))
    (pad "3" smd rect (at -8.4 -2.25) (size 1 1) (layers "B.Cu") (net 3 "ENC_B"))
    (pad "4" smd rect (at -8.4 -0.75) (size 1 1) (layers "B.Cu") (net 1 "GND"))
    (pad "5" smd rect (at -8.4 0.75) (size 1 1) (layers "B.Cu") (net 2 "ENC_A"))
    (pad "6" smd rect (at -8.4 2.25) (size 1 1) (layers "B.Cu") (net 1 "GND"))
    (pad "7" smd rect (at -8.4 3.75) (size 1 1) (layers "B.Cu"))
    (pad "8" smd rect (at -8.4 5.25) (size 1 1) (layers "B.Cu"))
  )
  (footprint "local:RP2040-Zero" (layer "B.Cu")
    (tstamp a2408f60-4982-46c0-80d3-37aeb9244d09)
    (at 111.750 92.000)
    (fp_text reference "U1" (at 0 0) (layer "B.SilkS"))
    (fp_text value "RP2040-Zero" (at 0 2) (layer "B.SilkS"))
    (pad "5V" smd rect (at -10.16 -8) (size 1.2 2) (layers "B.Cu"))
  )
  (gr_line (start 100.00 60.00) (end 248.00 60.00) (layer "Edge.Cuts"))
  (gr_line (start 248.00 60.00) (end 248.00 124.00) (layer "Edge.Cuts"))
  (gr_line (start 248.00 124.00) (end 100.00 124.00) (layer "Edge.Cuts"))
  (gr_line (start 100.00 124.00) (end 100.00 60.00) (layer "Edge.Cuts"))
  (segment (start 140.000 85.000) (end 216.000 85.000) (width 0.35) (layer "B.Cu") (net 4))
  (segment (start 216.000 85.000) (end 216.000 86.750) (width 0.35) (layer "B.Cu") (net 4))
  (segment (start 216.000 86.750) (end 229.200 86.750) (width 0.35) (layer "B.Cu") (net 4))
  (segment (start 122.500 92.000) (end 218.000 92.000) (width 0.35) (layer "B.Cu") (net 3))
  (segment (start 218.000 92.000) (end 218.000 89.750) (width 0.35) (layer "B.Cu") (net 3))
  (segment (start 218.000 89.750) (end 229.200 89.750) (width 0.35) (layer "B.Cu") (net 3))
  (segment (start 140.000 99.000) (end 220.000 99.000) (width 0.35) (layer "B.Cu") (net 2))
  (segment (start 220.000 99.000) (end 220.000 92.750) (width 0.35) (layer "B.Cu") (net 2))
  (segment (start 220.000 92.750) (end 229.200 92.750) (width 0.35) (layer "B.Cu") (net 2))
)\n"""


def test_sch2dsl_reads_only_placed_symbols() -> None:
    document = inspect_source(SCH, "panel.kicad_sch")

    assert document.source.kind == "schematic"
    assert document.source.kicad_version == 20211123
    assert len(document.items) == 1
    assert document.items[0].reference == "R1"
    assert document.items[0].position.rotation == 90


def test_schematic_state_explains_pcb_sync_and_netgraph_limits() -> None:
    schematic = inspect_source(SCH, "panel.kicad_sch")
    board = inspect_source(PCB.replace('reference "R1"', 'reference "R2"'), "panel.kicad_pcb")

    state = schematic_state(schematic, board)

    assert state["status"] == "requires_follow_up"
    assert state["codes"] == ["EDA-SCH-PCB-SYNC-001", "EDA-SCH-NETGRAPH-001"]
    assert state["summary"]["pcb_only_references"] == ["R2"]
    assert state["summary"]["schematic_only_references"] == ["R1"]


def test_pcb_state_turns_drc_categories_into_safe_repair_draft() -> None:
    state = pcb_state(
        inspect_source(PCB, "panel.kicad_pcb"),
        {
            "violations": 3,
            "unconnected": 2,
            "categories": {"clearance": 1, "unconnected_items": 2, "silk_over_copper": 3},
            "details": {"clearance": {"samples": ["@(1, 2): track and pad"]}},
        },
    )

    assert state["status"] == "blocked"
    assert state["codes"] == [
        "EDA-PCB-CLEARANCE-001",
        "EDA-PCB-SILK-001",
        "EDA-PCB-UNCONNECTED-001",
    ]
    assert state["findings"][0]["samples"] == ["@(1, 2): track and pad"]
    assert state["draft"]["status"] == "draft"
    assert state["draft"]["requires_approval"] is True


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


def test_subllm_repairs_a_hallucinated_uuid_for_a_known_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = inspect_source(PCB, "panel.kicad_pcb")
    expected = local_nl_to_dsl("przesuń R1 do x=120 y=75", document)
    hallucinated = expected.model_copy(
        update={
            "operations": [
                expected.operations[0].model_copy(
                    update={
                        "target": EdaTarget(
                            uuid="11111111-1111-1111-1111-111111111111", reference="R1"
                        )
                    }
                )
            ]
        }
    )

    class Route:
        provider = "zai"
        model = "glm-5.3"
        transport = "openai-compatible"

        @staticmethod
        def litellm_kwargs():
            return {"model": "zai/glm-5.3", "api_key": "test-secret"}

    def completion(**_kwargs):
        message = SimpleNamespace(content=hallucinated.model_dump_json())
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

    result, mode = nl_to_dsl("przesuń R1 do x=120 y=75", document, settings)

    assert mode == "subllm:zai/glm-5.3:target-repaired"
    assert result.operations[0].target.uuid == document.items[0].uuid
    assert result.operations[0].target.reference == "R1"


def test_subllm_invalid_schema_uses_safe_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    document = inspect_source(PCB, "panel.kicad_pcb")

    class Route:
        provider = "zai"
        model = "glm-5.3"
        transport = "openai-compatible"

        @staticmethod
        def litellm_kwargs():
            return {"model": "zai/glm-5.3", "api_key": "test-secret"}

    def completion(**_kwargs):
        message = SimpleNamespace(content="I cannot produce the requested JSON.")
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

    result, mode = nl_to_dsl("przesuń R1 do x=120 y=75", document, settings)

    assert mode == "local-fallback:subllm:zai/glm-5.3:ValidationError"
    assert result.operations[0].target.uuid == document.items[0].uuid
    assert result.operations[0].x == 120
    assert result.operations[0].y == 75


def test_subllm_rejects_a_noop_plan_for_a_connectivity_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = inspect_source(PCB, "panel.kicad_pcb")
    noop = EdaChangeDocument(
        source=document.source,
        operations=[
            MoveOperation(
                op="move",
                entity="footprint",
                target=EdaTarget(uuid=document.items[0].uuid, reference="R1"),
                x=document.items[0].position.x,
                y=document.items[0].position.y,
                rotation=document.items[0].position.rotation,
            )
        ],
    )

    class Route:
        provider = "zai"
        model = "glm-5.3"
        transport = "openai-compatible"

        @staticmethod
        def litellm_kwargs():
            return {"model": "zai/glm-5.3", "api_key": "test-secret"}

    def completion(**_kwargs):
        message = SimpleNamespace(content=noop.model_dump_json())
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

    with pytest.raises(KicadDslError, match="no-op plan"):
        nl_to_dsl("przesuń R1 do x=100 y=50", document, settings)


def test_nl_to_dsl_compiles_and_applies_rj45_connectivity_without_llm() -> None:
    document = inspect_source(PCB_RJ45, "panel.kicad_pcb")
    prompt = "złącze RJ45 ma mase na pinach 1,3,5 a sygnaly na 2,4,6 i plus zaislania na 7 i 8"

    change, mode = nl_to_dsl(prompt, document, SimpleNamespace())
    candidate, repair = apply_changes_with_repair(PCB_RJ45, change)
    updated = inspect_source(candidate, "panel.kicad_pcb")
    pads = {pad.number: pad.net for pad in updated.items[0].pads}

    assert mode == "deterministic:connectivity"
    assert len(change.operations) == 9
    # Signals follow the copper already routed to pads 1/3/5, so repinning is a
    # parallel 1.5 mm slide instead of three crossing tracks.
    assert pads == {
        "1": "GND",
        "2": "ENC_SW",
        "3": "GND",
        "4": "ENC_B",
        "5": "GND",
        "6": "ENC_A",
        "7": "+5V",
        "8": "+5V",
    }
    u1 = next(item for item in updated.items if item.reference == "U1")
    assert {pad.number: pad.net for pad in u1.pads}["5V"] == "+5V"
    assert [(net.code, net.name) for net in updated.nets][-1] == (5, "+5V")
    assert change_validation(change, repair)["codes"] == ["EDA_DRC_NOT_RUN"]
    assert change_validation(change)["codes"] == ["EDA_ROUTING_REQUIRED", "EDA_DRC_NOT_RUN"]
    schematic_change = change.model_copy(
        update={"source": change.source.model_copy(update={"kind": "schematic"})}
    )
    assert change_validation(schematic_change)["codes"] == ["EDA_CONNECTIVITY_NOT_RUN"]


def test_repinning_slides_the_stub_and_leaves_the_feeder_alone() -> None:
    document = inspect_source(PCB_RJ45, "panel.kicad_pcb")
    prompt = "złącze RJ45 ma mase na pinach 1,3,5 a sygnaly na 2,4,6 i plus zaislania na 7 i 8"

    change, _mode = nl_to_dsl(prompt, document, SimpleNamespace())
    candidate, repair = apply_changes_with_repair(PCB_RJ45, change)

    assert [entry["to_pad"] for entry in repair["retargeted"]] == ["J1.2", "J1.4", "J1.6"]
    # The stub ends on the new pad and its corner moved with it...
    assert "(start 216 88.25) (end 229.2 88.25)" in candidate
    assert "(start 216 85) (end 216 88.25)" in candidate
    # ...while the long feeder that runs parallel to the shift stays put.
    assert "(start 140.000 85.000) (end 216.000 85.000)" in candidate
    assert "86.750" not in candidate


def test_a_new_power_net_is_routed_between_its_pads() -> None:
    document = inspect_source(PCB_RJ45, "panel.kicad_pcb")
    prompt = "złącze RJ45 ma mase na pinach 1,3,5 a sygnaly na 2,4,6 i plus zaislania na 7 i 8"

    change, _mode = nl_to_dsl(prompt, document, SimpleNamespace())
    candidate, repair = apply_changes_with_repair(PCB_RJ45, change)
    routed = repair["routed"][0]

    assert routed["net"] == "+5V"
    assert routed["layer"] == "B.Cu"
    assert sorted(routed["pads"]) == ["J1.7", "J1.8", "U1.5V"]
    # A rectilinear tree over three pads never needs more than five segments.
    assert 0 < routed["segments"] <= 5
    assert candidate.count('(layer "B.Cu") (net 5)') == routed["segments"]


def test_routing_a_new_net_needs_a_board_outline() -> None:
    without_outline = "\n".join(
        line for line in PCB_RJ45.splitlines() if "Edge.Cuts" not in line
    ) + "\n"
    document = inspect_source(without_outline, "panel.kicad_pcb")
    prompt = "złącze RJ45 ma mase na pinach 1,3,5 a sygnaly na 2,4,6 i plus zaislania na 7 i 8"

    change, _mode = nl_to_dsl(prompt, document, SimpleNamespace())
    with pytest.raises(KicadDslError, match="Edge.Cuts"):
        apply_changes(without_outline, change)


def test_subllm_rejects_an_unknown_component_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = inspect_source(PCB, "panel.kicad_pcb")
    expected = local_nl_to_dsl("przesuń R1 do x=120 y=75", document)
    invalid = expected.model_copy(
        update={
            "operations": [
                expected.operations[0].model_copy(
                    update={
                        "target": EdaTarget(
                            uuid="11111111-1111-1111-1111-111111111111", reference="R2"
                        )
                    }
                )
            ]
        }
    )

    class Route:
        provider = "zai"
        model = "glm-5.3"
        transport = "openai-compatible"

        @staticmethod
        def litellm_kwargs():
            return {"model": "zai/glm-5.3", "api_key": "test-secret"}

    def completion(**_kwargs):
        message = SimpleNamespace(content=invalid.model_dump_json())
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

    with pytest.raises(KicadDslError, match="outside the supplied document"):
        nl_to_dsl("przesuń R1 do x=120 y=75", document, settings)


def test_a_rejected_llm_answer_keeps_what_was_rejected(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    document = inspect_source(SCH, "panel.kicad_sch")
    monkeypatch.setattr(
        kicad_dsl, "eda_litellm_route",
        lambda settings: ({"model": "zai/glm-5.3"}, "zai/glm-5.3", False),
    )
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(
        completion=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"operations": "nie lista"}'))]),
    ))

    rejection: dict[str, object] = {}
    _change, mode = kicad_dsl.nl_to_dsl(
        "ustaw wartość R1 na 10k", document, SimpleNamespace(), diagnostics=rejection
    )

    # "ValidationError" alone says nothing about what to fix in the prompt.
    assert mode.startswith("local-fallback:")
    assert rejection["stage"] == "schema"
    assert rejection["response"] == '{"operations": "nie lista"}'
    assert "operations" in rejection["error"]


def test_callers_that_do_not_ask_for_diagnostics_are_unaffected(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    document = inspect_source(SCH, "panel.kicad_sch")
    monkeypatch.setattr(kicad_dsl, "eda_litellm_route", lambda settings: None)

    change, mode = kicad_dsl.nl_to_dsl("ustaw wartość R1 na 10k", document, SimpleNamespace())

    assert mode == "local"
    assert change.operations


def test_a_routing_request_is_refused_before_the_model_is_asked(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    document = inspect_source(PCB, "panel.kicad_pcb")
    monkeypatch.setattr(
        kicad_dsl, "eda_litellm_route",
        lambda settings: pytest.fail("routing is not expressible in DSL v1; do not spend a call"),
    )

    with pytest.raises(KicadDslError, match="DSL v1"):
        kicad_dsl.nl_to_dsl(
            "nie przeprowadzaj niebieskich linii pod switchami tylko na około",
            document, SimpleNamespace(),
        )


def test_a_pad_net_request_is_not_mistaken_for_routing(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    document = inspect_source(PCB_RJ45, "panel.kicad_pcb")
    monkeypatch.setattr(kicad_dsl, "eda_litellm_route", lambda settings: None)

    _change, mode = kicad_dsl.nl_to_dsl(
        "złącze RJ45 ma mase na pinach 1,3,5 a sygnaly na 2,4,6 i plus zaislania na 7 i 8",
        document, SimpleNamespace(),
    )

    # Repinning does move copper, but through the deterministic repair - the
    # guard must not swallow it.
    assert mode == "deterministic:connectivity"


def test_a_pad_prompt_the_compiler_cannot_read_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    document = inspect_source(PCB_RJ45, "panel.kicad_pcb")
    asked: list[str] = []

    def route(settings):
        asked.append("route")
        return None

    monkeypatch.setattr(kicad_dsl, "eda_litellm_route", route)

    # Mentions a pad, so the classifier claims it, but it is not the
    # three-group sentence the deterministic compiler knows. It used to die
    # with an error naming R1 and SW1 without the model ever being asked.
    with pytest.raises(KicadDslError):
        kicad_dsl.nl_to_dsl("przenieś sygnał z pada 1 na inne wyprowadzenie", document, SimpleNamespace())

    assert asked == ["route"]


def test_the_sentence_the_compiler_knows_still_never_costs_a_call(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    document = inspect_source(PCB_RJ45, "panel.kicad_pcb")
    monkeypatch.setattr(
        kicad_dsl, "eda_litellm_route",
        lambda settings: pytest.fail("the deterministic path must answer this one"),
    )

    _change, mode = kicad_dsl.nl_to_dsl(
        "złącze RJ45 ma mase na pinach 1,3,5 a sygnaly na 2,4,6 i plus zaislania na 7 i 8",
        document, SimpleNamespace(),
    )

    assert mode == "deterministic:connectivity"
