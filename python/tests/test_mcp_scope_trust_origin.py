from types import SimpleNamespace
from extension import mcp_scopes


def test_project_cannot_opt_out_of_trust(monkeypatch):
    monkeypatch.setattr(mcp_scopes, 'read_mcp_scope_files', lambda _: {
        'project': {'local': {'command': 'program', '_requires_trust': False, '_scope': 'user'}},
        'user': {}})
    monkeypatch.setattr(mcp_scopes, 'load_plugin_mcp_specs', lambda *a, **kw: {})
    monkeypatch.setattr(mcp_scopes, 'load_enterprise_policy', mcp_scopes._default_enterprise_policy)
    result = mcp_scopes.collect_mcp_specs('.', config=SimpleNamespace())
    assert result['local']['_scope'] == 'project'
    assert result['local']['_requires_trust'] is True


def test_invalid_server_entry_does_not_crash_valid_siblings(monkeypatch):
    monkeypatch.setattr(mcp_scopes, 'read_mcp_scope_files', lambda _: {
        'project': {'bad': None, 'good': {'command': 'program'}}, 'user': {}})
    monkeypatch.setattr(mcp_scopes, 'load_plugin_mcp_specs', lambda *a, **kw: {})
    monkeypatch.setattr(mcp_scopes, 'load_enterprise_policy', mcp_scopes._default_enterprise_policy)
    result = mcp_scopes.collect_mcp_specs('.', config=SimpleNamespace())
    assert set(result) == {'good'}
    assert result['good']['_requires_trust'] is True
