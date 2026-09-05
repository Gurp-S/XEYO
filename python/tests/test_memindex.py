"""A4 memindex：sqlite 派生索引（签名缓存/fail-open）+ A2 fragments 往返。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory import memindex
from memory.governance import new_note_id
from memory.memdir import load_notes, memdir_root, write_note


def _note(title: str, content: str, note_id: str | None = None):
    from memory.governance import parse_and_validate

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


@pytest.fixture()
def mem_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "mem"))
    return tmp_path / "mem"


def _wsid() -> str:
    from memory.memdir import workspace_id
    import os

    return workspace_id(os.getcwd())


def test_sqlite_fixed_on_by_default(mem_env):
    """A4 已固化开启（原 XEYO_MEMORY_SQLITE_INDEX 键已删）；restore 仍是开关。"""
    assert memindex.sqlite_index_enabled() is True
    assert memindex.restore_enabled() is True


def test_cached_load_matches_file_scan(mem_env, monkeypatch, tmp_path):
    wsid = _wsid()
    root = memdir_root(wsid)
    (root / "topics").mkdir(parents=True, exist_ok=True)
    for i in range(5):
        write_note(
            _note(f"t{i}", f"内容 {i} 关于 xeyo-memory-{i}"), wsid=wsid
        )
    file_scan = load_notes(wsid)
    cached = memindex.load_notes_cached(wsid)
    assert [(n.id, n.title, n.content) for n in cached] == [
        (n.id, n.title, n.content) for n in file_scan
    ]


def test_signature_self_heal(mem_env, monkeypatch, tmp_path):
    wsid = _wsid()
    write_note(_note("before", "old body"), wsid=wsid)
    first = memindex.load_notes_cached(wsid)
    assert len(first) == 1
    # 直接改文件（模拟人手编辑/外部写入）→ 签名失配 → 懒重解析
    topic = next((memdir_root(wsid) / "topics").glob("*.md"))
    topic.write_text(
        topic.read_text(encoding="utf-8").replace("old body", "new body"),
        encoding="utf-8",
    )
    second = memindex.load_notes_cached(wsid)
    assert len(second) == 1
    assert "new body" in second[0].content
    # 删除文件 → db 行同步删除
    topic.unlink()
    third = memindex.load_notes_cached(wsid)
    assert third == []


def test_write_through_keeps_cache_fresh(mem_env, monkeypatch, tmp_path):
    wsid = _wsid()
    memindex.load_notes_cached(wsid)  # 预热（空）
    write_note(_note("hot", "fresh fact"), wsid=wsid)
    rows = memindex.load_notes_cached(wsid)
    assert any(n.title == "hot" for n in rows)


def test_fail_open_on_corrupt_db(mem_env, monkeypatch, tmp_path):
    wsid = _wsid()
    write_note(_note("keep", "file truth"), wsid=wsid)
    dbp = memindex.db_path(wsid)
    dbp.parent.mkdir(parents=True, exist_ok=True)
    dbp.write_bytes(b"not a sqlite db")
    # load_notes 的 sqlite 路径抛错 → fail-open 回退文件扫描
    rows = load_notes(wsid)
    assert len(rows) == 1
    assert rows[0].content == "file truth"


def test_fragments_roundtrip(mem_env):
    sid = "sess_frag1"
    stack = "Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: boom"
    n = memindex.store_fragments(
        sid,
        [
            {"msg_index": 12, "kind": "stack", "seq": 0, "text": stack},
            {"msg_index": 12, "kind": "kv", "seq": 0, "text": "theta = 0.5"},
        ],
    )
    assert n == 2
    rows = memindex.get_fragments(sid, 12)
    assert {r["kind"] for r in rows} == {"stack", "kv"}
    stack_row = next(r for r in rows if r["kind"] == "stack")
    assert stack_row["text"] == stack  # 字节级还原
    assert memindex.get_fragments(sid, 999) == []
    # 单 kind 过滤
    only_stack = memindex.get_fragments(sid, 12, kind="stack")
    assert len(only_stack) == 1 and only_stack[0]["kind"] == "stack"


def test_fragment_text_cap(mem_env):
    sid = "sess_cap"
    big = "x" * (memindex.FRAGMENT_TEXT_CAP + 1000)
    memindex.store_fragments(sid, [{"msg_index": 1, "kind": "kv", "seq": 0, "text": big}])
    rows = memindex.get_fragments(sid, 1)
    assert len(rows[0]["text"]) == memindex.FRAGMENT_TEXT_CAP


def test_edges_roundtrip(mem_env):
    sid = "sess_edge"
    memindex.add_edges(
        sid,
        [
            {"from_msg": 3, "to_msg": 4, "kind": "tool_use"},
            {"from_msg": 3, "to_msg": 4, "kind": "tool_use"},  # OR IGNORE
        ],
    )
    edges = memindex.edges_for(sid, 3)
    assert len(edges) == 1
    assert edges[0]["to_msg"] == 4


def test_rollover_cache_matches_files(mem_env, monkeypatch, tmp_path):
    wsid = _wsid()
    d = memdir_root(wsid) / "rollout_summaries"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.md").write_text("---\nsession_id: s1\n---\n# Session\n## Goal\n部署 C2\n", encoding="utf-8")
    cached = memindex.load_rollouts_cached(wsid)
    assert "a.md" in cached and "部署 C2" in cached["a.md"]
    # 新增文件 → 签名同步
    (d / "b.md").write_text("---\nsession_id: s2\n---\n# Session\n## Goal\n重构\n", encoding="utf-8")
    cached = memindex.load_rollouts_cached(wsid)
    assert set(cached) == {"a.md", "b.md"}
