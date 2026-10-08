"""文件规模事实：让"大文件"在**读之前**就可见。

动机（agent 自报的摩擦）：Glob/Grep 的结果里没有任何规模信号，唯一的
``view_total_lines`` 来自**读完之后**的 read_observation ⇒ 只能先整读一遍
（1145 行）才知道它 1145 行。这里给结果行附一个廉价的字节事实
（``os.stat``，不读文件、不开子进程），让读法（整读 / 定向读 / 先看结构）
在读之前就能决定。

边界：
- 纯附加事实，不删改任何既有字段与排版；
- ``XEYO_GLOB_SIZE_FACTS=0`` 一键关掉（回到逐字节相同的旧输出）；
- 任何异常（不存在 / 权限 / 虚拟文件系统）→ 返回空串，绝不因规模事实失败。
"""

from __future__ import annotations

import os

#: 低于这个字节数不标注：小文件"整读"本来就是对的读法，标注只是噪声。
_MIN_BYTES = 24 * 1024

ENV_SWITCH = "XEYO_GLOB_SIZE_FACTS"


def enabled() -> bool:
    raw = os.environ.get(ENV_SWITCH, "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "off", "no"}


def size_suffix(path: str, *, min_bytes: int = _MIN_BYTES) -> str:
    """返回 ``" (48 KB)"`` 这类规模后缀；小文件/取不到 → ``""``。"""
    if not enabled():
        return ""
    try:
        size = os.stat(path).st_size
    except (OSError, ValueError):
        return ""
    if size < max(0, int(min_bytes)):
        return ""
    return f" ({_human(size)})"


def _human(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, size // 1024)} KB"


__all__ = ["ENV_SWITCH", "enabled", "size_suffix"]
