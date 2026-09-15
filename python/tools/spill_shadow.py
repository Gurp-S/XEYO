"""spill_shadow — 【侧挂模块·升格后默认开】spill 预览补「Read 该路径」tail 建议。

升格状态（2026-09-14 更正）：挂钩型侧挂模块（在 `sidecar/upgrade.py` 的 `_HOOKED` 清单内），
`enabled()` 走 `sidecar.policy.side_enabled()`；专用 env 未设时回退总升格开关
`XEYO_SIDEMOD_PROMOTE`（默认 1=升格）⇒ 实际**默认开**，原「默认关」表述与运行时相反。
单项关闭 `XEYO_SPILL_TAIL_HINT=0`，全局回退 `XEYO_SIDEMOD_PROMOTE=0`。

依据：spill 预览补 tail 建议设计（侧挂 ⑭：大输出落盘后提示 Read 该路径，文案级）。

## 为什么（收益=可用性）
- 大工具输出落文件后，`spill.save_text` 返回的 `SpillRef.hint` 只有 `full output: <path> (N bytes)`。
  模型不知道「若要中段，该 Read 该路径」。
- 本模块给 hint 追加半句「若需中段，Read 该路径」，与 `glob_tool` 的 `spill_path — use Read to open`
  同款。

## 侧挂契约（不改主逻辑）
- `enabled()`：读 `XEYO_SPILL_TAIL_HINT`；未设时回退总升格开关（默认开）。开=`save_text` 的 hint 追加建议；
  关=原样（逐位不变）。
- `install()` / `uninstall()`：挂钩 `tools.spill.save_text`。卸载即恢复原函数。
- **fail-open**：任何异常 → 交回原 `save_text`（落盘不受影响；宁可 hint 无建议也不破坏证据）。
"""

from __future__ import annotations

import importlib

_TARGET_MODULE = "tools.spill"
_HOOK_NAME = "save_text"
_ENV = "XEYO_SPILL_TAIL_HINT"
_ORIG_NAME = "_ORIG__save_text"
_INSTALLED_FLAG = "__spill_tail_hint_installed"
_TARGET = None

_TAIL_SUGGESTION = "若需中段，Read 该路径"


def enabled() -> bool:
    """是否启用 tail 建议（升格后默认开；专用 env / 全局 promote 可关）。"""
    from sidecar.policy import side_enabled

    return side_enabled(_ENV)


def install() -> bool:
    """挂钩 `tools.spill.save_text`；返回是否实际安装（仅已启用才装）。"""
    if not enabled():
        return False
    global _TARGET
    mod = importlib.import_module(_TARGET_MODULE)
    if not getattr(mod, _INSTALLED_FLAG, False):
        if not hasattr(mod, _ORIG_NAME):
            setattr(mod, _ORIG_NAME, getattr(mod, _HOOK_NAME))
        setattr(mod, _HOOK_NAME, _save_text_with_hint)
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


def _save_text_with_hint(session_id: str, text: str):
    """包装 `spill.save_text`：在 hint 里追加 tail 建议。"""
    mod = _TARGET or importlib.import_module(_TARGET_MODULE)
    try:
        ref = getattr(mod, _ORIG_NAME)(session_id, text)
        # ref.hint 是 SpillRef 的 hint 字段；追加建议（不覆盖原 hint）。
        if ref is not None and hasattr(ref, "hint") and ref.hint:
            return ref.__class__(path=ref.path, bytes=ref.bytes, hint=ref.hint + f"（{_TAIL_SUGGESTION}）")
        return ref
    except Exception:  # noqa: BLE001 — fail-open：hint 建议失败不破坏落盘
        return getattr(mod, _ORIG_NAME)(session_id, text)


def tail_suggestion() -> str:
    return _TAIL_SUGGESTION
