from housing_studio.models import default_project_config
from housing_studio.validation import board_actual_clearances, collect_warnings, design_metrics


def test_default_dimensions_and_angles() -> None:
    config = default_project_config()
    metrics = design_metrics(config)
    assert metrics["internal_width"] == 75.0
    assert metrics["internal_depth"] == 91.0
    assert metrics["top_depth"] == 80.0
    assert abs(metrics["front_lid_angle_deg"] - 45.0) < 1e-6


def test_position_b_mismatch_is_explicit() -> None:
    config = default_project_config()
    clearances = board_actual_clearances(config, config.board.position_b)
    assert clearances["right"] == 7.5
    assert clearances["left"] == 11.5
    warnings = collect_warnings(config)
    assert any(warning.code == "PCB_B_CLEARANCE_MISMATCH" for warning in warnings)
