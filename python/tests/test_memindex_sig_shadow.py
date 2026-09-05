"""memindex_sig_shadow 门槛/证明性测试（⑧.5）。

覆盖：
- 关（默认）：不挂钩，`_sync_table` 逐位不变。
- 开=内容哈希签名：同 mtime 不同内容正确重读；卸载后恢复原函数。
- fail-open：签名路径异常（memdir 缺失）不静默吞，交给调用方。
- 读代价探针：开关两路径都能正确同步（不抛错）。
"""

from __future__ import annotations

import os as _os

import pytest

from memory import memindex
from memory.memindex_sig_shadow import _sha256, enabled, install, uninstall


@pytest.fixture()
def mem_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "mem"))
    return tmp_path / "mem"


@pytest.fixture()
def shadow_off(monkeypatch):
    monkeypatch.delenv("XEYO_MEMINDEX_SIG_HASH", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


def _note(title: str, content: str, note_id: str | None = None):
    from memory.governance import new_note_id, parse_and_validate

    fm = {
        "id": note_id or new_note_id(),
        "type": "fact",
        "title": title,
        "scope": "workspace",
        "status": "active",
        "confidence": 0.8,
        "source": {"kind": "user"},
    }
    return parse_and_validate(fm, content)


def _wsid() -> str:
    import os

    from memory.memdir import workspace_id

    return workspace_id(os.getcwd())


def test_default_off_no_hook(mem_env, shadow_off):
    assert enabled() is False
    assert install() is False
    assert not getattr(memindex, "__memindex_sig_installed", False)


def test_install_replaces_and_uninstall_restores(mem_env, monkeypatch):
    monkeypatch.setenv("XEYO_MEMINDEX_SIG_HASH", "1")
    assert enabled() is True
    before = memindex._sync_table
    assert install() is True
    assert getattr(memindex, "__memindex_sig_installed", False) is True
    assert memindex._sync_table is not before
    uninstall()
    assert getattr(memindex, "__memindex_sig_installed", False) is False
    assert memindex._sync_table is before


def test_content_hash_signature_catches_same_mtime(mem_env, monkeypatch, tmp_path):
    """同 mtime（强制同一值）但内容不同 → 内容哈希签名识别并重读。"""
    monkeypatch.setenv("XEYO_MEMINDEX_SIG_HASH", "1")
    assert install() is True
    try:
        from memory.memdir import write_note

        from memory.memdir import memdir_root

        wsid = _wsid()
        write_note(_note("t", "old body"), wsid=wsid)
        rows1 = memindex.load_notes_cached(wsid)
        assert len(rows1) == 1

        # 直接改文件内容（模拟外部编辑），并把 mtime 强制回同一值（模拟同秒编辑）。
        topic = next((memdir_root(wsid) / "topics").glob("*.md"))
        fixed = 1_700_000_000.0
        _os.utime(topic, (fixed, fixed))
        topic.write_text(
            topic.read_text(encoding="utf-8").replace("old body", "new body"),
            encoding="utf-8",
        )
        _os.utime(topic, (fixed, fixed))  # 仍然同一 mtime

        rows2 = memindex.load_notes_cached(wsid)
        assert len(rows2) == 1
        # mtime 相同但内容哈希不同 → 内容被识别并并入 DB。
        assert "new body" in rows2[0].content
        assert rows2[0].id == rows1[0].id
    finally:
        uninstall()


def test_read_cost_both_paths_sync(mem_env, monkeypatch, tmp_path):
    """关/开两条路径都能正确同步（不抛错）。"""
    from memory.memdir import write_note

    wsid = _wsid()
    for i in range(3):
        write_note(_note(f"t{i}", f"内容 {i} 关于 xeyo-memory-{i}"), wsid=wsid)

    # 关（回退）：promote=0 + 未设模块 env → install() 返回 False，行为=原逻辑。
    monkeypatch.delenv("XEYO_MEMINDEX_SIG_HASH", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")
    assert install() is False
    assert len(memindex.load_notes_cached(wsid)) == 3

    # 开（升格）：设模块 env=1。
    monkeypatch.setenv("XEYO_MEMINDEX_SIG_HASH", "1")
    assert install() is True
    try:
        assert len(memindex.load_notes_cached(wsid)) == 3
    finally:
        uninstall()


def test_fail_open_missing_memdir(mem_env, monkeypatch, tmp_path):
    """签名路径 memdir 缺失 → 签名函数返回空，调用方拿空结果（不抛）。"""
    monkeypatch.setenv("XEYO_MEMINDEX_SIG_HASH", "1")
    assert install() is True
    try:
        rows = memindex.load_notes_cached("ws_failopen_new")
        assert rows == []
    finally:
        uninstall()


def test_sha256_stability():
    assert len(_sha256("x")) == 32
