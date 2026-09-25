"""模型行的权限身份必须是"这一枪提交时"的值，而不是写行瞬间的 ambient 值。

事故形状（2026-09-25 真实数据普查）：最近 40 个轮次里 27 个轮次出现
**同一个 model_request_id 的 started 与 finished 带着不同的
permission_snapshot_id**。原因不是权限层在动，而是记录点选错了：
``_audit_model_event`` 每写一行都从 ambient ``ExecutionContext`` 现取该字段，
而本引擎的工具会在流式过程中提前/并行执行，``tools/tool_registry.py`` 每次裁决
都会 ``update_execution_context(permission_snapshot_id=...)``。
于是那一行记录的是"写行的那一刻"，诊断层拿它判断不了任何权限上下文漂移
（rules._DRIFT_FIELDS 因此把它排除在外）。
"""

from __future__ import annotations

from engine import query_loop as ql
from engine.execution_context import ExecutionContext
from engine.workspace_context import set_workspace_context


class _Recorder:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict]] = []

    def record(self, kind: str, **fields):
        self.rows.append((kind, fields))
        return fields


def _capture(monkeypatch) -> _Recorder:
    from audit import log as audit_log

    rec = _Recorder()
    monkeypatch.setattr(audit_log, "default_audit_log", lambda: rec)
    return rec


class _Model:
    """最小 fake：只带记账 meta，不碰网络。"""

    def __init__(self, **meta) -> None:
        self._meta_request_id = meta.get("request_id", "r1")
        self._meta_attempt = meta.get("attempt", 1)
        for key, value in meta.items():
            if key.startswith("_"):
                setattr(self, key, value)


def _ctx(snapshot_id: str) -> ExecutionContext:
    return ExecutionContext(
        session_id="s1", cwd="/w", runtime="local", permission_snapshot_id=snapshot_id
    )


def test_pinned_identity_wins_over_ambient_mutation(monkeypatch) -> None:
    """流式途中 ambient 被别的声道改掉：这一枪的两行仍必须是同一个身份。"""
    rec = _capture(monkeypatch)
    set_workspace_context(_ctx("perm:attempts_started"))
    try:
        model = _Model(_meta_permission_snapshot_id="perm:attempts_started")
        ql._audit_model_event(
            "model.started",
            session_id="s1",
            turn_id="t1",
            request_id="r1",
            attempt=1,
            model=model,
            status="started",
        )
        # 工具在流式期间完成裁决：ambient 换人了
        set_workspace_context(_ctx("perm:after_tool_decision"))
        ql._audit_model_event(
            "model.finished",
            session_id="s1",
            turn_id="t1",
            request_id="r1",
            attempt=1,
            model=model,
            status="ok",
        )
    finally:
        set_workspace_context(None)

    ids = [f.get("permission_snapshot_id") for _kind, f in rec.rows]
    assert ids == ["perm:attempts_started", "perm:attempts_started"], ids


def test_without_pinned_meta_it_falls_back_to_ambient(monkeypatch) -> None:
    """没注入 meta 的调用方（旧 fake / 旁路）保持旧可见行为，不静默丢字段。"""
    rec = _capture(monkeypatch)
    set_workspace_context(_ctx("perm:ambient"))
    try:
        ql._audit_model_event(
            "model.started",
            session_id="s1",
            turn_id="t1",
            request_id="r1",
            attempt=1,
            model=_Model(),
            status="started",
        )
    finally:
        set_workspace_context(None)

    assert rec.rows[0][1].get("permission_snapshot_id") == "perm:ambient"


def test_attempt_snapshot_reads_ambient_then_the_permission_store(monkeypatch) -> None:
    """取值顺序：ambient 有就用，没有才现算一份快照身份；两边都取不到返回空串。"""
    set_workspace_context(_ctx("perm:ctx"))
    try:
        assert ql._attempt_permission_snapshot_id() == "perm:ctx"
    finally:
        set_workspace_context(None)

    import permissions.trace as ptr

    monkeypatch.setattr(
        ptr, "current_permission_snapshot", lambda **_kw: {"snapshot_id": "perm:fresh"}
    )
    assert ql._attempt_permission_snapshot_id() == "perm:fresh"

    def boom(**_kw):
        raise RuntimeError("store down")

    monkeypatch.setattr(ptr, "current_permission_snapshot", boom)
    assert ql._attempt_permission_snapshot_id() == ""
