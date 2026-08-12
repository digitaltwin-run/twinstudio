from twinstudio.simulations import (
    evaluate_human_scenario,
    mechanical_rule_checks,
    simulate_power,
    simulate_thermal,
)


def test_power_and_thermal_models(project_snapshot) -> None:
    power = simulate_power(project_snapshot.power_model)
    assert power["cases"]
    assert power["peak_current_a"] > 0
    assert power["minimum_board_voltage_v"] <= project_snapshot.power_model.supply_voltage_v

    rpi_uri = "poa://demo/demo-rpi5@main/purchased-component/raspberry-pi-5"
    result = simulate_thermal(project_snapshot.thermal_model, {rpi_uri: 10.0}, duration_s=20, sample_every_s=5)
    assert result["samples"]
    assert result["peaks_c"][rpi_uri] >= 25


def test_human_and_mechanical_checks(project_snapshot) -> None:
    evaluated = evaluate_human_scenario(project_snapshot.human_scenarios[0])
    assert evaluated["step_count"] > 0
    checks = mechanical_rule_checks(project_snapshot.model_dump(mode="json"))
    assert isinstance(checks, list)
