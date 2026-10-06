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

from contextvars import ContextVar, Token
from dataclasses import dataclass

__all__ = [
	"WrapWindow",
	"in_wrap_window",
	"reset_wrap_window",
	"set_wrap_window",
	"snapshot_wrap_window",
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


def snapshot_wrap_window() -> "Token[WrapWindow]":
	"""进入查询循环前调用：取一个恢复令牌（记录当前值）。

	循环期间的 set/刷新在同一上下文内生效；退出时用 ``reset_wrap_window``
	恢复进入前的值——嵌套循环（子 Agent 在同一 task 直接 await）因此把内层
	状态还原成父上下文的值，而不是把内层状态留给父级。
	"""
	return _SLOT.set(_SLOT.get())


def reset_wrap_window(token: "Token[WrapWindow]") -> None:
	"""与 ``snapshot_wrap_window`` 配对；token 跨上下文失效时退化为清位。"""
	try:
		_SLOT.reset(token)
	except ValueError:  # token 不属于当前上下文（跨 task 误用）——清位兜底
		_SLOT.set(_INACTIVE)


def wrap_state() -> WrapWindow:
	return _SLOT.get()


def in_wrap_window() -> bool:
	return _SLOT.get().active


def wrap_remaining_s() -> float | None:
	state = _SLOT.get()
	return state.remaining_s if state.active else None
