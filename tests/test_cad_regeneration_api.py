from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_apply_and_undo_regenerate_visible_artifacts_in_isolated_process(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    code = r'''
import hashlib
import json
import time
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

    logs = client.get('/api/v1/projects/demo-rpi5/logs.dsl?limit=100').text
    assert 'CODE "CAD_REGENERATION_QUEUED"' in logs
    assert 'CODE "CAD_REGENERATION_COMPLETED"' in logs
'''
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
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
