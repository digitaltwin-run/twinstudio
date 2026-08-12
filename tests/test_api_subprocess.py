from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_primary_api_paths_in_isolated_process(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    code = r'''
import json
from fastapi.testclient import TestClient
from twinstudio.api import app
with TestClient(app) as client:
    health = client.get('/health')
    assert health.status_code == 200
    assert health.json()['version'] == '0.5.0'
    assert health.json()['feature_lens_count'] == 49

    catalog = client.get('/api/v1/feature-lenses')
    assert catalog.status_code == 200
    assert catalog.json()['declared_lens_count'] == 50
    assert len(catalog.json()['lenses']) == 49

    evolution_catalog = client.get('/api/v1/evolution/catalog')
    assert evolution_catalog.status_code == 200
    assert len(evolution_catalog.json()['extension_dimensions']) >= 30
    assert len(evolution_catalog.json()['lifecycle_templates']) >= 3

    dsl_schema = client.get('/api/v1/dsl/schema')
    assert dsl_schema.status_code == 200
    assert dsl_schema.json()['properties']['kind']['const'] == 'EvolutionProgram'
    assert dsl_schema.json()['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    dsl_grammar = client.get('/api/v1/dsl/grammar')
    assert dsl_grammar.status_code == 200 and 'version-statement' in dsl_grammar.text
    dsl_source = open('examples/evolution/rpi5-hinge-evolution.twin').read()
    dsl_parse = client.post('/api/v1/dsl/parse', json={'source': dsl_source, 'source_format': 'twin'})
    assert dsl_parse.status_code == 200 and dsl_parse.json()['valid'] is True

    projects = client.get('/api/v1/projects')
    assert projects.status_code == 200 and projects.json()
    project = client.get('/api/v1/projects/demo-rpi5')
    assert project.status_code == 200
    tree = client.get('/api/v1/projects/demo-rpi5/tree')
    assert tree.status_code == 200 and tree.json()['tree']
    spec = client.get('/api/v1/projects/demo-rpi5/specification')
    assert spec.status_code == 200 and spec.json()['manufacturing_views']['print_job']
    power = client.post('/api/v1/projects/demo-rpi5/simulations/power')
    assert power.status_code == 200 and power.json()['cases']

    dsl_preview = client.post(
        '/api/v1/projects/demo-rpi5/dsl/preview',
        json={'source': dsl_source, 'source_format': 'twin'},
    )
    assert dsl_preview.status_code == 200, dsl_preview.text
    assert dsl_preview.json()['valid'] is True
    assert dsl_preview.json()['evolution_run']['candidates']
    assert any(stage['stage'] == 'verification' for stage in dsl_preview.json()['lifecycle_blueprint']['stages'])
    dsl_dry_run = client.post(
        '/api/v1/projects/demo-rpi5/dsl/apply',
        json={'source': dsl_source, 'source_format': 'twin', 'dry_run': True, 'generate_artifacts': False},
    )
    assert dsl_dry_run.status_code == 200
    assert dsl_dry_run.json()['events'] == []

    fixation = client.post(
        '/api/v1/projects/demo-rpi5/design-fixation/scan',
        json={
            'target_uri': 'poa://demo/demo-rpi5@main/part/base',
            'challenge': 'Improve print quality around the hinge without assuming the current geometry is fixed.',
            'max_alternatives': 3,
            'use_llm': False,
            'record': True,
        },
    )
    assert fixation.status_code == 200, fixation.text
    payload = fixation.json()
    assert payload['mode'] == 'local'
    assert len(payload['review']['observations']) == 49
    assert len(payload['review']['alternatives']) == 3
    assert payload['events'][0]['event_type'] == 'DesignFixationReviewRecorded'
    reviews = client.get('/api/v1/projects/demo-rpi5/design-fixation/reviews')
    assert reviews.status_code == 200 and reviews.json()

    selection = json.load(open('examples/rpi5-camera3/selections/example-selection.json'))
    resolved = client.post('/api/v1/projects/demo-rpi5/selections/resolve', json=selection)
    assert resolved.status_code == 200 and resolved.json()['resolved_feature_uris']
    planned = client.post('/api/v1/projects/demo-rpi5/change-plans', json={'prompt': 'add a 45 degree chamfer here', 'selection': selection})
    assert planned.status_code == 200 and planned.json()['plan']['operations']
    meta = {
        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'},
        'io.modelcontextprotocol/clientCapabilities': {},
    }
    discovery = client.post(
        '/mcp',
        json={'jsonrpc': '2.0', 'id': 'discover', 'method': 'server/discover', 'params': {'_meta': meta}},
        headers={
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': 'server/discover',
            'Accept': 'application/json, text/event-stream',
        },
    )
    assert discovery.status_code == 200
    assert discovery.json()['result']['supportedVersions'] == ['2026-07-28']
    assert discovery.json()['result']['resultType'] == 'complete'
    assert discovery.json()['result']['serverInfo']['name'] == 'twinstudio'
    tools = client.post(
        '/mcp',
        json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {'_meta': meta}},
        headers={
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': 'tools/list',
            'Accept': 'application/json, text/event-stream',
        },
    )
    assert tools.status_code == 200 and tools.json()['result']['tools']
    tool_names = {item['name'] for item in tools.json()['result']['tools']}
    assert {
        'list_feature_lenses', 'run_design_fixation_scan', 'get_design_fixation_reviews',
        'get_evolution_catalog', 'get_dsl_schema', 'preview_dsl',
        'list_evolution_runs', 'get_lifecycle_blueprints', 'candidate_to_change_plan',
    } <= tool_names
    assert len(tool_names) == 21
    assert tools.json()['result']['cacheScope'] == 'private'
    legacy = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'initialize', 'params': {}})
    assert legacy.status_code == 200 and legacy.json()['result']['protocolVersion'] == '2025-11-25'
    bad_origin = client.post(
        '/mcp',
        json={'jsonrpc': '2.0', 'id': 4, 'method': 'tools/list', 'params': {'_meta': meta}},
        headers={
            'Origin': 'https://evil.example',
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': 'tools/list',
        },
    )
    assert bad_origin.status_code == 403
'''
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(root / "src"),
            "DATABASE_URL": f"sqlite:///{tmp_path / 'api.db'}",
            "TWINSTUDIO_DATA_DIR": str(tmp_path / "data"),
            "DEV_AUTH_BYPASS": "true",
            "MQTT_ENABLED": "false",
        }
    )
    completed = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
