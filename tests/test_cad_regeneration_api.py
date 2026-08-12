from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_apply_and_undo_regenerate_visible_artifacts_in_isolated_process(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    code = r"""
import hashlib
import json
import os
import time
from pathlib import Path
from fastapi.testclient import TestClient
from twinstudio.api import app

def wait_for_generation(client, job_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        events = client.get('/api/v1/projects/demo-rpi5/events').json()
        match = next((
            item for item in reversed(events)
            if item['event_type'] in {'GenerationCompleted', 'GenerationFailed'}
            and item['data'].get('job_id') == job_id
        ), None)
        if match:
            assert match['event_type'] == 'GenerationCompleted', match
            assert match['data']['status'] == 'completed', match
            return match
        time.sleep(0.1)
    raise AssertionError(f'CAD generation {job_id} did not complete')

with TestClient(app) as client:
    selection = json.load(open('examples/rpi5-camera3/selections/example-selection.json'))
    selection.update({
        'selection_id': 'cad-regeneration-selection',
        'uri': 'poa://demo/demo-rpi5@main/region/cad-regeneration-selection',
        'source_view': '2d',
        'tool': 'rectangle',
        'ray_hits': [],
        'world_aabb': None,
        'camera': None,
        'projection_entity_ids': ['front.base.outer-wall'],
    })
    planned = client.post(
        '/api/v1/projects/demo-rpi5/change-plans',
        json={'prompt': 'ustaw grubość ścian na 3 mm', 'selection': selection},
    )
    assert planned.status_code == 200, planned.text
    plan_id = planned.json()['plan']['plan_id']
    applied = client.post(f'/api/v1/projects/demo-rpi5/change-plans/{plan_id}/apply', json={})
    assert applied.status_code == 200, applied.text
    assert applied.json()['generation']['status'] == 'queued'
    apply_job = applied.json()['generation']['job_id']
    applied_event = next(item for item in applied.json()['events'] if item['event_type'] == 'ChangeApplied')
    completed = wait_for_generation(client, apply_job)
    assert len(completed['data']['artifacts']) == 5

    changed = client.get('/api/v1/projects/demo-rpi5').json()['project']
    base_uri = 'poa://demo/demo-rpi5@main/part/base'
    base_artifact_uri = 'poa://demo/demo-rpi5@main/artifact/base-stl'
    assert changed['objects'][base_uri]['parameters']['wall_thickness']['value'] == 3
    assert changed['artifacts'][base_artifact_uri]['metadata']['cad_job_id'] == apply_job
    changed_bytes = client.get('/api/v1/projects/demo-rpi5/artifacts/base-stl').content
    changed_hash = hashlib.sha256(changed_bytes).hexdigest()
    assert changed_hash == changed['artifacts'][base_artifact_uri]['sha256']

    undone = client.post(
        f"/api/v1/projects/demo-rpi5/change-history/{applied_event['event_id']}/undo"
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()['generation']['status'] == 'queued'
    undo_job = undone.json()['generation']['job_id']
    assert undo_job != apply_job
    wait_for_generation(client, undo_job)

    restored = client.get('/api/v1/projects/demo-rpi5').json()['project']
    assert restored['objects'][base_uri]['parameters']['wall_thickness']['value'] == 2
    assert restored['artifacts'][base_artifact_uri]['metadata']['cad_job_id'] == undo_job
    restored_bytes = client.get('/api/v1/projects/demo-rpi5/artifacts/base-stl').content
    restored_hash = hashlib.sha256(restored_bytes).hexdigest()
    assert restored_hash == restored['artifacts'][base_artifact_uri]['sha256']
    assert restored_hash != changed_hash

    height_plan = client.post(
        '/api/v1/projects/demo-rpi5/change-plans',
        json={'prompt': 'zmniejsz wysokość podstawy o 4 mm', 'selection': selection},
    )
    assert height_plan.status_code == 200, height_plan.text
    height_plan_id = height_plan.json()['plan']['plan_id']
    height_applied = client.post(
        f'/api/v1/projects/demo-rpi5/change-plans/{height_plan_id}/apply',
        json={},
    )
    assert height_applied.status_code == 200, height_applied.text
    height_generation = height_applied.json()['generation']
    assert height_generation['dimension_overrides'] == {'lid_height_mm': 15.0}
    height_job = height_generation['job_id']
    wait_for_generation(client, height_job)

    resized = client.get('/api/v1/projects/demo-rpi5').json()['project']
    lid_uri = 'poa://demo/demo-rpi5@main/part/lid'
    assert resized['objects'][base_uri]['parameters']['height']['value'] == 21
    assert resized['objects'][lid_uri]['parameters']['total_height']['value'] == 40
    cad_dimensions = resized['objects'][lid_uri]['metadata']['cad_dimensions']
    assert cad_dimensions == {
        'base_height_mm': 21.0,
        'lid_height_mm': 15.0,
        'total_height_mm': 36.0,
        'source_total_height_mm': 40.0,
    }
    config_path = Path(os.environ['TWINSTUDIO_DATA_DIR']) / 'cad-jobs' / height_job / 'project_config.json'
    generated_config = json.loads(config_path.read_text())
    assert generated_config['dimensions']['base_height'] == 21
    assert generated_config['dimensions']['total_height'] == 36

    height_event = next(
        item for item in height_applied.json()['events'] if item['event_type'] == 'ChangeApplied'
    )
    height_undo = client.post(
        f"/api/v1/projects/demo-rpi5/change-history/{height_event['event_id']}/undo"
    )
    assert height_undo.status_code == 200, height_undo.text
    height_undo_job = height_undo.json()['generation']['job_id']
    wait_for_generation(client, height_undo_job)
    height_restored = client.get('/api/v1/projects/demo-rpi5').json()['project']
    restored_dimensions = height_restored['objects'][lid_uri]['metadata']['cad_dimensions']
    assert height_restored['objects'][base_uri]['parameters']['height']['value'] == 25
    assert restored_dimensions['base_height_mm'] == 25
    assert restored_dimensions['lid_height_mm'] == 15
    assert restored_dimensions['total_height_mm'] == 40

    logs = client.get('/api/v1/projects/demo-rpi5/logs.dsl?limit=100').text
    assert 'CODE "CAD_REGENERATION_QUEUED"' in logs
    assert 'CODE "CAD_REGENERATION_COMPLETED"' in logs
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(root / "src"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'cad-api.db'}",
            "TWINSTUDIO_DATA_DIR": str(tmp_path / "data"),
            "DEV_AUTH_BYPASS": "true",
            "MQTT_ENABLED": "false",
            "TWINSTUDIO_CAD_REGEN_ENABLED": "true",
            "LITELLM_MODEL": "",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=100,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
