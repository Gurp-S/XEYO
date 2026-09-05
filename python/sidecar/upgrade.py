"""sidecar.upgrade — 侧挂模块「升格」聚合器（单点 apply / unapply）。

依据：计划 `docs/实施计划/46-cursor博客技术融合优化计划.md` + 用户决策（总开关 promotion=1）。
作用：把升格动作集中到一处，供 `engine.query_engine.build_default_engine` 在构造时调用一次。
- `apply()`：受 `XEYO_SIDEMOD_PROMOTE` 门控，对 6 个**挂钩型**侧挂模块统一 `install()`。
- `unapply()`：对它们统一 `uninstall()`（一键回退）。
- 纯函数型（pollution/reporting/strict_env/blind_audit）无挂钩面，其升格 = `enabled()` 回退到
  `side_enabled()`（见各自模块），不属于本聚合器。

## 挂的模块（挂钩型，均默认关、可卸载）
- memory.memindex_sig_shadow          （⑧.5 memindex 内容哈希签名）
- tools.fileio.content_index_cache_shadow（⑧ content_index trigram 缓存）
- memory.eval_cold_memory_shadow      （① 冷记忆评测）
- tools.spill_shadow                  （⑭ spill tail 建议）
- prompt.transcript_pointer_shadow    （⑬ C2 原始历史指针）
- memory.rerank_preference_shadow     （⑮ 检索重排偏好）

## 红线
- **不触碰** mcp_name_manifest_shadow（⑫）——它需改会话起点冻结快照，标记「实测 token 收益后接入」。
- `apply()` 任一模块失败 → 照常推进其余（fail-open，绝不因单模块失败挡引擎构建）；卸载失败记日志。
- 只做 install/uninstall（模块内部包装器 fail-open 回退原函数）；不碰主函数语义、缓存、冻结面。
"""

from __future__ import annotations

import importlib
import logging

from sidecar.policy import sidemod_promote

_log = logging.getLogger("xeyo.sidecar.upgrade")

#: 挂钩型侧挂模块列表（按升格顺序）。
_HOOKED = [
    "memory.memindex_sig_shadow",
    "tools.fileio.content_index_cache_shadow",
    "memory.eval_cold_memory_shadow",
    "tools.spill_shadow",
    "prompt.transcript_pointer_shadow",
    "memory.rerank_preference_shadow",
]


def apply() -> bool:
    """升格：对挂钩型侧挂模块统一 install()。返回是否真的执行（受 promote 门控）。

    - `XEYO_SIDEMOD_PROMOTE=0` 时返回 False（未执行，模块保持默认关 = 现状）。
    - 单个模块失败 → 录制日志并继续其余（fail-open），不抛。
    """
    if not sidemod_promote():
        return False
    installed = 0
    for name in _HOOKED:
        try:
            mod = importlib.import_module(name)
            if getattr(mod, "install", lambda: False)():
                installed += 1
        except Exception:  # noqa: BLE001 — fail-open：单模块失败不挡引擎
            _log.warning("sidecar promote failed for %s", name, exc_info=True)
    _log.debug("sidecar promote: installed %d module(s)", installed)
    return True


def unapply() -> None:
    """一键回退：对挂钩型侧挂模块统一 uninstall()。"""
    for name in _HOOKED:
        try:
            mod = importlib.import_module(name)
            getattr(mod, "uninstall", lambda: None)()
        except Exception:  # noqa: BLE001 — 卸载失败仅记日志
            _log.warning("sidecar unpromote failed for %s", name, exc_info=True)


def hooked_modules() -> list[str]:
    return list(_HOOKED)
