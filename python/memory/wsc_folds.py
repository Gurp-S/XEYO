"""WSC 收纳事实台账（内存，键=session_id）：让"早期内容被收纳了几段、最近一段是什么"。

动机（agent 自报的摩擦）：折叠此前对模型**完全不可见**——唯一痕迹是
``fold_events.jsonl``（观测台账，模型看不到），模型能察觉"东西丢了"的唯一信号
是撞上写守卫的 ``missing_read``。本台账把这件事变成一行可核对事实，挂进
``context_usage``（不新增 T_now 登记条目、不动硬顶）。

约束（设计前提，别丢）：
- **单调**：计数只在真折叠时 +1，一轮内不会出现两个版本。反例是 ``est``/``vendor``
  那种"值会被下一枪推翻"的写法——同一轮里并排两个数字，锚错比没锚更坏。
- 键=会话 id，纯内存（随进程消失），与 ``engine/live_agents`` 同形态；
  有界（满则按插入序淘汰最旧），失败一律 fail-open。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Iterable

_MAX_SESSIONS = 512
_MAX_SUBJECT_CHARS = 60

_LOCK = threading.Lock()
_FOLDS: dict[str, dict[str, Any]] = {}

#: 可当作"最近被收纳的对象"的来源：工具调用里的路径/模式字段。
_PATH_KEYS = ("file_path", "path", "pattern", "notebook_path")


def record_fold(session_id: str, subject: str = "") -> None:
    """记一次真折叠。任何异常由调用方兜（本函数不抛）。"""
    sid = str(session_id or "").strip()
    if not sid:
        return
    text = str(subject or "").strip()[:_MAX_SUBJECT_CHARS]
    with _LOCK:
        item = _FOLDS.get(sid)
        if item is None:
            if len(_FOLDS) >= _MAX_SESSIONS:
                _FOLDS.pop(next(iter(_FOLDS)))
            item = {"folds": 0, "last_subject": ""}
            _FOLDS[sid] = item
        item["folds"] = int(item.get("folds") or 0) + 1
        if text:
            item["last_subject"] = text
        item["at"] = round(time.time(), 3)


def snapshot(session_id: str) -> dict[str, Any]:
    """该会话的 {folds, last_subject}；没有记录 → folds=0。"""
    with _LOCK:
        item = _FOLDS.get(str(session_id or "").strip())
        if not item:
            return {"folds": 0, "last_subject": ""}
        return {"folds": int(item.get("folds") or 0),
                "last_subject": str(item.get("last_subject") or "")}


def forget(session_id: str) -> None:
    """会话删除时回收（同 id 复用时不会继承旧计数）。"""
    with _LOCK:
        _FOLDS.pop(str(session_id or "").strip(), None)


def subject_from(messages: Iterable[Any], start: int, end: int) -> str:
    """从被收纳的消息区间里挑最后一个"可指认对象"（文件路径/搜索模式）。

    挑不到 → 空串（正文就只说段数，不编一个假出处）。
    """
    try:
        chunk = list(messages)[max(0, int(start)):max(0, int(end))]
    except Exception:  # noqa: BLE001
        return ""
    found = ""
    for message in chunk:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            payload = block.get("input")
            if not isinstance(payload, dict):
                continue
            for key in _PATH_KEYS:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    found = value.strip()
                    break
    return found


__all__ = ["forget", "record_fold", "snapshot", "subject_from"]
