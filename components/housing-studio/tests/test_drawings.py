from pathlib import Path

import ezdxf

from housing_studio.draw2d import export_all_2d
from housing_studio.models import default_project_config


def test_layered_dxf_svg_pdf_outputs(tmp_path: Path) -> None:
    config = default_project_config()
    outputs = export_all_2d(config, tmp_path)
    assert len(outputs) == 15

    dxf_path = tmp_path / "base" / "base_views.dxf"
    doc = ezdxf.readfile(dxf_path)
    expected = {
        "VISIBLE_EDGES",
        "HIDDEN_EDGES",
        "CENTERLINES",
        "DIMENSIONS",
        "NOTES",
        "PCB_REFERENCE",
        "DATUMS",
    }
    assert expected.issubset({layer.dxf.name for layer in doc.layers})
    assert (tmp_path / "lid" / "lid_side.svg").stat().st_size > 500
    assert (tmp_path / "assembly" / "assembly_drawing.pdf").stat().st_size > 1_000


def test_view_flags_control_exports(tmp_path: Path) -> None:
    config = default_project_config()
    config.drawing.include_top = False
    outputs = export_all_2d(config, tmp_path)
    assert len(outputs) == 12
    assert not (tmp_path / "base" / "base_top.svg").exists()
    assert (tmp_path / "base" / "base_front.svg").exists()
    assert (tmp_path / "base" / "base_side.svg").exists()


def test_svg_keeps_disabled_layers_for_interactive_preview(tmp_path: Path) -> None:
    config = default_project_config()
    config.drawing.layers.hidden_edges.enabled = False
    export_all_2d(config, tmp_path)
    source = (tmp_path / "base" / "base_front.svg").read_text(encoding="utf-8")
    assert 'data-layer-key="hidden_edges"' in source
    assembly_front = (tmp_path / "assembly" / "assembly_front.svg").read_text(encoding="utf-8")
    assert 'data-object-key="part/base"' in assembly_front
    assert 'data-projection-entity="front.base.outer-wall"' in assembly_front
    assert 'data-selection-bbox=' in assembly_front
    assert 'data-default-enabled="false"' in source
    assert 'style="display:none"' in source
