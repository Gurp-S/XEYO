"""memory.journal 生产化测试：锁 + 每路径索引 + 按路径查询 + GC 对齐。

锁与索引均按 workspace 落盘；本套测试只用 monkeypatch ``_changes_path`` 指向
tmp_path，避免污染用户 home（``_index_path`` 由 ``_changes_path`` 派生，随之一致）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import memory.journal as j


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
    return tmp_path


def _rec(seq: int, agent: str, path: str, ts: float, action: str = "edit"):
    return j.ChangeRecord(
        seq=seq,
        agent_id=agent,
        path=path,
        action=action,
        file_hash_after=f"sha256:{path}",
        ts=ts,
        brief="b",
        syntax_valid=True,
        conflict_task=False,
    )


def test_record_change_appends_journal_and_index_seq_monotonic(isolated):
    ws = "ws-a"
    for i in range(3):
        rec = _rec(0, f"agent-{i}", f"src/f{i}.ts", i + 1.0)
        seq = j.record_change(ws, rec)
        assert seq == i + 1  # 进程内锁保证 seq 单调、不重复
    journal = Path(isolated) / "ws-a.jsonl"
    index = Path(isolated) / "ws-a.index.jsonl"
    assert journal.is_file() and index.is_file()
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 3
    assert len(index.read_text(encoding="utf-8").splitlines()) == 3


def test_recent_changes_path_prefix_uses_index(isolated):
    ws = "ws-prefix"
    j.record_change(ws, _rec(0, "a", "src/foo.ts", 1.0))
    j.record_change(ws, _rec(0, "a", "src/keep.ts", 2.0))
    j.record_change(ws, _rec(0, "a", "other/x.py", 3.0))

    rows = j.recent_changes(ws, path_prefix="src/", workspace_root=str(isolated))
    assert [r.path for r in rows] == ["src/foo.ts", "src/keep.ts"]

    rows2 = j.recent_changes(ws, path_prefix="other/", workspace_root=str(isolated))
    assert [r.path for r in rows2] == ["other/x.py"]


def test_recent_changes_agent_and_since_filters(isolated):
    ws = "ws-af"
    j.record_change(ws, _rec(0, "bob", "a.ts", 1.0))
    j.record_change(ws, _rec(0, "alice", "b.ts", 2.0))
    j.record_change(ws, _rec(0, "bob", "c.ts", 3.0))

    rows = j.recent_changes(ws, agent_id="bob")
    assert [r.path for r in rows] == ["a.ts", "c.ts"]
    rows = j.recent_changes(ws, since_ts=2.0)
    assert [r.path for r in rows] == ["b.ts", "c.ts"]


def test_index_staleness_falls_back_to_scan(isolated):
    """journal 写入后没写索引（模拟崩溃/降级）→ 查询回退全量扫描，不丢数据。"""
    ws = "ws-stale"
    j.record_change(ws, _rec(0, "a", "x.ts", 1.0))
    # 直接向 journal 追加一行（绕过 record_change，索引不更新 → 索引水印落后）
    journal_path = Path(isolated) / f"{ws}.jsonl"
    extra = {
        "seq": 2,
        "agent_id": "zz",
        "path": "y.ts",
        "action": "write",
        "file_hash_after": "sha256:y",
        "ts": 2.0,
        "brief": "",
        "syntax_valid": True,
        "conflict_task": False,
        "metadata": {},
    }
    with journal_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(extra) + "\n")
    rows = j.recent_changes(ws)
    assert {r.path for r in rows} == {"x.ts", "y.ts"}


def test_rebuild_index_reconciles(isolated):
    ws = "ws-rebuild"
    j.record_change(ws, _rec(0, "a", "a.ts", 1.0))
    # 手工破坏索引（清空）
    (Path(isolated) / f"{ws}.index.jsonl").write_text("", encoding="utf-8")
    n = j.rebuild_index(ws)
    assert n == 1
    rows = j.recent_changes(ws)
    assert [r.path for r in rows] == ["a.ts"]


def test_gc_prunes_and_rebuilds_index(isolated):
    ws = "ws-gc"
    now = j._now()
    j.record_change(ws, _rec(0, "a", "old.ts", now - 100 * 3600))  # 旧（超 TTL）
    j.record_change(ws, _rec(0, "a", "new.ts", now))
    removed = j.gc(ws, ttl_seconds=24 * 3600)
    assert removed == 1
    rows = j.recent_changes(ws)
    assert [r.path for r in rows] == ["new.ts"]
    # 索引已对齐：不残留旧路径 / 旧 seq
    wm, by_path = j._read_index(ws)
    assert "old.ts" not in by_path
    assert wm == 2


def test_session_filter_in_tool_compat(isolated):
    """索引物化出的 ChangeRecord 保留 metadata，供工具做 session 过滤。"""
    ws = "ws-meta"
    meta = {"session_id": "sess-1"}
    rec = _rec(0, "a", "m.ts", 1.0)
    rec.metadata = meta
    j.record_change(ws, rec)
    rows = j.recent_changes(ws)
    assert rows[0].metadata["session_id"] == "sess-1"
