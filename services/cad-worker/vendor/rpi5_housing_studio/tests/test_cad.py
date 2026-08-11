from pathlib import Path

import trimesh

from housing_studio.cad3d import export_part, make_models, shape_stats
from housing_studio.models import default_project_config


def test_default_cad_solids_and_exports(tmp_path: Path) -> None:
    models = make_models(default_project_config())
    base_stats = shape_stats(models.base)
    lid_stats = shape_stats(models.lid)
    assert base_stats["volume_mm3"] > 10_000
    assert lid_stats["volume_mm3"] > 10_000

    base_step = tmp_path / "base.step"
    base_stl = tmp_path / "base.stl"
    export_part(models.base, base_step, base_stl)
    assert base_step.stat().st_size > 1_000
    assert base_stl.stat().st_size > 1_000

    lid_stl = tmp_path / "lid.stl"
    export_part(models.lid, stl_path=lid_stl)
    for path in (base_stl, lid_stl):
        mesh = trimesh.load_mesh(path, force="mesh")
        assert mesh.is_watertight
        assert mesh.is_winding_consistent
