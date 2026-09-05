"""sidecar.policy — 侧挂模块的「升格」总谓词（单一来源）。

依据：计划 `docs/实施计划/46-cursor博客技术融合优化计划.md`。
用户决策：全部升格（除 ⑫），用总开关 `XEYO_SIDEMOD_PROMOTE`（默认 1）一键回退=0。

## 语义
- `sidemod_promote()`：是否升格。默认 **True**（升格）；`XEYO_SIDEMOD_PROMOTE=0` → False（回退）。
- `side_enabled(env_name)`：侧挂模块 `enabled()` 应返回的值——
  ① 已注册进 memory_switches 的键严格按 `get_value`（settings.memory 权威）；
  ② 未注册键优先看各自专用 env；③ 未设置专用 env 时回退到 `sidemod_promote()`。这样：
  - 注册键：与 GUI 显示逐位一致（env/promote 均不穿越）。
  - 未注册键：升格开启（默认）且专用 env 未设 → True（默认开）；
    显式 `XEYO_XXX=0` → False（单项关闭）；`XEYO_SIDEMOD_PROMOTE=0` → False（全局回退）。
- 纯函数型 `enabled()` 与挂钩型 `enabled()` 共用此谓词，保证行为一致。

## 红线
- 只读环境变量，无副作用；不触碰任何主模块函数/缓存。
"""

from __future__ import annotations

import os

#: 总升格开关（默认 1=升格；0=全局回退）。
_PROMOTE_ENV = "XEYO_SIDEMOD_PROMOTE"


def sidemod_promote() -> bool:
    """是否升格（默认 True）。``=0`` / false / off / no 视为关。"""
    raw = os.environ.get(_PROMOTE_ENV, "").strip().lower()
    if not raw:
        return True
    return raw not in ("0", "false", "off", "no", "")


def promote_env() -> str:
    return _PROMOTE_ENV


def side_enabled(env_name: str) -> bool:
    """侧挂模块 enabled()：三段优先级。

    1. **已注册进 memory_switches 的键** → 严格按 ``get_value``（settings.memory
       唯一权威，env 与 ``XEYO_SIDEMOD_PROMOTE`` 均不参与）。否则 GUI 显示 0
       而升格回退默认开，出现「显示关、实际开」（契约 tests/test_memory_switch_authority.py）。
    2. 未注册键：专用 env 显式设置则严格按它。
    3. 都未设 → 回退全局升格 ``sidemod_promote()``。
    """
    try:
        from memory.memory_switches import get_value

        val = get_value(env_name)
        if val != "":
            return val == "1"
    except Exception:  # noqa: BLE001 — switches 不可用时退回 env/promote 语义
        pass
    raw = os.environ.get(env_name, "").strip().lower()
    if raw:
        return raw not in ("0", "false", "off", "no", "")
    return sidemod_promote()
