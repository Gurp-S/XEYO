from __future__ import annotations

# 中断控制器

class Aborted(Exception):
	"""循环内检测到中断时抛出，由 query_loop 转成 StoppedEvent。"""


class AbortController:
	def __init__(self) -> None:
		"""中断控制器。"""
		self._aborted = False

	@property
	def aborted(self) -> bool:
		"""是否已中断。"""
		return self._aborted

	def abort(self) -> None:
		"""中断循环。"""
		self._aborted = True

	def reset(self) -> None:
		"""重置中断状态。"""
		self._aborted = False

	def raise_if_aborted(self) -> None:
		"""如果已中断，则抛出 Aborted 异常。"""
		if self.aborted:
			raise Aborted()


class LinkedAbortController(AbortController):
	"""单工具超时用的局部 abort：自身 abort 不污染父控制器，但继承父级 aborted。"""

	def __init__(self, parent: AbortController) -> None:
		super().__init__()
		self._parent = parent

	@property
	def aborted(self) -> bool:
		return self._aborted or self._parent.aborted
