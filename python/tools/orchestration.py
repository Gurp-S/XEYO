"""
工具运行器，对齐 Claude Code ``toolOrchestration.ts``。

设计要点：
- 按 ``is_concurrency_safe`` 分区（默认 False — 失败即关闭，按顺序执行）。
- 连续的安全工具可并发执行（上限 10，可由环境变量调整）。
- 不安全工具（Edit/Write/Bash/…）始终单独、按序执行，避免冲突。
- 单工具超时（``XEYO_TOOL_TIMEOUT_S``，默认 300）；超时用 LinkedAbort 杀子进程，不影响同批兄弟。
- 安全批次 ``gather(return_exceptions=True)``：单工具异常不拖垮整批。
- 可选 ``result_q``：工具一完成就投递结果，供 query_loop 在兄弟仍在跑时挂起 Ask/Permission。
"""

from __future__ import annotations

import asyncio
import os
import logging
import time
from typing import TYPE_CHECKING, Any

from engine.abort import Aborted, AbortController, LinkedAbortController
from common.rwlock import RWLock
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult, tool_flag

if TYPE_CHECKING:
	from tools.tool_registry import ToolRegistry
	from engine.permission_coordinator import PermissionCoordinator


def _max_concurrency() -> int:
	"""
	获取最大并发执行数量。

	优先从环境变量 XEYO_MAX_TOOL_USE_CONCURRENCY 读取，若未设置或无效则返回默认值 10。
	确保返回值至少为 1，避免无意义的零并发。
	"""
	raw = os.environ.get("XEYO_MAX_TOOL_USE_CONCURRENCY", "").strip()
	if not raw:
		return 10
	try:
		return max(1, int(raw))
	except ValueError:
		return 10


def _tool_timeout_s() -> float | None:
	"""单工具 deadline（秒）。默认 300；``XEYO_TOOL_TIMEOUT_S=0`` 表示不限时。"""
	raw = os.environ.get("XEYO_TOOL_TIMEOUT_S", "300").strip()
	if not raw:
		return 300.0
	try:
		value = float(raw)
	except ValueError:
		return 300.0
	if value <= 0:
		return None
	return value


def _progress_interval_s() -> float:
	"""心跳间隔；``XEYO_TOOL_PROGRESS_S=0`` 关闭。默认 5s。"""
	raw = os.environ.get("XEYO_TOOL_PROGRESS_S", "5").strip()
	if not raw:
		return 5.0
	try:
		value = float(raw)
	except ValueError:
		return 5.0
	return max(0.0, value)


def is_concurrency_safe(registry: "ToolRegistry", name: str) -> bool:
	"""
	判断指定名称的工具是否支持并发安全。

	查找注册表中的工具，读取 ``is_concurrency_safe``；缺失或异常时默认 False。
	"""
	tool = registry.get(name)
	if tool is None:
		return False
	return tool_flag(tool, "is_concurrency_safe", default=False)


def partition_tool_calls(
	registry: "ToolRegistry",
	tool_uses: list[ToolUse],
) -> list[tuple[bool, list[ToolUse]]]:
	"""
	根据并发安全性将工具调用列表分区。

	遍历 tool_uses，若当前工具安全且上一个批次也是安全批次，则追加到同一批次；
	否则新建一个批次（安全或非安全）。这样形成连续安全工具合并为一个批次，
	而不安全工具则每个单独成批（或连续不安全工具也各自独立成批，因为不安全时总是新建）。

	返回值：列表，每个元素为 (是否安全, 该批次的 ToolUse 列表)。
	"""
	batches: list[tuple[bool, list[ToolUse]]] = []
	for tu in tool_uses:
		safe = is_concurrency_safe(registry, tu.name)
		# 如果安全且上一个批次也是安全的，则追加到当前批次
		if safe and batches and batches[-1][0]:
			batches[-1][1].append(tu)
		else:
			# 否则新建批次（安全或非安全）
			batches.append((safe, [tu]))
	return batches


def _emit_result(
	result_q: asyncio.Queue[Any] | None,
	tu: ToolUse,
	result: ToolResult,
) -> None:
	if result_q is None:
		return
	try:
		result_q.put_nowait((tu, result))
	except Exception:  # noqa: BLE001
		# 投递失败 = 前端永远收不到该工具结果；必须留痕。
		logging.getLogger(__name__).warning(
			"tool result dropped (queue full/closed) tool=%s id=%s",
			tu.name,
			tu.id,
		)


async def _run_one_tool(
	registry: "ToolRegistry",
	tu: ToolUse,
	abort: AbortController,
	coordinator: "PermissionCoordinator | None",
	progress_q: asyncio.Queue[Any] | None = None,
	result_q: asyncio.Queue[Any] | None = None,
	lock: RWLock | None = None,
) -> ToolResult:
	"""执行单个工具：局部 abort + 可选超时 + 可选进度心跳 + 读写锁（T2）。"""
	from msgtypes.events import ToolProgressEvent
	from tools.progress_sink import reset_progress_sink, set_progress_sink

	local = LinkedAbortController(abort)
	timeout = _tool_timeout_s()
	interval = _progress_interval_s()
	started = time.monotonic()
	heartbeat: asyncio.Task[None] | None = None

	def _put_progress(ev: Any) -> None:
		if progress_q is None:
			return
		if getattr(ev, "tool_use_id", None) in ("", None) and hasattr(ev, "tool_use_id"):
			try:
				ev.tool_use_id = tu.id
			except Exception:  # noqa: BLE001
				pass
		try:
			progress_q.put_nowait(ev)
		except Exception:  # noqa: BLE001
			logging.getLogger(__name__).debug(
				"tool progress dropped tool=%s", getattr(ev, "name", "?")
			)

	sink_token = set_progress_sink(_put_progress if progress_q is not None else None)

	async def _beat() -> None:
		if progress_q is None or interval <= 0:
			return
		while True:
			await asyncio.sleep(interval)
			if abort.aborted or local.aborted:
				return
			elapsed_ms = int((time.monotonic() - started) * 1000)
			try:
				progress_q.put_nowait(
					ToolProgressEvent(
						name=tu.name,
						tool_use_id=tu.id,
						message=f"{tu.name} still running…",
						elapsed_ms=elapsed_ms,
					)
				)
			except Exception:
				return

	if progress_q is not None and interval > 0:
		heartbeat = asyncio.create_task(_beat())

	try:
		coro = registry.run(tu, local, coordinator=coordinator)
		if lock is not None:
			# T2：并发安全工具共享读锁；不安全工具独占写锁（与分区判定同源）。
			if is_concurrency_safe(registry, tu.name):
				guard = lock.read_lock()
			else:
				guard = lock.write_lock()
			async with guard:
				if timeout is None:
					result = await coro
				else:
					result = await asyncio.wait_for(coro, timeout=timeout)
		else:
			if timeout is None:
				result = await coro
			else:
				result = await asyncio.wait_for(coro, timeout=timeout)
		_emit_result(result_q, tu, result)
		return result
	except asyncio.TimeoutError:
		local.abort()
		result = ToolResult(
			content=f"tool timed out after {timeout:g}s: {tu.name}",
			is_error=True,
			metadata={"timeout_s": timeout, "tool_name": tu.name},
		)
		_emit_result(result_q, tu, result)
		return result
	except asyncio.CancelledError:
		# T2：用户中止（turn 被取消）→ 确定性结果，非 error；不再落
		# "missing result" 错误占位。
		elapsed = time.monotonic() - started
		result = ToolResult(
			content=f"aborted by user after {elapsed:.1f}s",
			is_error=False,
			metadata={"cancelled": True, "tool_name": tu.name},
		)
		_emit_result(result_q, tu, result)
		return result
	except Aborted:
		raise
	except Exception as exc:
		result = ToolResult(
			content=f"tool error: {type(exc).__name__}: {exc}",
			is_error=True,
			metadata={"tool_name": tu.name},
		)
		_emit_result(result_q, tu, result)
		return result
	finally:
		reset_progress_sink(sink_token)
		if heartbeat is not None:
			heartbeat.cancel()
			try:
				await heartbeat
			except asyncio.CancelledError:
				pass


async def run_tools_partitioned(
	registry: "ToolRegistry",
	tool_uses: list[ToolUse],
	abort: AbortController,
	coordinator: "PermissionCoordinator | None" = None,
	progress_q: asyncio.Queue[Any] | None = None,
	result_q: asyncio.Queue[Any] | None = None,
) -> list[ToolResult]:
	"""
	执行给定的工具调用列表，并保持原始顺序返回结果。

	策略：
	1. 按 partition_tool_calls 分成批次。
	2. 安全批次（含多个工具）并发执行，使用信号量控制并发数（上限由 _max_concurrency 决定）。
	   批次内每个工具都检查 abort 信号，若被中止则提前退出。
	   gather(return_exceptions=True)：单工具失败不影响同批兄弟结果。
	3. 非安全批次（或只有一个工具的安全批次）顺序执行。
	4. 最终结果按原始 tool_uses 的顺序填充，缺失的结果用错误占位。
	5. 若提供 result_q：每个工具一完成就 put (ToolUse, ToolResult)。

	参数：
		registry: 工具注册表，用于执行工具。
		tool_uses: 待执行工具调用列表。
		abort: 中止控制器，用于响应外部取消信号。

	返回：
		与 tool_uses 顺序对应的 ToolResult 列表。
	"""
	if not tool_uses:
		return []

	# 占位结果列表，按原始索引存放结果，确保输出顺序稳定
	out: list[ToolResult | None] = [None] * len(tool_uses)
	# 通过 id(tu) 快速映射到原始索引，避免因对象哈希问题或重复而混淆
	index_of = {id(tu): i for i, tu in enumerate(tool_uses)}
	limit = _max_concurrency()
	# T2：读写锁——安全批共享读、不安全批独占写（每次调用独立，无跨批泄漏）。
	rw = RWLock()

	for safe, batch in partition_tool_calls(registry, tool_uses):
		abort.raise_if_aborted()  # 批次开始前检查中止信号

		if safe and len(batch) > 1:
			# 安全且多于一个工具：并发执行
			sem = asyncio.Semaphore(limit)  # 并发限制

			async def _one(tu: ToolUse) -> tuple[int, ToolResult]:
				"""单个工具执行包装，负责获取信号量并执行，返回 (原始索引, 结果)。"""
				async with sem:
					abort.raise_if_aborted()  # 执行前再次检查
					res = await _run_one_tool(
						registry, tu, abort, coordinator, progress_q, result_q,
						lock=rw,
					)
					return index_of[id(tu)], res

			# 并发执行；单工具异常映射为错误结果，不丢弃同批其它结果
			pairs = await asyncio.gather(
				*[_one(tu) for tu in batch],
				return_exceptions=True,
			)
			for item in pairs:
				if isinstance(item, Aborted):
					raise item
				if isinstance(item, BaseException):
					# _one 外层极少见失败：无法定位索引时跳过（下方 missing 占位）
					continue
				idx, res = item
				out[idx] = res
		else:
			# 非安全批次或单工具安全批次：顺序执行（写锁独占）
			for tu in batch:
				abort.raise_if_aborted()
				out[index_of[id(tu)]] = await _run_one_tool(
					registry, tu, abort, coordinator, progress_q, result_q,
					lock=rw,
				)

	# 确保所有位置都有结果，若因异常未能填充则用错误占位
	return [
		r if r is not None else ToolResult(content="missing result", is_error=True)
		for r in out
	]
