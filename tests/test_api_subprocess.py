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
from living_product_studio.api import app
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
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
            "LPS_DATA_DIR": str(tmp_path / "data"),
            "DEV_AUTH_BYPASS": "true",
            "MQTT_ENABLED": "false",
        }
    )
    completed = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
