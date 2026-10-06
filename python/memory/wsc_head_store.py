"""冻结头产物的落盘复用（旁路机制，fail-open，2026-09-24）。

**修什么**：`wsc_projection._STATE` 是进程内存（`_MAX_STATE = 64`，FIFO 淘汰）。
进程一重启、或第 65 个会话进来，冻结头字节就没了 ⇒ 那一枪由 `synaptic.project`
从头重排 ⇒ 发出去的 prompt 与上一枪**逐字无关**，厂商侧整段 miss。
真实 A3 快照：单枪 prompt 中位 11.7k tok，重启后的那一枪全价重投。

**只存什么**：发射产物（头文本）+ 失效条件（cwd / cursor / 冻结区 sha1）。
不 pickle `_Live`、更不 pickle `CadenceState` —— 它们含 shadow 计数、`last_*` 观测、
时间戳等瞬时量，序列化等于把上一枪的状态固化进下一枪（"账面一套、运行一套"的温床）。
落盘 ⇒ 读回时这些量一律从零起，只保留**字节**。

**什么时候不许复用**（任一不成立即拒，调用方走原重建路径 ⇒ 失败方向永远是"更保守"）：
`ver` 不符 / 无文件 / `cwd` 不符（`_pinned` 的钉法是进程内语义，跨进程必须重钉）/
`cursor` 不符（期间真发生过折叠）/ 冻结区越界 / 冻结区 `sha1` 不符（历史被改写、回滚、
in-place 重写）。最后一个是最强的那道：它保证复用的头与历史逐字对得上，宁可重建也不发
一份"和历史不一致的头"。

**不静默丢原文**：头里的冷层引用是 `.xeyo_offload/wsc/*.txt` 这类**字面路径**，
文件在盘上，接回来的头照样能按路径召回 —— 本模块只搬字节，不搬语义。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from memory.wsc_source_layout import LEGACY, bind_seal, validate

_log = logging.getLogger(__name__)

#: 布尔旗标走注册表（`memory/memory_switches.py`），与本模块外的读法同一份。
_ENV = "XEYO_WSC_HEAD_STORE"
_VER = 1
#: 单份记录上限：头正常是 1e4~1e5 字符；超过这个量说明有东西把整棵树写进去了，不落盘。
_MAX_BYTES = 4_000_000
#: 落盘目录清理：只留最近这些天的记录（每次进程只扫一遍）。
_PRUNE_AFTER_S = 7 * 24 * 3600
_pruned = False


def enabled() -> bool:
    """旗标唯一判据。读不到注册表时**不开**（新机制默认不动发射形状）。"""
    try:
        from memory.memory_switches import env_flag

        return env_flag(_ENV)
    except Exception:  # noqa: BLE001 - 判不出来就当关
        return False


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value or "x")[:64]


def _root() -> Path:
    """与会话 id 绑定、**与 cwd 无关** —— cwd 本身是被封印的失效条件之一，
    用它当目录键会让"cwd 变了"从"拒绝复用"变成"找不到文件"，两种失效混成一堆。"""
    home = (os.environ.get("XEYO_HOME") or "").strip()
    base = Path(home) if home else Path(os.path.expanduser("~")) / ".xeyo"
    return base / "wsc_head"


def path_for(session: str) -> Path:
    return _root() / f"{_safe(session)}.json"


@dataclasses.dataclass(frozen=True)
class FrozenHead:
    """接回来的那一份发射产物。没有 `prev` / `cold` / `cadence` —— 那三样不落盘。"""

    text: str
    cwd: str
    cursor: int
    region_end: int
    view_path: str = ""


def region_seal(messages: list[dict], region_end: int, *, source_layout: str = LEGACY) -> str:
    """冻结区（`messages[:region_end]`）的确定性指纹。

    `sort_keys` + `ensure_ascii=False` + 逐条 `\\x1e` 分隔：同一份 dict 列表在任何进程里
    算出同一个值，且 `{"a":1,"b":2}` 与 `{"a":1b:2}` 这类拼接歧义不会撞成同一个指纹。
    """
    h = hashlib.sha1()
    for m in messages[: max(0, int(region_end))]:
        h.update(json.dumps(m, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
        h.update(b"\x1e")
    return bind_seal(h.hexdigest(), source_layout)


def save(
    session: str,
    *,
    text: str,
    cwd: str,
    cursor: int,
    region_end: int,
    messages: list[dict],
    view_path: str = "",
    source_layout: str = LEGACY,
) -> None:
    """头刚建出来时写一份。只在**折叠事件**上调用（不是每枪）⇒ 写放大 = 折叠次数。"""
    if not text or not enabled():
        return
    try:
        validate(source_layout)
        body = json.dumps(
            {
                "ver": _VER,
                "cwd": str(cwd or ""),
                "cursor": int(cursor),
                "region_end": int(region_end),
                "seal": region_seal(messages, region_end, source_layout=source_layout),
                "text": text,
                "view_path": str(view_path or ""),
                **({"compression_source_layout": source_layout} if source_layout != LEGACY else {}),
            },
            ensure_ascii=False,
        )
        if len(body) > _MAX_BYTES:
            return
        path = path_for(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)  # 原子替换：半截文件永远不会被读回来
    except Exception:  # noqa: BLE001 - 观测/缓存面绝不许阻塞投影
        _log.debug("wsc head store write failed", exc_info=True)
    _prune_once()


def _read_record(session):
    path = path_for(session)
    if path.stat().st_size > _MAX_BYTES:
        return None
    rec = json.loads(path.read_text(encoding="utf-8"))
    return rec if isinstance(rec, dict) else None


def source_changed(session, *, cwd, cursor, messages):
    """True only for a well-formed legacy head whose source seal changed."""
    if not enabled():
        return False
    try:
        rec = _read_record(session)
        if rec is None or rec.get("ver") != _VER or rec.get("cwd") != str(cwd or ""):
            return False
        if rec.get("compression_source_layout", LEGACY) != LEGACY or rec.get("cursor") != int(cursor or 0):
            return False
        end = rec.get("region_end")
        if type(end) is not int or not 0 < end <= len(messages):
            return False
        seal = rec.get("seal")
        if not isinstance(seal, str) or len(seal) != 40 or any(c not in "0123456789abcdef" for c in seal):
            return False
        if not isinstance(rec.get("text"), str) or not rec["text"]:
            return False
        return seal != region_seal(messages, end)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def load(
    session: str,
    *,
    cwd: str,
    cursor: int,
    messages: list[dict],
    allow_advance: bool = False,
    source_layout: str = LEGACY,
) -> "FrozenHead | None":
    """接回头字节；任一封印不成立返回 None（调用方重建）。顺序 = 从便宜到贵。"""
    if not enabled():
        return None
    try:
        validate(source_layout)
        rec = _read_record(session)
        if rec is None:
            return None
        if int(rec.get("ver") or 0) != _VER:
            return None
        if rec.get("compression_source_layout", LEGACY) != source_layout:
            return None
        rec_cwd = str(rec.get("cwd") or "")
        if rec_cwd != str(cwd or ""):
            return None
        rec_cursor = int(rec.get("cursor") or 0)
        if rec_cursor != int(cursor) and not (allow_advance and rec_cursor < int(cursor)):
            return None
        end = int(rec.get("region_end") or 0)
        if end <= 0 or end > len(messages):
            return None
        if str(rec.get("seal") or "") != region_seal(messages, end, source_layout=source_layout):
            return None
        text = rec.get("text")
        if not isinstance(text, str) or not text:
            return None
        view_path = rec.get("view_path", "")
        if not isinstance(view_path, str):
            view_path = ""
        return FrozenHead(text=text, cwd=rec_cwd, cursor=rec_cursor, region_end=end, view_path=view_path)
    except Exception:  # noqa: BLE001 - 读坏了就当没有
        _log.debug("wsc head store read failed", exc_info=True)
        return None


def _prune_once() -> None:
    """清掉久没用过的记录（一个会话一份，长跑会攒）。每进程只扫一次，扫失败无所谓。"""
    global _pruned
    if _pruned:
        return
    _pruned = True
    try:
        cutoff = time.time() - _PRUNE_AFTER_S
        for p in _root().glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
