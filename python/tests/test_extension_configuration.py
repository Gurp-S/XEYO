import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routers.extension_documents import router


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home, workspace = tmp_path / 'home', tmp_path / 'workspace'
    home.mkdir(); workspace.mkdir()
    monkeypatch.setattr('memory.instruction.xeyo_home', lambda: home)
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        yield client, home, workspace


def document(client, workspace, kind='mcp', scope='workspace'):
    return client.get('/v1/extensions/configuration', params={'scope': scope, 'kind': kind, 'workspace': str(workspace)}).json()


def post(client, ws, previous, data, **extra):
    return client.post('/v1/extensions/configuration', json={
        'scope': previous['scope'], 'kind': previous['kind'], 'workspace': str(ws),
        'revision': previous['revision'], 'data': data, **extra,
    })


def test_validate_save_scope_and_conflict(setup):
    client, home, ws = setup
    before = document(client, ws)
    data = {'servers': {'example': {'command': 'nonexistent-layout-test', 'args': ['--stdio']}}}
    assert post(client, ws, before, data).json()['validated']
    assert not (ws / '.xeyo/mcp.json').exists()  # Validation never creates files or runs command.
    saved = post(client, ws, before, data, validate_only=False)
    assert saved.json()['saved']
    assert json.loads((ws / '.xeyo/mcp.json').read_text()) == data
    assert not (home / 'mcp.json').exists()
    assert post(client, ws, before, data, validate_only=False).status_code == 409
    scoped = document(client, ws, scope='home')
    assert post(client, ws, scoped, {'servers': {}}, validate_only=False).json()['saved']
    assert json.loads((ws / '.xeyo/mcp.json').read_text()) == data


@pytest.mark.parametrize('data', [
    {'mcpServers': {}}, {'servers': {'x': {'command': ''}}},
    {'servers': {'x': {'command': 'noop', 'args': 'bad'}}},
    {'servers': {'x': {'command': 'noop', '_requires_trust': False}}},
    {'servers': {'x': {'command': 'noop', 'url': 'https://example.com'}}},
    {'servers': {'x': {'command': 'noop', 'startup_timeout_s': -1}}},
    {'servers': {'x': {'command': 'noop', 'auto_start': 'false'}}},
    {'servers': {'x': {'command': 'noop', 'env_mode': []}}},
    {'servers': {'x': {'command': 'noop', 'tools_policy': {}}}},
])
def test_invalid_declaration_never_writes(setup, data):
    client, _, ws = setup
    assert post(client, ws, document(client, ws), data, validate_only=False).status_code == 422
    assert not (ws / '.xeyo/mcp.json').exists()


def test_preserves_other_settings_and_external_changes(setup):
    client, _, ws = setup
    target = ws / '.xeyo/settings.json'; target.parent.mkdir()
    target.write_text(json.dumps({'memory': {'enabled': True}, 'skills': {'old': {'enabled': False}}}))
    before = document(client, ws, 'settings')
    assert 'memory' not in before['data']
    assert post(client, ws, before, {'enabled_extensions': True}, validate_only=False).status_code == 200
    assert json.loads(target.read_text())['memory'] == {'enabled': True}
    assert 'skills' not in json.loads(target.read_text())  # Removing a scoped override actually restores inheritance.
    before = document(client, ws, 'settings')
    target.write_text('{"outside": 1}')
    assert post(client, ws, before, {'enabled_extensions': False}, validate_only=False).status_code == 409
    assert json.loads(target.read_text()) == {'outside': 1}


def test_bad_existing_file_and_missing_workspace_are_not_defaults(setup):
    client, _, ws = setup
    target = ws / '.xeyo/mcp.json'; target.parent.mkdir(); target.write_text('broken')
    assert client.get('/v1/extensions/configuration', params={'scope': 'workspace', 'kind': 'mcp', 'workspace': str(ws)}).status_code == 422
    assert client.get('/v1/extensions/configuration?scope=workspace&kind=mcp').status_code == 422
    assert target.read_text() == 'broken'


def test_lan_cannot_read_or_write_configuration(monkeypatch):
    monkeypatch.delenv('XEYO_ALLOW_REMOTE_CONTROL', raising=False)
    app = FastAPI(); app.include_router(router)
    with TestClient(app, client=('192.168.1.8', 1234)) as client:
        assert client.get('/v1/extensions/configuration?scope=home&kind=mcp').status_code == 403
