"""模型投影的机器侧 manifest。

manifest 不进入模型上下文，也不替代 canonical transcript；它是每次采样前
对“实际送出的投影”做的可重入观测，便于区分 compact/spill/配对问题。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProjectionManifest:
    projection_id: str
    created_at: float
    canonical_messages: int
    messages_kept: int
    messages_compacted: int
    tool_calls_seen: int
    tool_results_seen: int
    tool_pairs_preserved: int
    unresolved_tool_calls: int
    spills: int
    t_now_system_blocks: int
    estimated_tokens: int
    context_limit: int | None
    compact_cursor: int
    pressure_reason: str
    runtime: str
    cwd: str
    invariant_errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _tool_ids(messages: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    calls: set[str] = set()
    results: set[str] = set()
    for node in _walk(messages):
        type_name = str(node.get("type") or "")
        if type_name in {"tool_use", "tool_call"}:
            uid = str(node.get("id") or node.get("tool_use_id") or "")
            if uid:
                calls.add(uid)
        elif type_name in {"tool_result", "tool_result_block"}:
            uid = str(node.get("tool_use_id") or node.get("tool_call_id") or "")
            if uid:
                results.add(uid)
    return calls, results


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return ""


def build_manifest(
    *,
    canonical: list[dict[str, Any]],
    projected: list[dict[str, Any]],
    compact_cursor: int = 0,
    context_limit: int | None = None,
    pressure_reason: str = "",
) -> ProjectionManifest:
    """对当前模型投影做不阻断主链的结构检查。"""
    calls, canonical_results = _tool_ids(canonical)
    projected_calls, projected_results = _tool_ids(projected)
    pairs = len(projected_calls & projected_results)
    unresolved = len(projected_calls - projected_results)
    text = _text(projected)
    try:
        serialized = json.dumps(
            projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        serialized = repr(projected)
    projection_id = "proj_" + hashlib.sha256(
        serialized.encode("utf-8", "replace")
    ).hexdigest()[:24]
    system_blocks = sum(
        1 for item in projected if str(item.get("role") or "") == "system"
    )
    invariant_errors: list[str] = []
    if unresolved:
        invariant_errors.append(f"unresolved_tool_calls:{unresolved}")
    # 反向漏报（2026-09-20 事故）：只有「结果无调用」才会让厂商 400
    # （role=tool 必须是某条 assistant tool_calls 的应答），而这里原先只查
    # 「调用无结果」⇒ 坏投影被判为合法，之后每条消息都原样重发同一个坏形状。
    orphan_results = projected_results - projected_calls
    if orphan_results:
        invariant_errors.append(f"orphan_tool_results:{len(orphan_results)}")
        # 诊断（只进服务侧日志，不含内容）：点出是哪几个 tool_call_id 无主，
        # 供反查"最后一公里"里是谁改写了投影；模型可见面不受影响。
        try:
            import logging

            logging.getLogger(__name__).warning(
                "orphan tool results in projection: %s",
                ", ".join(sorted(orphan_results)[:5]),
            )
        except Exception:  # noqa: BLE001 — 诊断失败不影响主链
            pass
    if text.count("full output:") != text.count("output truncated"):
        invariant_errors.append("spill_reference_mismatch")
    if calls - canonical_results:
        invariant_errors.append(
            f"canonical_unpaired_tool_calls:{len(calls - canonical_results)}"
        )

    try:
        from engine.workspace_context import get_execution_context

        ctx = get_execution_context()
        runtime = ctx.runtime if ctx is not None else "unknown"
        cwd = ctx.cwd if ctx is not None else ""
    except Exception:  # noqa: BLE001
        runtime, cwd = "unknown", ""
    return ProjectionManifest(
        projection_id=projection_id,
        created_at=time.time(),
        canonical_messages=len(canonical),
        messages_kept=len(projected),
        messages_compacted=max(0, len(canonical) - len(projected)),
        tool_calls_seen=len(projected_calls),
        tool_results_seen=len(projected_results),
        tool_pairs_preserved=pairs,
        unresolved_tool_calls=unresolved,
        spills=text.count("output truncated"),
        t_now_system_blocks=system_blocks,
        estimated_tokens=max(0, len(serialized) // 4),
        context_limit=context_limit,
        compact_cursor=max(0, int(compact_cursor or 0)),
        pressure_reason=str(pressure_reason or ""),
        runtime=runtime,
        cwd=cwd,
        invariant_errors=invariant_errors,
    )


__all__ = ["ProjectionManifest", "build_manifest"]
