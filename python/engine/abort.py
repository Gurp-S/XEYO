from __future__ import annotations

import threading
import weakref
from collections.abc import Callable


class Aborted(Exception):
	"""循环内检测到中断时抛出，由 query_loop 转成 StoppedEvent。"""

	def __init__(self, reason: str = "aborted") -> None:
		self.reason = str(reason or "aborted")
		super().__init__(self.reason)


AbortListener = Callable[[str], None]


class AbortController:
	"""线程安全的取消节点。

	旧代码只依赖 ``aborted``/``abort``，所以这两个入口保持不变；新代码可用
	``child`` 建立 session → turn → tool/job → process 的父子关系。父节点只持有
	子节点弱引用，避免长生命周期 session 因已结束的工具泄漏内存。
	"""

	def __init__(self, *, label: str = "") -> None:
		self.label = str(label or "")
		self._aborted = False
		self._reason = ""
		self._notified = False
		self._lock = threading.RLock()
		self._listeners: set[AbortListener] = set()
		self._children: weakref.WeakSet[AbortController] = weakref.WeakSet()

	@property
	def aborted(self) -> bool:
		"""是否已中断。"""
		with self._lock:
			return self._aborted

	@property
	def reason(self) -> str:
		with self._lock:
			return self._reason or "aborted"

	@property
	def cancel_reason(self) -> str:
		"""结构化别名；便于生命周期/trace 层不用猜字段名。"""
		return self.reason

	def abort(self, reason: str = "aborted") -> bool:
		"""中断节点及其全部子节点；返回本次是否首次触发。"""
		with self._lock:
			if self._aborted:
				return False
			self._aborted = True
			self._reason = str(reason or "aborted")
			notifications = self._take_notifications_locked(self._reason)
		self._dispatch_notifications(*notifications)
		return True

	def reset(self) -> None:
		"""重置中断状态。

		XEYO 每次 submit 都会换新根节点；保留此兼容入口，但不尝试“复活”已经
		收到取消通知的子任务。这样不会把已停止的进程误认为可继续执行。
		"""
		with self._lock:
			self._aborted = False
			self._reason = ""
			self._notified = False

	def on_abort(self, listener: AbortListener) -> Callable[[], None]:
		"""注册一次性取消监听，返回移除函数。

		监听器异常被隔离；取消发生后注册会立即同步调用一次，避免竞态窗口。
		"""
		call_now = False
		reason = "aborted"
		with self._lock:
			if self.aborted:
				call_now = True
				reason = self.reason
			else:
				self._listeners.add(listener)
		if call_now:
			self._call_listener(listener, reason)

		def remove() -> None:
			with self._lock:
				self._listeners.discard(listener)

		return remove

	def child(self, *, label: str = "") -> "LinkedAbortController":
		"""创建本地可独立取消、但继承父节点取消的子节点。"""
		return LinkedAbortController(self, label=label)

	def _register_child(self, child: "AbortController") -> None:
		cancel_now = False
		reason = "aborted"
		with self._lock:
			if self.aborted:
				cancel_now = True
				reason = self.reason
			else:
				self._children.add(child)
		if cancel_now:
			child._abort_from_parent(reason)

	def _abort_from_parent(self, reason: str) -> None:
		with self._lock:
			if self._notified:
				return
			self._reason = str(reason or "aborted")
			notifications = self._take_notifications_locked(self._reason)
		self._dispatch_notifications(*notifications)

	def _take_notifications_locked(
		self, reason: str
	) -> tuple[tuple["AbortController", ...], tuple[AbortListener, ...], str]:
		# 复制后清空：监听器和子节点只收到一次通知，且回调在锁外执行。
		if self._notified:
			return (), (), reason
		self._notified = True
		children = tuple(self._children)
		listeners = tuple(self._listeners)
		self._listeners.clear()
		return children, listeners, reason

	def _dispatch_notifications(
		self,
		children: tuple["AbortController", ...],
		listeners: tuple[AbortListener, ...],
		reason: str,
	) -> None:
		# 该方法只能从 abort/_abort_from_parent 调用；通过局部快照避免回调
		# 观察到半更新状态。弱引用子节点可能在此处已经被 GC，直接跳过。
		for child in children:
			try:
				child._abort_from_parent(reason)
			except Exception:  # noqa: BLE001 — 取消不能被观察者阻断
				pass
		for listener in listeners:
			self._call_listener(listener, reason)

	@staticmethod
	def _call_listener(listener: AbortListener, reason: str) -> None:
		try:
			listener(reason)
		except Exception:  # noqa: BLE001 — 取消不能被观察者阻断
			pass

	def raise_if_aborted(self) -> None:
		"""如果已中断，则抛出带原因的 Aborted 异常。"""
		if self.aborted:
			raise Aborted(self.reason)


class CancellationScope(AbortController):
	"""语义化名称：用于 session/turn/job/process 生命周期树的根或中间节点。"""


class LinkedAbortController(AbortController):
	"""局部 abort：自身 abort 不污染父控制器，但继承父级 aborted。"""

	def __init__(self, parent: AbortController, *, label: str = "") -> None:
		self._parent = parent
		super().__init__(label=label)
		parent._register_child(self)

	@property
	def aborted(self) -> bool:
		return self._aborted or self._parent.aborted

	@property
	def reason(self) -> str:
		if self._aborted:
			return super().reason
		return self._parent.reason if self._parent.aborted else super().reason


__all__ = [
	"AbortController",
	"Aborted",
	"CancellationScope",
	"LinkedAbortController",
]
