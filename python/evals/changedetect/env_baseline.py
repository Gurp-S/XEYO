"""changedetect 的规范环境基线：L0/L1 快照钉的是**产品默认面**的字节。

宿主会话（agent / 受限容器）会把项目级开关桥进进程，快照随环境漂移。实测
（2026-10-07，同一工作树，只改环境变量）：

| 环境变量 | L0 surface | L1 trace |
| --- | --- | --- |
| ``XEYO_TOOL_DENY=Agent`` | 4 处 | 3 处 |
| ``XEYO_TOOL_SURFACE=minimal`` | 18 处 | 0 |
| ``XEYO_T_NOW_SKIP=env_facts,time_now`` | 0 | 19 处 |

这些差异是"这台机器怎么跑"，不是"产品改了什么"。危险在于 ``check`` 报红时顺手
``update``：那会把被 deny 的机器钉成新基线（与 ``tests/conftest.py`` 里
WSC / L5 / aging 的兜底同形——那边同样是"要开的世界由用例显式申请"）。

因此 surface / trace / check / all 四个入口先钉基线再比对；被钉掉的值由调用方
原样打印一行事实（不做劝导）。
"""

from __future__ import annotations

import os

#: (环境变量, 它为什么会漂移 golden)——括号里的数字是 2026-10-07 实测。
PINS: tuple[tuple[str, str], ...] = (
    ("XEYO_TOOL_DENY", "把命名工具移出工作面 ⇒ 工具面/提示块随环境变（实测 L0 4 / L1 3）"),
    ("XEYO_TOOL_SURFACE", "minimal 面 ⇒ 工具集随环境变（实测 L0 18）"),
    ("XEYO_T_NOW_SKIP", "块级旁路 ⇒ 注入面随环境变（实测 L1 19）"),
)


def pin() -> list[tuple[str, str, str]]:
    """按默认面归一化进程环境；返回被清掉的 ``(name, 原值, 原因)``。"""
    cleared: list[tuple[str, str, str]] = []
    for name, why in PINS:
        value = (os.environ.get(name) or "").strip()
        if not value:
            continue
        cleared.append((name, value, why))
        os.environ.pop(name, None)
    return cleared
