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
    assert health.json()['revision'] == 'test-revision'
    assert health.json()['feature_lens_count'] == 49
    assert health.json()['observation_dsl_version'] == 'TWINOBS 1.0'

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
    missing = client.get('/api/v1/projects/missing-project', headers={'X-Correlation-ID': 'test-correlation'})
    assert missing.status_code == 404
    assert missing.headers['X-Correlation-ID'] == 'test-correlation'
    assert missing.json()['error']['code'] == 'PROJECT_NOT_FOUND'
    assert missing.json()['error']['dsl'].startswith('TWINOBS 1.0')
    playbook = client.get(missing.json()['error']['registry_uri'])
    assert playbook.status_code == 200 and 'REPAIR 1.0' in playbook.json()['markdown']
    tree = client.get('/api/v1/projects/demo-rpi5/tree')
    assert tree.status_code == 200 and tree.json()['tree']
    artifact = client.get('/api/v1/projects/demo-rpi5/artifacts/base-stl')
    assert artifact.status_code == 200 and len(artifact.content) > 1000
    drawings_pdf = client.get('/api/v1/projects/demo-rpi5/drawings.pdf')
    assert drawings_pdf.status_code == 200, drawings_pdf.text
    assert drawings_pdf.headers['content-type'] == 'application/pdf'
    assert 'demo-rpi5-main-drawings.pdf' in drawings_pdf.headers['content-disposition']
    assert drawings_pdf.content.startswith(b'%PDF-') and len(drawings_pdf.content) > 2_000
    png_data_url = (
        'data:image/png;base64,'
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )
    tab_slugs = {
        'view3d': '3d',
        'view2d': '2d',
        'spec': 'specification-xbom',
        'lifecycle': 'lifecycle',
        'tests': 'tests-simulations',
        'fixation': 'feature-lenses',
        'evolution': 'evolution-dsl',
    }
    for tab, slug in tab_slugs.items():
        tab_pdf = client.post(
            f'/api/v1/projects/demo-rpi5/tabs/{tab}.pdf',
            json={
                'content_text': f'Visible content for {tab}: Zażółć gęślą jaźń',
                'screenshot_png_data_url': png_data_url if tab == 'view3d' else None,
                'selected_object_uri': 'poa://demo/demo-rpi5@main/part/base',
            },
        )
        assert tab_pdf.status_code == 200, (tab, tab_pdf.text)
        assert tab_pdf.headers['content-type'] == 'application/pdf'
        assert f'demo-rpi5-main-{slug}.pdf' in tab_pdf.headers['content-disposition']
        assert tab_pdf.content.startswith(b'%PDF-') and len(tab_pdf.content) > 1_000
    invalid_tab_pdf = client.post('/api/v1/projects/demo-rpi5/tabs/unknown.pdf', json={})
    assert invalid_tab_pdf.status_code == 422
    invalid_png_pdf = client.post(
        '/api/v1/projects/demo-rpi5/tabs/view3d.pdf',
        json={'screenshot_png_data_url': 'data:image/png;base64,bm90IGEgcG5n'},
    )
    assert invalid_png_pdf.status_code == 422
    ui_context = {
        'session_id': 'pytest-browser-1234',
        'project_id': 'demo-rpi5',
        'active_tab': 'view3d',
        'viewer_state': 'ready',
        'loaded_mesh_count': 2,
        'expected_mesh_count': 2,
        'rendered_triangles': 100,
        'visible_artifact_uris': ['poa://demo/demo-rpi5@main/artifact/base-stl'],
        'artifacts': [{
            'uri': 'poa://demo/demo-rpi5@main/artifact/base-stl',
            'purpose': 'viewer3d:base',
            'status': 'visible',
        }],
    }
    reported = client.put('/api/v1/projects/demo-rpi5/ui-context', json=ui_context)
    assert reported.status_code == 200, reported.text
    current_ui = client.get('/api/v1/projects/demo-rpi5/ui-context')
    assert current_ui.status_code == 200 and current_ui.json()['rendered_triangles'] == 100
    observation_logs = client.get('/api/v1/projects/demo-rpi5/logs.dsl?limit=100')
    assert observation_logs.status_code == 200
    assert observation_logs.headers['content-type'].startswith('text/plain')
    assert 'demo-rpi5-observations.twinobs' in observation_logs.headers['content-disposition']
    assert observation_logs.headers['cache-control'] == 'no-store'
    assert 'TWINOBS 1.0' in observation_logs.text
    assert 'HTTP_REQUEST_COMPLETED' in observation_logs.text
    assert 'PROJECT "demo-rpi5"' in observation_logs.text
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
    queue = client.get('/api/v1/projects/demo-rpi5/change-queue')
    assert queue.status_code == 200, queue.text
    queued_chamfer = next(
        item for item in queue.json()['tasks']
        if item['plan_id'] == planned.json()['plan']['plan_id']
    )
    assert queued_chamfer['status'] == 'waiting_cad'
    assert queued_chamfer['target_uris'] == ['poa://demo/demo-rpi5@main/part/base']
    assert queue.json()['active_count'] >= 1

    selection_2d = dict(selection)
    selection_2d.update({
        'selection_id': 'history-undo-selection',
        'uri': 'poa://demo/demo-rpi5@main/region/history-undo-selection',
        'source_view': '2d',
        'tool': 'rectangle',
        'ray_hits': [],
        'world_aabb': None,
        'camera': None,
        'projection_entity_ids': ['front.base.outer-wall'],
    })
    annotation = client.post(
        '/api/v1/projects/demo-rpi5/annotations',
        json={'text': 'ustaw grubość ścian na 3 mm', 'selection': selection_2d},
    )
    assert annotation.status_code == 200, annotation.text
    reversible_plan = client.post(
        '/api/v1/projects/demo-rpi5/change-plans',
        json={'prompt': 'ustaw grubość ścian na 3 mm', 'selection': selection_2d},
    )
    assert reversible_plan.status_code == 200, reversible_plan.text
    reversible_plan_id = reversible_plan.json()['plan']['plan_id']
    applied = client.post(
        f'/api/v1/projects/demo-rpi5/change-plans/{reversible_plan_id}/apply',
        json={'annotation_uri': annotation.json()['uri']},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()['result']['parameter_patches'][0]['previous_parameter']['value'] == 2
    applied_event = next(event for event in applied.json()['events'] if event['event_type'] == 'ChangeApplied')
    assert applied_event['data']['authority']['schema_version'] == 'twinstudio.change-authority/v1'
    assert applied_event['data']['authority']['actor'] == 'creator@example.test'
    assert applied_event['data']['authority']['permission'] == 'change.apply'
    changed_project = client.get('/api/v1/projects/demo-rpi5').json()['project']
    base_uri = 'poa://demo/demo-rpi5@main/part/base'
    assert changed_project['objects'][base_uri]['parameters']['wall_thickness']['value'] == 3
    assert changed_project['annotations'][annotation.json()['uri']]['status'] == 'resolved'
    history = client.get('/api/v1/projects/demo-rpi5/change-history')
    assert history.status_code == 200, history.text
    applied_entry = next(item for item in history.json() if item['event_type'] == 'ChangeApplied')
    assert applied_entry['undo_available'] is True
    undone = client.post(
        f"/api/v1/projects/demo-rpi5/change-history/{applied_entry['event_id']}/undo"
    )
    assert undone.status_code == 200, undone.text
    reverted_project = client.get('/api/v1/projects/demo-rpi5').json()['project']
    assert reverted_project['objects'][base_uri]['parameters']['wall_thickness']['value'] == 2
    assert reverted_project['annotations'][annotation.json()['uri']]['status'] == 'open'
    history_after_undo = client.get('/api/v1/projects/demo-rpi5/change-history').json()
    assert any(item['event_type'] == 'ChangeReverted' for item in history_after_undo)
    assert next(
        item for item in history_after_undo if item['event_id'] == applied_entry['event_id']
    )['reverted'] is True
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
        'get_error_playbook', 'get_ui_context',
    } <= tool_names
    assert len(tool_names) == 23
    assert tools.json()['result']['cacheScope'] == 'private'
    ui_tool = client.post(
        '/mcp',
        json={
            'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
            'params': {
                'name': 'get_ui_context',
                'arguments': {'project_id': 'demo-rpi5'},
                '_meta': meta,
            },
        },
        headers={
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': 'tools/call',
            'Mcp-Name': 'get_ui_context',
            'Accept': 'application/json, text/event-stream',
        },
    )
    assert ui_tool.status_code == 200, ui_tool.text
    assert ui_tool.json()['result']['structuredContent']['viewer_state'] == 'ready'
    error_tool = client.post(
        '/mcp',
        json={
            'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call',
            'params': {
                'name': 'get_error_playbook',
                'arguments': {'code': 'UI_ARTIFACT_LOAD_FAILED'},
                '_meta': meta,
            },
        },
        headers={
            'MCP-Protocol-Version': '2026-07-28',
            'Mcp-Method': 'tools/call',
            'Mcp-Name': 'get_error_playbook',
            'Accept': 'application/json, text/event-stream',
        },
    )
    assert error_tool.status_code == 200, error_tool.text
    assert 'REPAIR 1.0' in error_tool.json()['result']['structuredContent']['markdown']
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
            "TWINSTUDIO_BUILD_SHA": "test-revision",
            "DEV_AUTH_BYPASS": "true",
            "MQTT_ENABLED": "false",
            "TWINSTUDIO_CAD_REGEN_ENABLED": "false",
        }
    )
    completed = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
