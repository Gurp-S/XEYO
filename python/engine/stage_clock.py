"""stage_clock — 旁路(P0):回合内阶段计时纯件(无引擎依赖)。

query_loop 逐段计时钩子(收口后接入)与本地诊断共用。只做时间采集,
不负责落审计(调用方在 `finish()` 时拿到 dict 自行 emit/写日志)。
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


class StageClock:
	"""命名阶段计时(ms)。支持嵌套 contextmanager 与显式 add/lap。

	- ``with clock.stage("assemble"): ...`` — 常规用法,段耗时自动累计;
	- ``clock.lap("first_byte")`` — 打点:距 __init__/reset 的累计耗时;
	- ``clock.sink`` — finish() 时收到完整 {name: ms} 报告(接审计)。
	"""

	def __init__(
		self,
		*,
		sink: Callable[[dict[str, float]], None] | None = None,
	) -> None:
		self._t0 = time.monotonic()
		self._stages: dict[str, float] = {}
		self._order: list[str] = []
		self._stack: list[tuple[str, float]] = []
		self._finished = False
		self.sink = sink

	def _add(self, name: str, ms: float) -> None:
		if name not in self._stages:
			self._stages[name] = 0.0
			self._order.append(name)
		self._stages[name] += ms

	@contextmanager
	def stage(self, name: str) -> Iterator[None]:
		"""命名阶段计时;同名多次进入则累计。异常也记录耗时。"""
		start = time.monotonic()
		self._stack.append((name, start))
		try:
			yield
		finally:
			_, s = self._stack.pop()
			self._add(name, (time.monotonic() - s) * 1000.0)

	def add(self, name: str, ms: float) -> None:
		"""外部提供耗时(如子进程返回的墙钟)直接累计。"""
		self._add(name, max(0.0, float(ms)))

	def lap(self, name: str) -> float:
		"""打点:记录自起点到此刻的累计 ms(适合『首字节』类单点)。"""
		ms = (time.monotonic() - self._t0) * 1000.0
		self._add(name, ms)
		return ms

	def result(self) -> dict[str, float]:
		"""按首次进入顺序返回 {name: 累计 ms}。"""
		return {n: round(self._stages.get(n, 0.0), 3) for n in self._order}

	def finish(self) -> dict[str, float]:
		"""取结果;若配了 sink 则回调一次(幂等)。"""
		out = self.result()
		if self.sink is not None and not self._finished:
			self._finished = True
			try:
				self.sink(dict(out))
			except Exception:  # noqa: BLE001 — 审计侧失败不阻塞主路径
				pass
		return out

	def reset(self) -> None:
		self._t0 = time.monotonic()
		self._stages.clear()
		self._order.clear()
		self._stack.clear()
		self._finished = False


def to_summary_report(report: dict[str, float]) -> str:
	"""诊断用单行/多行文本(不依赖 prof_stats,保持零耦合)。"""
	if not report:
		return "(no stages)"
	lines = [f"{name:<18} {ms:>10.2f} ms" for name, ms in report.items()]
	total = sum(report.values())
	lines.append(f"{'TOTAL':<18} {total:>10.2f} ms")
	return "\n".join(lines)
