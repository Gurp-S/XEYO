"""诊断查询域：运行列表、运行详情、固定证据、上下文定位、实验计划与受控执行。

这里只做查询与受控启动：不持有模型执行计划、不把诊断建议塞回模型上下文。
请求体与源码正文不是普通审计摘要，所以整组路由必须走本机门禁（在 app.py 注册处
统一挂 ``require_loopback``）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from diagnostics import store
from diagnostics.capture import capture_enabled, set_capture_enabled
from diagnostics.collect import collect_run, list_runs
from diagnostics.identity import SCHEMA_VERSION, _s
from diagnostics.loss_chain import trace_fact
from diagnostics.pins import delete_pin, pin_run, pins_for_run, record_verifier
from diagnostics.report import build_report, load_report, report_id, save_report, to_markdown
from diagnostics.rules import RULESET_VERSION, evaluate_run

router = APIRouter(tags=["diagnostics"])


def _key(value: str, label: str) -> str:
    """身份参数在进入查询前收敛：空白值会被下游当成「不按该字段过滤」。"""
    text = str(value if value is not None else "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"{label} 不能为空")
    if len(text) > 300 or any(ch in text for ch in ("/", "\\", "\x00")):
        raise HTTPException(status_code=422, detail=f"{label} 非法")
    return text


def _ident(value: str, label: str) -> str:
    """路径里的 id 必须像本包生成的产物名，越界取值一律 422 而非静默清洗。"""
    try:
        return store.safe_ident(value, label=label)
    except store.InvalidIdentifier as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _experiment_modes() -> tuple[str, ...]:
    """模式取值以实验层自己的常量为准，避免路由与实现各写一份。"""
    from diagnostics.experiments.manifest import MODES

    return tuple(MODES)


class PinBody(BaseModel):
    note: str = Field(default="", max_length=4000)
    expected: str = Field(default="", max_length=4000)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    pinned_files: list[str] = Field(default_factory=list)


class VerifierBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    command: str = Field(default="", max_length=2000)
    exit_code: int | None = None
    output_ref: str = Field(default="", max_length=1000)
    verifier_version: str = Field(default="", max_length=200)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class CaptureBody(BaseModel):
    session_id: str = Field(min_length=1, max_length=300)
    enabled: bool
    max_bytes: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=500)


class ExperimentPlanBody(BaseModel):
    mode: str = Field(default="a0")
    task_id: str = Field(default="", max_length=200)
    pair_id: str = Field(default="p1", max_length=100)
    repeat: int = Field(default=0, ge=0, le=20)
    variants: dict[str, dict[str, Any]] = Field(default_factory=dict)
    allowed_differences: list[str] = Field(default_factory=list)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    task_spec: dict[str, Any] = Field(default_factory=dict)
    budget_cny: float | None = Field(default=None, ge=0)
    price: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(default_factory=dict)
    billable: bool | None = None


class ExperimentStartBody(ExperimentPlanBody):
    idempotency_key: str = Field(min_length=1, max_length=200)


def _checkpoint(raw: dict[str, Any]) -> Any:
    """请求里的检查点字典 → a1.Checkpoint；未知键丢弃而不是猜。"""
    import dataclasses

    from diagnostics.experiments.a1 import Checkpoint

    if not raw:
        return None
    known = {f.name for f in dataclasses.fields(Checkpoint)}
    return Checkpoint(**{k: v for k, v in raw.items() if k in known})


def _plan_kwargs(body: ExperimentPlanBody) -> dict[str, Any]:
    return {
        "mode": body.mode,
        "task_id": body.task_id,
        "variants": body.variants or None,
        "allowed_differences": body.allowed_differences,
        "checkpoint": _checkpoint(body.checkpoint),
        "task_spec": body.task_spec or None,
        "budget_cny": body.budget_cny,
        "price": body.price or None,
        "limits": body.limits or None,
        "billable": body.billable,
    }


def _audit_locator(run: Any) -> str:
    window = run.window("audit")
    return window.locator if window else "audit:unavailable"


@router.get("/v1/diagnostics/runs")
def get_runs(
    session_id: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """有界运行列表：每个 turn 覆盖到哪些边界。"""
    sid = _key(session_id, "session_id")
    coverage: dict[str, Any] = {}
    runs = list_runs(sid, limit=limit, coverage_sink=coverage)
    return {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "session_id": sid,
        "runs": runs,
        "count": len(runs),
        "limit": limit,
        # 列表为空时 coverage 仍要说得清："读完整份没有" vs "尾窗没盖到"。
        # complete 的既有口径不变（每条 run 都无缺项说明），扫描本身的情况另放。
        "complete": bool(runs) and not any(r.get("coverage_note") for r in runs),
        "coverage": coverage,
        "store_root": str(store.diagnostics_root()),
    }


@router.get("/v1/diagnostics/runs/{turn_id}")
def get_run(
    turn_id: str = Path(min_length=1),
    session_id: str = Query(..., min_length=1),
    event_limit: int = Query(default=200, ge=1, le=1000),
    event_offset: int = Query(default=0, ge=0),
    with_report: bool = Query(default=True),
) -> dict[str, Any]:
    """一次运行的证据链、结论与缺项；事件按 offset 分页。"""
    sid = _key(session_id, "session_id")
    tid = _key(turn_id, "turn_id")
    run = collect_run(sid, tid)
    findings = evaluate_run(run)
    doc = run.to_dict(include_rows=False)
    events = [e.to_dict(_audit_locator(run)) for e in run.events_for_turn()]
    page = events[event_offset : event_offset + event_limit]
    doc["events"] = page
    doc["event_total"] = len(events)
    doc["event_limit"] = event_limit
    doc["event_offset"] = event_offset
    doc["events_complete"] = event_offset + len(page) >= len(events)
    doc["next_event_cursor"] = (
        "" if doc["events_complete"] else str(event_offset + event_limit)
    )
    doc["findings"] = [f.to_dict() for f in findings]
    if with_report:
        full = build_report(run, findings)
        doc["attribution"] = full["attribution"]
        doc["usage_summary"] = full["usage_summary"]
        doc["fault"] = full["fault"]
    doc["versions"] = store.code_version()
    return doc


@router.get("/v1/diagnostics/runs/{turn_id}/report.md")
def get_run_markdown(turn_id: str = Path(min_length=1), session_id: str = Query(..., min_length=1)) -> dict[str, str]:
    """Markdown 导出：同一结构渲染，不额外加工结论。"""
    sid = _key(session_id, "session_id")
    tid = _key(turn_id, "turn_id")
    run = collect_run(sid, tid)
    return {"markdown": to_markdown(build_report(run)), "turn_id": tid, "session_id": sid}


@router.post("/v1/diagnostics/runs/{turn_id}/pin")
def post_pin(body: PinBody, turn_id: str = Path(min_length=1), session_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    """标记「这轮结果不对」并固定证据。不触发任何付费实验，也不改任务内容。"""
    if not body.note.strip():
        return {"ok": False, "error": "note 不能为空"}
    sid = _key(session_id, "session_id")
    tid = _key(turn_id, "turn_id")
    doc = pin_run(
        sid,
        tid,
        note=body.note,
        expected=body.expected,
        evidence=body.evidence,
        pinned_files=body.pinned_files,
    )
    return {"ok": True, "pin": doc}


@router.post("/v1/diagnostics/runs/{turn_id}/verifier")
def post_verifier(
    body: VerifierBody, turn_id: str = Path(min_length=1), session_id: str = Query(..., min_length=1)
) -> dict[str, Any]:
    """固定一次验收结果。``exit_code`` 省略即"未运行"，不会按 0 处理。"""
    sid = _key(session_id, "session_id")
    tid = _key(turn_id, "turn_id")
    doc = record_verifier(
        sid,
        tid,
        name=body.name,
        command=body.command,
        exit_code=body.exit_code,
        output_ref=body.output_ref,
        verifier_version=body.verifier_version,
        evidence=body.evidence,
    )
    return {"ok": True, "pin": doc}


@router.get("/v1/diagnostics/pins")
def get_pins(session_id: str = Query(..., min_length=1), turn_id: str = Query(default="")) -> dict[str, Any]:
    return {"pins": pins_for_run(_key(session_id, "session_id"), _s(turn_id))}


@router.delete("/v1/diagnostics/pins/{pin_id}")
def remove_pin(pin_id: str = Path(min_length=1), session_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    return {"ok": delete_pin(_ident(pin_id, "pin_id"), _key(session_id, "session_id"))}


@router.get("/v1/diagnostics/runs/{turn_id}/fact")
def get_fact(
    turn_id: str = Path(min_length=1),
    session_id: str = Query(..., min_length=1),
    needle: str = Query(..., min_length=1, max_length=400),
) -> dict[str, Any]:
    """信息丢失定位链：这条事实在哪一级消失，或为什么无法归因。"""
    sid = _key(session_id, "session_id")
    tid = _key(turn_id, "turn_id")
    text = _s(needle).strip()
    if not text:
        raise HTTPException(status_code=422, detail="needle 不能为空")
    run = collect_run(sid, tid)
    return trace_fact(run, text)


@router.get("/v1/diagnostics/messages/{message_id}")
def get_message_body(
    message_id: str = Path(min_length=1),
    session_id: str = Query(..., min_length=1),
    max_chars: int = Query(default=20000, ge=1, le=200000),
) -> dict[str, Any]:
    """按需回读 transcript 正文（含冷层 blob）。缺 blob 必须说明，不返回空正文冒充成功。"""
    from pathlib import Path as FsPath

    sid = _key(session_id, "session_id")
    mid = _s(message_id)
    try:
        from session.persistence import transcript_path
        from session.transcript_blobs import blobs_dir, resolve_transcript_row
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"transcript 读取器不可用：{type(exc).__name__}"}
    path = transcript_path(sid)
    if not path.is_file():
        return {"ok": False, "error": "no_transcript", "locator": str(path)}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                import json as _json

                row = _json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or str(row.get("id") or "") != mid:
                continue
            ref = _s(row.get("content_ref"))
            if ref and not (blobs_dir(path) / FsPath(ref).name).is_file():
                return {
                    "ok": False,
                    "error": "missing_blob",
                    "message_id": mid,
                    "body_state": "missing_blob",
                    "content_hash": str(row.get("content_hash") or ""),
                    "locator": str(path),
                }
            try:
                resolved = resolve_transcript_row(row, path)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"resolve_failed: {type(exc).__name__}", "message_id": mid}
            content = resolved.get("content")
            text = content if isinstance(content, str) else str(content or "")
            return {
                "ok": True,
                "message_id": mid,
                "role": str(row.get("role") or ""),
                "content": text[:max_chars],
                "truncated": len(text) > max_chars,
                "body_state": "blob" if ref else "inline",
                "content_hash": str(row.get("content_hash") or ""),
                "locator": str(path),
            }
    return {"ok": False, "error": "no_such_message", "message_id": mid, "locator": str(path)}


@router.get("/v1/diagnostics/capture")
def get_capture(session_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    sid = _key(session_id, "session_id")
    return {
        "session_id": sid,
        "enabled": capture_enabled(sid),
        "disk_bytes": store.dir_size(store.captures_dir()),
        "disk_scope": "captures_dir",
        "quota_bytes": store.quota_bytes(),
        "locator": str(store.captures_dir()),
    }


@router.post("/v1/diagnostics/capture")
def post_capture(body: CaptureBody) -> dict[str, Any]:
    """按会话开启可复现记录。开启只影响是否落盘，不改变任何发射形状。"""
    sid = _key(body.session_id, "session_id")
    doc = set_capture_enabled(sid, body.enabled, max_bytes=body.max_bytes, note=body.note)
    return {"ok": True, "session_id": sid, "enabled": capture_enabled(sid), "config": doc}


@router.get("/v1/diagnostics/captures/{body_hash}")
def get_capture_body(body_hash: str = Path(min_length=1)) -> dict[str, Any]:
    from diagnostics.capture import resolve_capture

    return resolve_capture(_ident(body_hash, "body_hash"))


@router.post("/v1/diagnostics/experiments/plan")
def post_experiment_plan(body: ExperimentPlanBody) -> dict[str, Any]:
    """生成差异、输入可用性、隔离要求与预算。不发模型请求。"""
    from diagnostics.experiments import runner

    if body.mode not in _experiment_modes():
        return {"ok": False, "error": f"mode 必须是 {list(_experiment_modes())}"}
    try:
        return {"ok": True, "plan": runner.plan(**_plan_kwargs(body))}
    except Exception as exc:  # noqa: BLE001 — 计划失败要可见，不转成成功
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


@router.post("/v1/diagnostics/experiments")
def post_experiment_start(body: ExperimentStartBody) -> dict[str, Any]:
    """按明确的实验配置启动。同一 idempotency_key 重连不重复执行。"""
    if body.mode not in _experiment_modes():
        return {"ok": False, "error": f"mode 必须是 {list(_experiment_modes())}"}
    from diagnostics.experiments import runner

    kwargs = _plan_kwargs(body)
    checkpoint = kwargs.pop("checkpoint")
    try:
        return runner.start(
            idempotency_key=body.idempotency_key,
            pair_id=body.pair_id,
            repeat=body.repeat,
            checkpoint=checkpoint,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


@router.get("/v1/diagnostics/experiments")
def get_experiments(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    from diagnostics.experiments import runner

    index = runner.load_index()
    by_key = index.get("by_key") if isinstance(index.get("by_key"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key, ident in sorted(by_key.items()):
        rows.append({"idempotency_key": key, "experiment_id": _s(ident)})
    rows.sort(key=lambda r: r["experiment_id"], reverse=True)
    return {"experiments": rows[:limit], "count": len(rows)}


@router.get("/v1/diagnostics/experiments/{experiment_id}")
def get_experiment(experiment_id: str = Path(min_length=1)) -> dict[str, Any]:
    from diagnostics.experiments import runner

    return runner.progress(_ident(experiment_id, "experiment_id"))


@router.post("/v1/diagnostics/experiments/{experiment_id}/cancel")
def post_experiment_cancel(experiment_id: str = Path(min_length=1)) -> dict[str, Any]:
    from diagnostics.experiments import runner

    return runner.cancel(_ident(experiment_id, "experiment_id"))


@router.get("/v1/diagnostics/reports/{report_id}")
def get_report(report_id: str = Path(min_length=1)) -> dict[str, Any]:
    ident = _ident(report_id, "report_id")
    doc = load_report(ident)
    if not doc:
        return {"ok": False, "error": "no_such_report", "report_id": ident}
    return {"ok": True, "report": doc}


@router.post("/v1/diagnostics/reports")
def post_report(session_id: str = Query(..., min_length=1), turn_id: str = Query(default="")) -> dict[str, Any]:
    sid = _key(session_id, "session_id")
    run = collect_run(sid, _s(turn_id))
    doc = build_report(run)
    ident = report_id(doc)
    path = save_report(doc)
    return {"ok": True, "path": path, "report_id": ident, "markdown": to_markdown(doc)}


__all__ = ["router"]
