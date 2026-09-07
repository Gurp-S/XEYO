"""rerank_preference_shadow — 【侧挂模块·默认关】轨迹驱动检索重排偏好信号。

依据：轨迹驱动的检索/重排偏好信号设计（侧挂 ⑮）。

## 为什么（收益）
- `memory/search.py` 现在按「词法命中数 + 置信度 + 近因」打分（F4 已有查询感知重排 `query_reweight`，
  默认关；只排序不动召回集——P0 红线）。
- 核心思路：用 **agent 行为轨迹当监督信号**：agent 多次搜索、打开多个文件才找到正确代码
  → 事后推断「更早阶段应检索到什么」。XEYO 已有数据源：`MemoryNote.last_used_at / last_confirmed_at`
  （`touch_last_used` 在检索命中时更新）——即「agent 实际打开/采用了什么」。
- 本模块给**已采用**（最近被使用/确认）的 note 加偏好分，让「被采用者高加分」；**不改召回集**
  （P0：仍由 `load_notes_for_search` 决定哪些 note 进入候选，绝不扩充/收缩）。

## 侧挂契约（不改主逻辑）
- `enabled()`：**恒 True（已固化开启）**——叠加语义修复 + 召回集不变过了验收，原
  `XEYO_MEMORY_RERANK_PREFERENCE` 键已移出 memory_switches 注册表；回退只能改源码。
  残留旁路：`XEYO_SIDEMOD_PROMOTE=0`（侧挂实验全局一键回退，不在 GUI）会跳过 install。
- 包装 `memory.search.search` 打分：在既有 `score` 之上叠加偏好分（`_preference_bonus(note)`）。
- **P0 召回集不变**：候选集仍来自 `load_notes_for_search`；只调排序，绝不改候选集。
- **fail-open**：任何异常 → 交回原 `search()`（检索不因偏好信号中断）。
- 与 F4 `query_reweight` 正交：`query_reweight` 改「广度 vs 深度」，本模块加「采用偏好」。
  两者均已默认开启（F4 是注册表开关默认 1；本模块固化恒开）。

## 偏好信号来源
- `note.last_used_at`：最近一次被检索/触碰/采用；`note.last_confirmed_at`：最近被确认。
  近 24h 内被采用的给较高分；更早的递减；两者皆无 → 0。
"""

from __future__ import annotations

import importlib
import os
import time

_TARGET_MODULE = "memory.search"
_HOOK_NAME = "search"
_ORIG_NAME = "_ORIG__search"
_INSTALLED_FLAG = "__rerank_preference_installed"
_TARGET = None

#: 偏好窗口（秒）与分级权重。
_WINDOW_S = 24 * 3600
_PREFERENCE_WEIGHT = 3.0   # 近 24h 被采用
_MID_WEIGHT = 1.0          # 24h–7d 被采用
_DAYS_7_S = 7 * 24 * 3600


def enabled() -> bool:
    """重排偏好信号：**恒 True**（已固化开启；原 XEYO_MEMORY_RERANK_PREFERENCE 键已删）。

    注意：本模块仍留在 sidecar.upgrade 的挂钩列表里，`XEYO_SIDEMOD_PROMOTE=0`
    （侧挂实验全局回退）会令 apply() 跳过 install——那是全局应急开关，不是本功能开关。
    """
    return True


def install() -> bool:
    """挂钩 `memory.search.search`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    global _TARGET
    mod = importlib.import_module(_TARGET_MODULE)
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _search_rerank)
        setattr(mod, _INSTALLED_FLAG, True)
    _TARGET = mod
    return True


def uninstall() -> None:
    global _TARGET
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    if getattr(mod, _INSTALLED_FLAG, False):
        setattr(mod, _HOOK_NAME, getattr(mod, _ORIG_NAME))
        setattr(mod, _INSTALLED_FLAG, False)
    _TARGET = None


def _search_rerank(query, **kwargs):
    """包装 `memory.search.search`：打分叠加「采用偏好」；召回集不变（P0）。"""
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    try:
        if not enabled():
            return getattr(mod, _ORIG_NAME)(query, **kwargs)
        return _rerank(query, **kwargs)
    except Exception:  # noqa: BLE001 — fail-open：偏好信号异常交回原 search
        return getattr(mod, _ORIG_NAME)(query, **kwargs)


def _rerank(query, **kwargs):
    """重排版检索：复用原 search 的召回，按「原分 + 偏好分」稳定重排。

    **P0 召回集不变**：先调用原 `search()` 得到候选命中（召回集由原函数决定），
    再对已命中 note 以 ``search.score_note``（与主检索同口径的词法分）叠加
    `_preference_bonus` 后重排——同分保持原序，绝不改变候选集。

    touch 语义：先以 touch=False 取召回（偏好分须看"此前"的采用记录，若先触碰
    所有命中都会拿到今天的 last_used_at、偏好分被抹平），重排后按新序统一触碰。
    """
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    kwargs = dict(kwargs)
    want_touch = bool(kwargs.get("touch", True))
    kwargs["touch"] = False
    hits = getattr(mod, _ORIG_NAME)(query, **kwargs)
    if not hits:
        return hits
    q = mod._normalize_query(query)
    terms, _require_all, _min_hits = mod._query_terms(q)
    scored = [
        (mod.score_note(n, q, terms) + _preference_bonus(n), idx, n)
        for idx, n in enumerate(hits)
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = [n for _score, _idx, n in scored]
    if want_touch:
        ident = kwargs.get("wsid") or mod.workspace_id(kwargs.get("cwd") or ".")
        touched = []
        for n in out:
            try:
                touched.append(mod.touch_last_used(n, wsid=ident))
            except OSError:
                touched.append(n)
        return touched
    return out


def _preference_bonus(note) -> float:
    """采用偏好分：近 24h 被采用 +3，24h–7d +1，否则 0。"""
    stamp = _stamp(note)
    if stamp is None or stamp <= 0:
        return 0.0
    age = time.time() - stamp
    if age < 0:
        return 0.0
    if age <= _WINDOW_S:
        return _PREFERENCE_WEIGHT
    if age <= _DAYS_7_S:
        return _MID_WEIGHT
    return 0.0


def _stamp(note) -> float | None:
    """取 note 的「最近采用」时间戳（秒）；last_used_at 优先，退 last_confirmed_at。"""
    raw = getattr(note, "last_used_at", None) or getattr(note, "last_confirmed_at", None)
    if not raw:
        return None
    try:
        # MemoryNote 该类时间戳为 ISO 串（如 'YYYY-MM-DD HH:MM:SS' 或 ISO）；兼容解析。
        s = str(raw)
        if "T" in s:
            s = s.replace("T", " ")
        return time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, AttributeError, TypeError):
        # 已为秒级数字则直接用；否则 None。
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
