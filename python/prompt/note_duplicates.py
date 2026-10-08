"""同一 ``note_key`` 在一次投影里出现两份（内容不同）的**可数事实**。

动因（2026-10-08 本会话实测）：整段重渲染只在"文本变了"时替换旧副本；同回合内该行的
数字每枪都变 ⇒ 旧副本撤不掉、新片段照发，模型同时看到两份：

    world_state: …120k…      world_state: …121k…

这个形态原先是"只有 agent 读代码才发现"的（本次为此绕了若干轮）。冻结治因
（``prompt.context_usage`` 的轮内冻结）；本模块把"仍在发生"变成可数指标，回归里可以断言 0。

纯观测：任何异常都吞掉（指标不该影响投影装配）。
"""

from __future__ import annotations

import json
import threading
from typing import Any

_LOCK = threading.Lock()
#: 观测点 → 累计"同 key 多版本"次数。
_EVENTS: dict[str, int] = {}
#: 观测点 → 最近一次的各 key 版本数（供诊断面看形状）。
_LAST: dict[str, dict[str, int]] = {}


def _fingerprint(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(content)


def observe(rows: Any, *, where: str) -> int:
    """数一遍：有多少个 ``note_key`` 带了 ≥2 个**互不相同**的正文版本。

    返回重复键个数（0 = 干净）。同一份文本重复出现不算重复版本——那是投影自身的
    分块，不是"同一事实的两个测量值"。
    """
    try:
        per_key: dict[str, set[str]] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("note_key") or "").strip()
            if not key:
                continue
            per_key.setdefault(key, set()).add(_fingerprint(row.get("content")))
        counts = {key: len(versions) for key, versions in per_key.items()}
        dup_keys = {key: n for key, n in counts.items() if n > 1}
        with _LOCK:
            _LAST[where] = counts
            if dup_keys:
                _EVENTS[where] = _EVENTS.get(where, 0) + 1
        return len(dup_keys)
    except Exception:  # noqa: BLE001 — 指标绝不阻断投影装配
        return 0


def snapshot() -> dict[str, Any]:
    """当前计数（诊断 / 回归用）。"""
    with _LOCK:
        return {
            "events": dict(_EVENTS),
            "last": {k: dict(v) for k, v in _LAST.items()},
        }


def reset() -> None:
    with _LOCK:
        _EVENTS.clear()
        _LAST.clear()


__all__ = ["observe", "reset", "snapshot"]
