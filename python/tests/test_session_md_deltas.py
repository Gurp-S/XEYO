"""A5 session.md 差分重写：只追加 Changed 节；fold==render；回滚精确截断。"""

from __future__ import annotations

from memory import session_md as sm
from memory.working import WorkingSnapshot


def _msgs(goal: str = "ship C2", extra_tools: int = 10, tail: str = "") -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": f"remember the goal is {goal} {tail}"}]
    for i in range(extra_tools):
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": f"t{i}",
                "content": [
                    {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"out{i} {tail}"}
                ],
            }
        )
    return msgs


def _w(sid: str = "sd1") -> WorkingSnapshot:
    return WorkingSnapshot(session_id=sid)


def test_first_update_writes_full_delta(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_SESSION_MD_DELTA", raising=False)
    maybe = sm.maybe_update("sd1", _msgs(), working=_w())
    assert maybe is None
    rows = sm.read_deltas("sd1")
    assert len(rows) == 1
    assert rows[0]["author"] == "det"
    assert set(rows[0]["sections"]) >= {"## Goal"}  # 首写全节都是 Changed
    assert sm.load("sd1")  # 物化文件照常可读


def test_second_update_only_changed_sections(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_SESSION_MD_DELTA", raising=False)
    w = _w()
    sm.maybe_update("sd1", _msgs(), working=w)
    # 追加 8 个工具 + 改 tail（跨过 REWRITE_GAP=8 节流；tail 变化 → 部分节的值变）
    sm.maybe_update("sd1", _msgs(tail="phase2", extra_tools=18), working=w)
    rows = sm.read_deltas("sd1")
    assert len(rows) == 2
    changed = rows[1]["sections"]
    # Changed 节应少于全节 7（差分的意义：只记变化的节）
    assert len(changed) < 7
    # fold(全部 delta) == 物化现状（load 端有 strip，比较也 strip）
    state = sm.fold_deltas(rows)
    assert sm._fold_sections(state).strip() == sm.load("sd1").strip()


def test_fold_equals_render_property(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_SESSION_MD_DELTA", raising=False)
    w = _w()
    for step in ("a", "b", "c", "d"):
        sm.maybe_update("sd1", _msgs(tail=step), working=w)
        text = sm.load("sd1")
        rebuilt = sm._fold_sections(sm.fold_deltas(sm.read_deltas("sd1")))
        assert rebuilt.strip() == text.strip()  # 折叠重放 ≡ 物化文件（每步都成立）


def test_unchanged_content_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_SESSION_MD_DELTA", raising=False)
    w = _w()
    sm.maybe_update("sd1", _msgs(), working=w)
    rows = sm.read_deltas("sd1")
    mtime = sm.path_for("sd1").stat().st_mtime
    # 同内容再触发（跨过节流间隔）：无 Changed → 不写 delta、不动物化文件
    w2 = _w()
    w2.session_md_tool_epoch = 0
    sm.maybe_update("sd1", _msgs(), working=w2)
    assert sm.read_deltas("sd1") == rows
    assert sm.path_for("sd1").stat().st_mtime == mtime


def test_corrupt_delta_line_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_SESSION_MD_DELTA", raising=False)
    sm.maybe_update("sd1", _msgs(), working=_w())
    with sm.path_deltas("sd1").open("a", encoding="utf-8") as fh:
        fh.write("{not json at all\n")
    rows = sm.read_deltas("sd1")
    assert len(rows) == 1  # 坏行跳过，历史不毁（单条有误只废一条）
    rebuilt = sm._fold_sections(sm.fold_deltas(rows))
    assert rebuilt.strip() == sm.load("sd1").strip()


def test_rewind_truncation_precise(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("XEYO_SESSION_MD_DELTA", raising=False)
    w = _w()
    sm.maybe_update("sd1", _msgs(tail="phase1"), working=w)  # turn≈10
    sm.maybe_update("sd1", _msgs(tail="phase2"), working=w)  # turn≈11
    turns = [r["turn"] for r in sm.read_deltas("sd1")]
    # 回滚到第一条 delta 的 turn：第二条被截断，叙事保留 phase1 时刻
    sm.clear_after_rollback("sd1", keep_tool_calls=turns[0])
    kept = sm.load("sd1")
    assert kept is not None
    assert "phase1" in kept
    assert "phase2" not in kept
    # 截断点 0（回滚到无工具）→ 无可存叙事 → 旧行为整删
    sm.clear_after_rollback("sd1", keep_tool_calls=0)
    assert sm.load("sd1") is None


def test_rollback_without_deltas_falls_back_to_delete(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    sm.path_for("sd1").parent.mkdir(parents=True, exist_ok=True)
    sm.path_for("sd1").write_text("# stale session notes", encoding="utf-8")
    sm.clear_after_rollback("sd1", keep_tool_calls=5)  # 无 delta 文件
    assert sm.load("sd1") is None


def test_deltas_fixed_on(monkeypatch, tmp_path):
    """A5 差分重写已固化开启：env 写 0 关不掉（键已出注册表，照常写 delta 日志）。"""
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("XEYO_SESSION_MD_DELTA", "0")
    sm.maybe_update("sd1", _msgs(), working=_w())
    assert sm.load("sd1") is not None
    assert sm.read_deltas("sd1") != []
