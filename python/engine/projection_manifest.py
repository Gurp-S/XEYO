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


# 「截断」这个词在投影里由三个不同的产生方写下，形状各不相同：
#   tools/tool_registry.py      [output truncated: …；full output: <path>]   —— 声明+句柄成对
#   tools/spill.py              full output: <path> (N bytes)                —— 只有句柄
#   tools/bash_tool/truncate.py [output truncated, full at <path> (N chars)] —— 自带回读路径
#   tools/job_tools.py          (earlier output truncated)                   —— 天生无句柄
# 旧不变量拿 "full output:" 与 "output truncated" 两个子串各自的全局计数比大小，
# 于是任何一次 Bash 截断或后台任务输出都会让它为真（真实数据 26/40 轮），
# 连正文里引用过这两个词都会改变计数。它测的不是它以为的那件事。
# 现在只问一条真正会伤人的：声明了预算截断，有没有在同一处给出可回读句柄。
_TRUNCATION_CLAIM = "[output truncated:"
_SPILL_HANDLE = "full output:"
_BASH_SPILL_MARK = "[output truncated, full at "


def _truncation_claim_spans(text: str) -> list[str]:
    """每个预算截断标记 own 的那段文字（到它自己的右括号；没闭合就到结尾）。"""
    spans: list[str] = []
    start = 0
    while True:
        at = text.find(_TRUNCATION_CLAIM, start)
        if at < 0:
            return spans
        end = text.find("]", at)
        spans.append(text[at:] if end < 0 else text[at : end + 1])
        start = at + len(_TRUNCATION_CLAIM)


def _unhandled_truncations(text: str) -> int:
    """截断声明里缺句柄的处数 —— 这些是模型再也读不回来的原文。"""
    return sum(1 for span in _truncation_claim_spans(text) if _SPILL_HANDLE not in span)


def _spill_handle_count(text: str) -> int:
    """带可回读句柄的截断/落盘标记数（spills 的真实口径）。

    残留口径限制：这是按**标记前缀**计数的估计值 —— 正文里原样引用
    ``full output:`` 也会计入一项。它只用于"这一轮大概有几处可回读"的展示，
    真正的不变量看 ``_unhandled_truncations``（只扫 ``[output truncated:`` 的
    标记作用域，不受正文引用影响）。
    """
    return text.count(_SPILL_HANDLE) + text.count(_BASH_SPILL_MARK)


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
    if _unhandled_truncations(text):
        # 旗标名保持不变（诊断层按名字 membership 判定，见 diagnostics/rules.py 的
        # cold_reference 分支）；含义收窄成"有截断声明拿不到回读句柄"。
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
        spills=_spill_handle_count(text),
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
