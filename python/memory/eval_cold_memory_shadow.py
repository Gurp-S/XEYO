"""eval_cold_memory_shadow — 【侧挂模块·默认关】评测冷记忆：清空召回面，只测「解」不测「记」。

依据：计划 `docs/实施计划/46-cursor博客技术融合优化计划.md` §A1（①）。
对应方案稿：`docs/设计/cursor博客的技术融合到XEYO.md` §①（把「记忆召回」当作「已知修复检索」通道）。

## 为什么（收益=评测诚实度）
- XEYO 自评时，`memory/search.py` 的检索召回就是外部 git/web 泄漏的 XEYO 内变体（混淆效应
  相同）——分数混入「检索已知修复」而非「原创解决」。
- 本模块在**评测时**清空可召回索引/召回面，让分数测「解」不测「记」。同时保留召回归因能力
  （`mark_retrieval_assisted`），把「靠检索命中的引用」与「原创解决」分开标注。

## 侧挂契约（不改主文件逻辑）
- `enabled()`：读 `XEYO_EVAL_COLD_MEMORY`（默认 0=关，仅评测置 1）。开=`search()` 候选召回面
  置空返回 `[]`；关=原逻辑（逐位不变）。
- `install()` / `uninstall()`：挂钩 `memory.search.search`。卸载即恢复原函数，零源改动。
- **作用域限制**：为避免误伤生产路径，仅当**调用链处于评测上下文**才真正清空召回面——
  本模块用「独立的 `XEYO_EVAL_COLD_MEMORY=1` 开关」作为评测显式声明；未置位恒走原逻辑。
- **fail-open**：任何异常 → 交回原 `search()`（报告/检索不因评测开关而中断）。

## 召回归因（纯函数，不写盘）
`mark_retrieval_assisted(block)`：给 `CitationBlock` 的每条 entry 的 note 前加
`[retrieval-assisted] ` 前缀 + 整体 `rollout_ids` 不变；返回**新块**（不改原块）。供评测审计侧
把「靠检索命中的引用」与「原创解决」分开标注。**红线**：不改结构、不写文件、纯只读。
"""

from __future__ import annotations

import importlib
import os

_TARGET_MODULE = "memory.search"
_HOOK_NAME = "search"
_ENV = "XEYO_EVAL_COLD_MEMORY"

_ORIG_NAME = "_ORIG__search"
_INSTALLED_FLAG = "__eval_cold_memory_installed"
_TARGET = None

#: 引用标记前缀（mark_retrieval_assisted 使用）。
_RETRIEVAL_PREFIX = "[retrieval-assisted] "


def enabled() -> bool:
    """是否启用冷记忆评测（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def install() -> bool:
    """挂钩 `memory.search.search`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    global _TARGET
    mod = importlib.import_module(_TARGET_MODULE)
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _search_cold)
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


def _search_cold(query, **kwargs):
    """冷记忆版 `search.search`：清空召回面返回 `[]`（只测「解」不测「记」）。

    任何异常 → 回退原 `search()`（fail-open：评测/检索不因开关中断）。
    """
    try:
        return []
    except Exception:  # noqa: BLE001 — 绝不让冷记忆开关破坏检索
        return _orig()(query, **kwargs)


def _orig():
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    return getattr(mod, _ORIG_NAME)


# --------------------------------------------------------------------------- #
# 召回归因（纯函数）
# --------------------------------------------------------------------------- #

def mark_retrieval_assisted(block):
    """给引用块的每条 entry 加 `[retrieval-assisted]` 前缀；返回新块（不改原块）。

    - 只读/纯函数；不写文件、不改结构（entries/rollout_ids 数据类型不变）。
    - 前端/审计侧可据此把「靠检索命中的引用」与「原创解决」分开标注。
    """
    if block is None:
        return block
    from memory.citation import CitationEntry, CitationBlock

    new_entries = []
    for e in block.entries:
        note = (e.note or "")
        if note.startswith(_RETRIEVAL_PREFIX):
            new_entries.append(e)  # 已标注，原样保留
        else:
            new_entries.append(
                CitationEntry(
                    path=e.path,
                    line_start=e.line_start,
                    line_end=e.line_end,
                    note=_RETRIEVAL_PREFIX + note,
                )
            )
    return CitationBlock(entries=new_entries, rollout_ids=list(block.rollout_ids))
