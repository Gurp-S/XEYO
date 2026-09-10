"""收尾窗口的环境信号——给工具层的**只读**广播（ContextVar 形态）。

## 语义

预算走尽时 `query_loop` 进入收尾窗（`forced_wrap_up`），并把本状态广播到
contextvars；工具层据此把"会不会吃掉整个收尾窗"的决策（长命令后台化）在
**执行层**静默完成。与 `tools/container_routing`、`permissions.write_scope`
同构：不设置时一切路径与旧行为字节级等价。

## 纪律（与引擎理念一致）

- **只广播事实**（是否在窗口、剩余墙钟秒数），不含任何命令/建议；工具层据此做的
  也只是**路由决策**（立即后台化），不产生给模型的劝告文本；
- 不设置在权限或策略层——它不改变"能不能做"，只改变"怎么做"；
- 未武装墙钟 / 未进入收尾窗时 `in_wrap_window()` 恒 False。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

__all__ = [
	"WrapWindow",
	"clear_wrap_window",
	"in_wrap_window",
	"set_wrap_window",
	"wrap_remaining_s",
	"wrap_state",
]


@dataclass(frozen=True)
class WrapWindow:
	"""收尾窗口状态：是否在窗口内 + 距墙钟死线的剩余秒数（未知为 None）。"""

	active: bool = False
	remaining_s: float | None = None


_INACTIVE = WrapWindow()
_SLOT: ContextVar[WrapWindow] = ContextVar("xeyo_wrap_window", default=_INACTIVE)


def set_wrap_window(active: bool, remaining_s: float | None = None) -> None:
	_SLOT.set(WrapWindow(active=bool(active), remaining_s=remaining_s))


def clear_wrap_window() -> None:
	_SLOT.set(_INACTIVE)


def wrap_state() -> WrapWindow:
	return _SLOT.get()


def in_wrap_window() -> bool:
	return _SLOT.get().active


def wrap_remaining_s() -> float | None:
	state = _SLOT.get()
	return state.remaining_s if state.active else None
