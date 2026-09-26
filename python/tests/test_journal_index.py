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


def test_recent_changes_uses_the_index_when_aligned(isolated, monkeypatch):
    """对齐时必须真的走索引读——这条路径在修好新鲜度之前从未被执行过。"""
    ws = "ws-uses"
    j.record_change(ws, _rec(0, "a", "src/f.ts", 1.0))
    j.record_change(ws, _rec(0, "a", "src/g.ts", 2.0))

    seen: list[str] = []
    real = j._read_index

    def spy(wsid):
        out = real(wsid)
        seen.append(wsid)
        return out

    monkeypatch.setattr(j, "_read_index", spy)
    assert j._journal_fresh(ws, Path(isolated) / f"{ws}.jsonl") is True
    rows = j.recent_changes(ws, path_prefix="src/")
    assert [r.path for r in rows] == ["src/f.ts", "src/g.ts"]
    assert seen == [ws], seen


def test_index_ahead_of_journal_is_not_fresh(isolated):
    """索引比 journal 多行（GC 后没重建成功就是这个形）⇒ 判为不新鲜。"""
    ws = "ws-ahead"
    j.record_change(ws, _rec(0, "a", "one.ts", 1.0))
    j.record_change(ws, _rec(0, "a", "two.ts", 2.0))
    journal = Path(isolated) / f"{ws}.jsonl"
    kept = journal.read_text(encoding="utf-8").splitlines()[-1]
    journal.write_text(kept + "\n", encoding="utf-8")  # 只留最新一条，索引不动
    assert j._journal_fresh(ws, journal) is False
    assert [r.path for r in j.recent_changes(ws)] == ["two.ts"]


def test_session_filter_in_tool_compat(isolated):
    """索引物化出的 ChangeRecord 保留 metadata，供工具做 session 过滤。"""
    ws = "ws-meta"
    meta = {"session_id": "sess-1"}
    rec = _rec(0, "a", "m.ts", 1.0)
    rec.metadata = meta
    j.record_change(ws, rec)
    rows = j.recent_changes(ws)
    assert rows[0].metadata["session_id"] == "sess-1"


# ---------------------------------------------------------------------------
# 回归：GC 扫描把派生索引当 journal，会让文件名每小时多长一层 .index
# ---------------------------------------------------------------------------


def test_journal_workspace_ids_skips_derived_indexes(tmp_path):
    for name in (
        "ws-a.jsonl",
        "ws-a.index.jsonl",
        "ws-a.index.index.jsonl",
        "ws-b.jsonl",
        "notes.txt",
    ):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert j.journal_workspace_ids(tmp_path) == ["ws-a", "ws-b"]
    assert j.is_derived_index(tmp_path / "ws-a.index.jsonl") is True
    assert j.is_derived_index(tmp_path / "ws-a.jsonl") is False


def test_index_name_is_not_a_workspace_id(isolated):
    """把索引名喂回来必须报错，而不是静默再套一层 / 撞名。"""
    with pytest.raises(ValueError):
        j._index_path("ws-a.index")

    # 旧跑轮的入口就是这个形状：ws-a.index.jsonl 确实在目录里"像个 journal"。
    (isolated / "ws-a.index.jsonl").write_text(
        '{"seq": 1, "path": "src/f.ts"}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        j.gc("ws-a.index", ttl_seconds=0)
    # 拒绝之后不能留下更深的一层
    assert not (isolated / "ws-a.index.index.jsonl").exists()


def test_repeated_gc_sweep_does_not_grow_files(isolated):
    """闭环不变量：按新的枚举方式重复跑 GC，目录里的文件名集合不该增长。"""
    for i in range(3):
        j.record_change("ws-a", _rec(i, "agent-1", f"src/f{i}.ts", float(i)))
    assert (isolated / "ws-a.jsonl").is_file()
    assert (isolated / "ws-a.index.jsonl").is_file()

    for _ in range(4):
        for wsid in j.journal_workspace_ids(isolated):
            j.gc(wsid, ttl_seconds=0)

    names = sorted(p.name for p in isolated.glob("*.jsonl"))
    assert names == ["ws-a.index.jsonl", "ws-a.jsonl"], names


# ---------------------------------------------------------------------------
# 回归：GC 裁了 journal 却没重建索引 ⇒ 旧索引不能继续被当作"新鲜"
# ---------------------------------------------------------------------------


def test_gc_that_cannot_rebuild_index_does_not_serve_ghosts(isolated, monkeypatch):
    """裁剪成功、重建失败 ⇒ 查询不得报出 journal 里已经没有的变更。

    索引的 watermark 只跟 journal 的尾 seq 比，被裁掉的是**旧** seq，所以裁剪后
    旧索引仍然"盖得住"尾号——不删掉它就会把幻影行读成真话。
    """
    ws = "ws-gc-fail"
    now = j._now()
    j.record_change(ws, _rec(0, "a", "old.ts", now - 100 * 3600))
    j.record_change(ws, _rec(0, "a", "new.ts", now))

    def boom(_wsid):
        raise OSError("disk full")

    monkeypatch.setattr(j, "rebuild_index", boom)
    assert j.gc(ws, ttl_seconds=24 * 3600) == 1

    rows = j.recent_changes(ws)
    assert [r.path for r in rows] == ["new.ts"], rows


def test_gc_reports_when_the_stale_index_survives(isolated, monkeypatch, caplog):
    """连删都删不掉时至少要留下事实，不许静默 pass。"""
    ws = "ws-gc-stuck"
    now = j._now()
    j.record_change(ws, _rec(0, "a", "old.ts", now - 100 * 3600))
    j.record_change(ws, _rec(0, "a", "new.ts", now))

    monkeypatch.setattr(j, "rebuild_index", lambda _wsid: (_ for _ in ()).throw(OSError("ro")))
    real_unlink = Path.unlink

    def stuck(self, *a, **k):
        if self.name.endswith(".index.jsonl"):
            raise OSError("locked by another handle")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", stuck)
    with caplog.at_level("WARNING"):
        j.gc(ws, ttl_seconds=24 * 3600)
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert "index" in caplog.text.lower(), caplog.text
