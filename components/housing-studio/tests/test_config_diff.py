from housing_studio.config_diff import diff_configs
from housing_studio.models import default_project_config


def test_config_diff_reports_leaf_paths() -> None:
    before = default_project_config()
    after = before.model_copy(deep=True)
    after.dimensions.wall_thickness = 2.4
    after.feature_layers.pcb_mount_b.enabled = False

    changes = diff_configs(before, after)
    by_path = {change.path: change for change in changes}

    assert by_path["dimensions.wall_thickness"].before == 2.0
    assert by_path["dimensions.wall_thickness"].after == 2.4
    assert by_path["feature_layers.pcb_mount_b.enabled"].after is False
