"""LSP 工具契约测试：语言映射、结果渲染、fail-open（无服务器时不报假阴）。

不起真实语言服务器：验的是「发现 → 渲染 → 失败时的措辞」这三段。
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from lsp import manager
from lsp.servers import find_server, language_for_path
from tools.lsp_tool import LspTool


def _run(tool, payload):
    return asyncio.run(tool.execute(payload, AbortController()))


def _no_servers(monkeypatch):
    """把候选表清空 + 清掉 env 覆盖 ⇒ 任何语言都找不到服务器。"""
    monkeypatch.setattr("lsp.servers.CANDIDATES", {})
    for key in list(os.environ):
        if key.startswith("XEYO_LSP_SERVER_"):
            monkeypatch.delenv(key, raising=False)


# ---- 语言映射 ---------------------------------------------------------------

def test_language_mapping():
    assert language_for_path("a/b/c.py") == "python"
    assert language_for_path("x.tsx") == "typescriptreact"
    assert language_for_path("Makefile") == ""
    assert language_for_path("x.unknown") == ""


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("XEYO_LSP_SERVER_PYTHON", "my-lsp --stdio")
    spec = find_server("python")
    assert spec is not None and spec.command == ("my-lsp", "--stdio")


def test_no_server_found_when_registry_empty(monkeypatch):
    _no_servers(monkeypatch)
    assert find_server("python") is None
    assert manager.status()["available"] == []


# ---- 结果渲染 ---------------------------------------------------------------

def test_render_locations_all_three_shapes(tmp_path):
    root = tmp_path
    (root / "a.py").write_text("x\n", encoding="utf-8")
    uri = (root / "a.py").as_uri()
    loc = {"uri": uri, "range": {"start": {"line": 4, "character": 2}}}
    link = {
        "targetUri": uri,
        "targetSelectionRange": {"start": {"line": 9, "character": 0}},
    }
    assert manager.render_locations(loc, root) == ["a.py:5:3"]
    assert manager.render_locations([loc, link], root) == ["a.py:5:3", "a.py:10:1"]
    assert manager.render_locations(None, root) == []


def test_render_hover_shapes():
    assert manager.render_hover({"contents": "sig"}) == "sig"
    assert manager.render_hover({"contents": {"value": "sig2"}}) == "sig2"
    assert manager.render_hover({"contents": ["a", {"value": "b"}]}) == "a\nb"
    assert manager.render_hover(None) == ""


def test_render_symbols_nested():
    payload = [
        {
            "name": "Cls",
            "kind": 5,
            "selectionRange": {"start": {"line": 2, "character": 0}},
            "children": [
                {
                    "name": "m",
                    "kind": 6,
                    "selectionRange": {"start": {"line": 4, "character": 4}},
                }
            ],
        }
    ]
    lines = manager.render_symbols(payload, ".", "a.py")
    assert lines[0].startswith("Cls") and "a.py:3" in lines[0]
    assert lines[1].startswith("  m") and "a.py:5" in lines[1]


# ---- fail-open --------------------------------------------------------------

def test_status_action(monkeypatch):
    _no_servers(monkeypatch)
    result = _run(LspTool(cwd="."), {"action": "status"})
    assert not result.is_error
    assert "available on PATH: (none)" in result.content


def test_missing_server_is_not_an_error(tmp_path, monkeypatch):
    """核心纪律：没有服务器 ⇒ 中性事实，不是"没有定义"。"""
    _no_servers(monkeypatch)
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    result = _run(LspTool(cwd=str(tmp_path)), {"action": "definition", "path": "a.py", "line": 1})
    assert not result.is_error
    assert "no language server for python" in result.content
    assert "Read/Grep still work" in result.content
    assert "no definition" not in result.content


def test_unmapped_extension_is_not_an_error(tmp_path, monkeypatch):
    _no_servers(monkeypatch)
    (tmp_path / "Makefile").write_text("all:\n", encoding="utf-8")
    result = _run(LspTool(cwd=str(tmp_path)), {"action": "hover", "path": "Makefile", "line": 1})
    assert not result.is_error
    assert "no language server mapping" in result.content


def test_unknown_action_is_error():
    result = _run(LspTool(cwd="."), {"action": "rename"})
    assert result.is_error
    assert "unknown action" in result.content


def test_missing_path_is_error():
    result = _run(LspTool(cwd="."), {"action": "symbols"})
    assert result.is_error
    assert "path is required" in result.content


def test_position_required_for_position_actions(tmp_path, monkeypatch):
    _no_servers(monkeypatch)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = _run(LspTool(cwd=str(tmp_path)), {"action": "references", "path": "a.py"})
    assert result.is_error
    assert "line (1-based) is required" in result.content


def test_missing_file_is_error(tmp_path, monkeypatch):
    _no_servers(monkeypatch)
    result = _run(LspTool(cwd=str(tmp_path)), {"action": "symbols", "path": "nope.py"})
    assert result.is_error
    assert "no such file" in result.content


# ---- 契约 -------------------------------------------------------------------

def test_tool_flags_and_schema():
    tool = LspTool(cwd=".")
    assert tool.is_read_only() is True
    assert tool.is_concurrency_safe() is True
    schema = tool.schema()
    assert schema["name"] == "Lsp"
    assert schema["input_schema"]["required"] == ["action"]
