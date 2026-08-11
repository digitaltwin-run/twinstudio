from housing_studio.llm_config import fallback_interpret
from housing_studio.models import default_project_config


def test_fallback_updates_dimensions_and_layers() -> None:
    current = default_project_config()
    result = fallback_interpret(
        "Ustaw grubość ścian na 2.4 mm, kąt otwarcia 200 stopni i wyłącz drugi wariant PCB position B",
        current,
    )
    assert result.config.dimensions.wall_thickness == 2.4
    assert result.config.hinge.opening_angle_deg == 200.0
    assert result.config.feature_layers.pcb_mount_b.enabled is False
    assert result.mode == "fallback"


def test_fallback_understands_bundled_polish_example() -> None:
    current = default_project_config()
    prompt = (
        "Ustaw grubość wszystkich ścian na 2 mm. Zachowaj szerokość 79 mm, "
        "wysokość podstawy 25 mm i wysokość całkowitą 40 mm. Włącz oba zestawy "
        "słupków Raspberry Pi. Zawias ma otwierać się do 195 stopni. "
        "W dokumentacji 2D zachowaj warstwy visible edges, hidden edges, centerlines, "
        "dimensions i PCB reference oraz widoki front, top i side."
    )
    result = fallback_interpret(prompt, current)
    assert result.config.dimensions.wall_thickness == 2.0
    assert result.config.dimensions.external_width == 79.0
    assert result.config.dimensions.base_height == 25.0
    assert result.config.dimensions.total_height == 40.0
    assert result.config.hinge.opening_angle_deg == 195.0
    assert result.config.feature_layers.pcb_mount_a.enabled is True
    assert result.config.feature_layers.pcb_mount_b.enabled is True
    assert result.config.drawing.include_front is True
    assert result.config.drawing.include_top is True
    assert result.config.drawing.include_side is True
    assert result.config.drawing.layers.visible_edges.enabled is True
    assert result.config.drawing.layers.hidden_edges.enabled is True
    assert result.config.drawing.layers.centerlines.enabled is True
    assert result.config.drawing.layers.dimensions.enabled is True
    assert result.config.drawing.layers.pcb_reference.enabled is True


def test_fallback_understands_detailed_manufacturing_values() -> None:
    current = default_project_config()
    result = fallback_interpret(
        "Ustaw średnicę zewnętrzną słupków 6.5 mm, średnicę otworu słupków 1.2 mm, "
        "kąt ścięcia 45 stopni, górna powierzchnia dodatkowych punktów 14 mm i bez OBJ.",
        current,
    )
    assert result.config.board.standoff.outer_diameter == 6.5
    assert result.config.board.standoff.pilot_hole_diameter == 1.2
    assert result.config.hinge.base_front_chamfer_angle_deg == 45.0
    assert result.config.auxiliary_lid_bosses.top_z_from_base_mating_plane == 14.0
    assert result.config.artifacts.export_obj is False
    assert any(change["path"] == "board.standoff.outer_diameter" for change in result.changes)

def test_fallback_understands_explicit_export_commands() -> None:
    current = default_project_config()
    result = fallback_interpret(
        "Ustaw grubość ścian na 2.2 mm i wyłącz eksport OBJ, ale włącz eksport PDF.",
        current,
    )
    assert result.config.dimensions.wall_thickness == 2.2
    assert result.config.artifacts.export_obj is False
    assert result.config.artifacts.export_pdf is True
    assert any(change["path"] == "artifacts.export_obj" for change in result.changes)

