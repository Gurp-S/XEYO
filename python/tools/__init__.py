"""Tools 包（Tools | 工具组）。

新增 / 完善工具：
  1. 在 tools.meta 登记元数据
  2. 在 tools/<pkg>/ 实现 execute() 与 prompt.py
  3. 在 tools/catalog.py 把 (name, factory) 加入 ENABLED_TOOL_ENTRIES

``from tools.meta import …`` 不得触发 catalog（避免 policy↔bash 循环导入）。
"""

from __future__ import annotations

from typing import Any

__all__ = [
	"DEFAULT_TOOLS",
	"ENABLED_TOOLS",
	"build_default_registry",
]


def __getattr__(name: str) -> Any:
	if name in ("DEFAULT_TOOLS", "ENABLED_TOOLS", "build_default_registry"):
		from tools import catalog as _catalog

		return getattr(_catalog, name)
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
