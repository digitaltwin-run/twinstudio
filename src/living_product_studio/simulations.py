from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

from living_product_studio.domain import HumanUseScenario, PowerModel, ThermalModel


@dataclass(slots=True)
class PowerCaseResult:
    name: str
    current_a: float
    board_voltage_v: float
    voltage_drop_v: float
    load_power_w: float
    distribution_loss_w: float
    current_limit_exceeded: bool
    brownout_risk: bool
    duration_s: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_power(model: PowerModel) -> dict[str, Any]:
    resistance = model.cable_resistance_ohm + model.connector_resistance_ohm + model.board_path_resistance_ohm
    cases: list[PowerCaseResult] = []
    worst_voltage = model.supply_voltage_v
    peak_current = 0.0
    energy_j = 0.0
    for load in model.load_cases:
        drop = load.current_a * resistance
        board_voltage = max(0.0, model.supply_voltage_v - drop)
        power = board_voltage * load.current_a
        loss = load.current_a * load.current_a * resistance
        result = PowerCaseResult(
            name=load.name,
            current_a=load.current_a,
            board_voltage_v=round(board_voltage, 4),
            voltage_drop_v=round(drop, 4),
            load_power_w=round(power, 4),
            distribution_loss_w=round(loss, 4),
            current_limit_exceeded=load.current_a > model.supply_current_limit_a,
            brownout_risk=board_voltage < model.brownout_voltage_v,
            duration_s=load.duration_s,
        )
        cases.append(result)
        worst_voltage = min(worst_voltage, board_voltage)
        peak_current = max(peak_current, load.current_a)
        energy_j += (power + loss) * load.duration_s
    return {
        "model": "dc_lumped_resistance_v1",
        "total_series_resistance_ohm": round(resistance, 5),
        "peak_current_a": round(peak_current, 4),
        "minimum_board_voltage_v": round(worst_voltage, 4),
        "total_scenario_energy_j": round(energy_j, 3),
        "cases": [item.to_dict() for item in cases],
        "limitations": [
            "No transient regulator dynamics or USB-C negotiation model.",
            "Resistance values must be measured for the actual cable, connector, and board path.",
        ],
    }


def simulate_thermal(
    model: ThermalModel,
    power_by_uri_w: dict[str, float],
    *,
    duration_s: float = 600.0,
    sample_every_s: float = 10.0,
) -> dict[str, Any]:
    if duration_s <= 0 or sample_every_s <= 0:
        raise ValueError("Simulation duration and sample interval must be positive")
    state = {node.uri: node.initial_c for node in model.nodes}
    samples: list[dict[str, Any]] = []
    elapsed = 0.0
    next_sample = 0.0
    while elapsed <= duration_s + 1e-9:
        if elapsed + 1e-9 >= next_sample:
            samples.append(
                {
                    "time_s": round(elapsed, 3),
                    "temperature_c": {uri: round(value, 3) for uri, value in state.items()},
                }
            )
            next_sample += sample_every_s
        updated = dict(state)
        for node in model.nodes:
            temperature = state[node.uri]
            power = float(power_by_uri_w.get(node.uri, 0.0))
            heat_out = (temperature - node.ambient_c) / node.thermal_resistance_c_per_w
            derivative = (power - heat_out) / node.thermal_capacitance_j_per_c
            candidate = temperature + derivative * model.timestep_s
            if not isfinite(candidate):
                raise ValueError(f"Thermal model diverged for {node.uri}")
            updated[node.uri] = candidate
        state = updated
        elapsed += model.timestep_s
    peaks = {
        node.uri: max(sample["temperature_c"][node.uri] for sample in samples)
        for node in model.nodes
    }
    return {
        "model": "lumped_thermal_rc_v1",
        "duration_s": duration_s,
        "timestep_s": model.timestep_s,
        "peaks_c": peaks,
        "samples": samples,
        "limitations": [
            "This is a lumped RC estimate, not CFD or a validated enclosure airflow model.",
            "Thermal resistance and capacitance require calibration against measurements.",
        ],
    }


def evaluate_human_scenario(scenario: HumanUseScenario) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    total_duration = 0.0
    for index, step in enumerate(scenario.steps, start=1):
        if not step.success_criteria:
            issues.append({"step_id": step.step_id, "severity": "medium", "issue": "No success criterion."})
        if not step.possible_errors:
            issues.append({"step_id": step.step_id, "severity": "low", "issue": "No misuse/error case recorded."})
        if step.expected_force_n is not None and step.expected_force_n > 80:
            issues.append(
                {"step_id": step.step_id, "severity": "high", "issue": "Expected manual force exceeds 80 N review threshold."}
            )
        total_duration += step.expected_duration_s or 0.0
        if index > 1 and not step.preconditions:
            issues.append(
                {"step_id": step.step_id, "severity": "low", "issue": "Step has no explicit preconditions."}
            )
    return {
        "scenario_uri": scenario.uri,
        "name": scenario.name,
        "step_count": len(scenario.steps),
        "estimated_duration_s": round(total_duration, 2),
        "issues": issues,
        "passed": not any(item["severity"] == "high" for item in issues),
        "limitations": [
            "The MVP checks task logic and declared forces; it does not perform biomechanical avatar simulation.",
            "A physical usability study is required for validation.",
        ],
    }


def mechanical_rule_checks(project: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for uri, node in project.get("objects", {}).items():
        parameters = node.get("parameters", {})
        wall = parameters.get("wall_thickness", {}).get("value")
        process = node.get("manufacturing", {}).get("process")
        if process == "fdm_print" and isinstance(wall, (int, float)) and wall < 1.2:
            checks.append(
                {
                    "target_uri": uri,
                    "severity": "high",
                    "rule": "fdm.minimum_wall",
                    "message": f"Wall thickness {wall} mm is below the project FDM review threshold of 1.2 mm.",
                }
            )
        opening = parameters.get("hinge_opening_angle_deg", {}).get("value")
        if isinstance(opening, (int, float)) and opening < 190:
            checks.append(
                {
                    "target_uri": uri,
                    "severity": "medium",
                    "rule": "hinge.minimum_opening",
                    "message": "Hinge opening is below the specified >190 degree requirement.",
                }
            )
    return checks
