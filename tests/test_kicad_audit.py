from __future__ import annotations

from twinstudio.kicad_audit import netlist_state


def _netlist(components, nets, source="panel.kicad_sch"):
    return {"source": source, "components": components, "nets": nets}


HEALTHY = _netlist(
    components=[
        {"reference": "U1", "part": "local:MCU", "pins": [
            {"number": "1", "name": "GND", "type": "power_in"},
            {"number": "2", "name": "VDD", "type": "power_in"},
        ]},
        {"reference": "C1", "part": "local:C", "pins": [
            {"number": "1", "name": "~", "type": "passive"},
            {"number": "2", "name": "~", "type": "passive"},
        ]},
    ],
    nets=[
        {"name": "GND", "nodes": [
            {"reference": "U1", "pin": "1"}, {"reference": "C1", "pin": "2"}]},
        {"name": "+3V3", "nodes": [
            {"reference": "U1", "pin": "2"}, {"reference": "C1", "pin": "1"}]},
    ],
)


def test_a_sound_netlist_reports_no_findings() -> None:
    state = netlist_state(HEALTHY)

    assert state["status"] == "ready"
    assert state["findings"] == []
    assert state["summary"] == {"components": 2, "nets": 2, "nodes": 4, "findings": 0}


def test_a_rail_split_across_two_names_is_an_error() -> None:
    # The classic defect DRC cannot see: both nets are perfectly legal, the
    # part simply never reaches the rail its decoupling sits on.
    split = _netlist(
        components=HEALTHY["components"],
        nets=[
            {"name": "GND", "nodes": [
                {"reference": "U1", "pin": "1"}, {"reference": "C1", "pin": "2"}]},
            {"name": "3V3", "nodes": [{"reference": "U1", "pin": "2"}]},
            {"name": "+3V3", "nodes": [{"reference": "C1", "pin": "1"}]},
        ],
    )

    state = netlist_state(split)
    codes = state["codes"]

    assert state["status"] == "blocked"
    assert "EDA-NET-RAIL-SPLIT-001" in codes
    rail = next(f for f in state["findings"] if f["code"] == "EDA-NET-RAIL-SPLIT-001")
    assert rail["samples"] == ["3V3: +3V3 (1 w.) | 3V3 (1 w.)"]
    # The same defect must also surface as a starved power pin.
    assert "EDA-NET-NO-POWER-001" in codes
    assert "EDA-NET-SINGLE-NODE-001" in codes


def test_a_pin_outside_every_net_is_reported_as_floating() -> None:
    floating = _netlist(
        components=[{"reference": "U1", "part": "local:MCU", "pins": [
            {"number": "1", "name": "GND", "type": "power_in"},
            {"number": "2", "name": "VDD", "type": "power_in"},
            {"number": "3", "name": "IO", "type": "bidirectional"},
        ]}],
        nets=[
            {"name": "GND", "nodes": [{"reference": "U1", "pin": "1"}]},
            {"name": "+3V3", "nodes": [{"reference": "U1", "pin": "2"}]},
        ],
    )

    state = netlist_state(floating)
    pins = next(f for f in state["findings"] if f["code"] == "EDA-NET-FLOATING-PIN-001")

    assert pins["samples"] == ["U1.3 [IO]"]


def test_an_intentional_no_connect_is_not_reported_as_floating() -> None:
    documented = _netlist(
        components=[{"reference": "U1", "part": "local:MCU", "pins": [
            {"number": "1", "name": "GND", "type": "power_in"},
            {"number": "2", "name": "VDD", "type": "power_in"},
            {"number": "3", "name": "IO", "type": "bidirectional"},
        ]}],
        nets=[
            {"name": "GND", "nodes": [{"reference": "U1", "pin": "1"}]},
            {"name": "+3V3", "nodes": [{"reference": "U1", "pin": "2"}]},
        ],
    )
    documented["intentional_no_connect"] = [{
        "name": "unconnected-(U1-Pad3)",
        "nodes": [{"reference": "U1", "pin": "3"}],
    }]

    state = netlist_state(documented)

    assert "EDA-NET-FLOATING-PIN-001" not in state["codes"]


def test_a_part_wired_only_to_itself_is_isolated() -> None:
    isolated = _netlist(
        components=[{"reference": "SW1", "part": "local:SW", "pins": [
            {"number": "1", "name": "A", "type": "passive"},
            {"number": "2", "name": "A", "type": "passive"},
        ]}],
        nets=[{"name": "Net-(SW1-A1)", "nodes": [
            {"reference": "SW1", "pin": "1"}, {"reference": "SW1", "pin": "2"}]}],
    )

    state = netlist_state(isolated)
    part = next(f for f in state["findings"] if f["code"] == "EDA-NET-ISOLATED-PART-001")

    assert part["samples"] == ["SW1 (sieci: Net-(SW1-A1))"]


def test_pcb_pads_are_compared_against_the_schematic_net() -> None:
    pcb = {"pads": [
        {"reference": "U1", "pin": "1", "net": "GND"},
        {"reference": "U1", "pin": "2", "net": "VBUS"},
        {"reference": "R9", "pin": "1", "net": "GND"},
    ]}

    state = netlist_state(HEALTHY, pcb)
    by_code = {f["code"]: f for f in state["findings"]}

    parts = by_code["EDA-NET-DRIFT-PART-001"]
    assert "tylko w schemacie: C1" in parts["samples"]
    assert "tylko w PCB: R9" in parts["samples"]
    # A net under a different name is a naming decision, not a missing part.
    assert by_code["EDA-NET-DRIFT-NAME-001"]["samples"] == ["U1.2: PCB VBUS ≠ schemat +3V3"]


def test_a_different_pin_of_the_same_family_is_not_a_rename() -> None:
    # GP7 against GP2 means the router picked another GPIO for shorter traces.
    # Calling that a naming problem would send the reader to fix the wrong thing.
    netlist = _netlist(
        components=[{"reference": "SW1", "part": "local:SW", "pins": [
            {"number": "1", "name": "A", "type": "passive"}]}],
        nets=[{"name": "GP2", "nodes": [{"reference": "SW1", "pin": "1"}]}],
    )
    pcb = {"pads": [{"reference": "SW1", "pin": "1", "net": "GP7"}]}

    state = netlist_state(netlist, pcb)
    by_code = {f["code"]: f for f in state["findings"]}

    assert by_code["EDA-NET-DRIFT-PINOUT-001"]["samples"] == ["SW1.1: PCB GP7 ≠ schemat GP2"]
    assert "EDA-NET-DRIFT-NAME-001" not in by_code
    # A layout choice is a warning, not a blocker.
    assert by_code["EDA-NET-DRIFT-PINOUT-001"]["severity"] == "WARNING"


def test_spare_pins_are_a_warning_not_an_error() -> None:
    # A dev board's unused GPIO is a note, not a defect; only a starved power
    # pin blocks. Otherwise the audit teaches people to ignore it.
    spare = _netlist(
        components=[{"reference": "U1", "part": "local:MCU", "pins": [
            {"number": "1", "name": "GND", "type": "power_in"},
            {"number": "2", "name": "VDD", "type": "power_in"},
            {"number": "3", "name": "GP9", "type": "bidirectional"},
        ]}],
        nets=[
            {"name": "GND", "nodes": [
                {"reference": "U1", "pin": "1"}, {"reference": "C1", "pin": "2"}]},
            {"name": "+3V3", "nodes": [
                {"reference": "U1", "pin": "2"}, {"reference": "C1", "pin": "1"}]},
            {"name": "GP9", "nodes": [{"reference": "U1", "pin": "3"}]},
        ],
    )

    state = netlist_state(spare)
    single = next(f for f in state["findings"] if f["code"] == "EDA-NET-SINGLE-NODE-001")

    assert single["severity"] == "WARNING"
    assert state["status"] == "ready"


def test_a_node_between_the_logic_thresholds_is_an_error() -> None:
    from twinstudio.kicad_audit import simulation_state

    state = simulation_state({
        "voltages": {"gp10": 0.9851, "+3v3": 3.3},
        "undefined_logic": [{"node": "gp10", "volts": 0.9851}],
        "thresholds": {"low": 0.8, "high": 2.0},
        "skipped_devices": ["U1"],
        "driven_rails": ["+3V3=3.3V"],
    }, "panel.kicad_sch")

    assert state["status"] == "blocked"
    assert state["codes"] == ["EDA-SIM-UNDEFINED-LEVEL-001", "EDA-SIM-NO-MODEL-001"]
    level = state["findings"][0]
    assert level["samples"] == ["gp10 = 0.9851 V"]
    # A modelless part limits the result but does not invalidate it.
    assert state["findings"][1]["severity"] == "WARNING"
    # The fix is a component-value decision, so it stays with a human.
    assert state["draft"]["requires_approval"] is True


def test_clean_levels_leave_the_simulation_ready() -> None:
    from twinstudio.kicad_audit import simulation_state

    state = simulation_state({
        "voltages": {"gp10": 3.3},
        "undefined_logic": [],
        "thresholds": {"low": 0.8, "high": 2.0},
        "skipped_devices": [],
        "driven_rails": ["+3V3=3.3V"],
    })

    assert state["status"] == "ready"
    assert state["findings"] == []
