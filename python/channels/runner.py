"""运行 agent 回合并仅返回最终 result 文本。"""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import Any

from channels.jobs import JobRecord, JobStore
from common.errors import friendly_error
from model.openai_compat import PROVIDER_PRESETS
from msgtypes.events import (
	AssistantDelta,
	FinalEvent,
	PermissionPendingEvent,
	PermissionResolvedEvent,
	ResultEvent,
	StoppedEvent,
	TaskStateEvent,
	ToolCallEvent,
	ToolResultEvent,
)
from server.session_pool import ModelConfig, SessionPool

OnComplete = Callable[[JobRecord], Awaitable[None] | None]
OnDelta = Callable[[str, str], Awaitable[None] | None]
OnStatus = Callable[[str, str], Awaitable[None] | None]
OnToolCall = Callable[[str, dict[str, Any], str], Awaitable[None] | None]
OnToolResult = Callable[[str, str, bool, str], Awaitable[None] | None]
OnPermission = Callable[[dict[str, Any], str], Awaitable[None] | None]
OnTaskState = Callable[[str, str], Awaitable[None] | None]

_runtime_model_cfg: ModelConfig | None = None


def set_runtime_model_config(cfg: ModelConfig | None) -> None:
	global _runtime_model_cfg
	_runtime_model_cfg = cfg


class SessionBusyError(RuntimeError):
	"""无法获取 session lease。"""


def default_remote_session_id() -> str:
	return os.environ.get("XEYO_REMOTE_SESSION_ID", "remote:default").strip() or "remote:default"


def resolve_remote_model_config() -> ModelConfig:
	"""无头远程路径的模型凭据：UI 启动时注入，否则读 env。"""
	if _runtime_model_cfg is not None and _runtime_model_cfg.api_key.strip():
		return _runtime_model_cfg
	api_key = (
		os.environ.get("XEYO_MODEL_API_KEY", "").strip()
		or os.environ.get("DEEPSEEK_API_KEY", "").strip()
	)
	if not api_key:
		raise RuntimeError(
			"missing model API key — set XEYO_MODEL_API_KEY or DEEPSEEK_API_KEY"
		)

	provider = (
		os.environ.get("XEYO_REMOTE_PROVIDER", "").strip()
		or os.environ.get("XEYO_PROVIDER", "").strip()
		or "deepseek"
	).lower()
	if provider not in PROVIDER_PRESETS:
		raise RuntimeError(f"unsupported provider: {provider}")

	model = (
		os.environ.get("XEYO_REMOTE_MODEL", "").strip()
		or os.environ.get("XEYO_MODEL", "").strip()
		or "deepseek-chat"
	)
	base_url = (
		os.environ.get("XEYO_REMOTE_BASE_URL", "").strip()
		or PROVIDER_PRESETS[provider].get("base_url")
		or "https://api.openai.com/v1"
	).rstrip("/")

	return ModelConfig(
		provider=provider,
		api_key=api_key,
		base_url=base_url,
		model=model,
	)


async def _maybe_await(result: object) -> None:
	if inspect.isawaitable(result):
		await result


async def run_final_only(
	pool: SessionPool,
	*,
	session_id: str,
	text: str,
	cfg: ModelConfig | None = None,
	on_delta: OnDelta | None = None,
	on_status: OnStatus | None = None,
	on_tool_call: OnToolCall | None = None,
	on_tool_result: OnToolResult | None = None,
	on_permission: OnPermission | None = None,
	on_task_state: OnTaskState | None = None,
	images: list[str] | None = None,
) -> str:
	"""提交 ``text`` 并仅返回 Final / Result / Stopped 摘要。

	微信等远程端只拿终稿；``on_delta`` / 工具回调供本机 UI 镜像。
	"""
	model_cfg = cfg or resolve_remote_model_config()
	lease_id = pool.try_begin(session_id)
	if lease_id is None:
		raise SessionBusyError(f"session busy: {session_id}")

	final_text = ""
	result_text = ""
	stopped_note = ""

	try:
		engine = pool.get_or_create(session_id, model_cfg)
		if pool.take_pending_interrupt(session_id):
			engine.interrupt()

		if images:
			stream = engine.submit(text, images=images)
		else:
			stream = engine.submit(text)
		async for ev in stream:
			if isinstance(ev, AssistantDelta):
				if ev.text and on_delta is not None:
					await _maybe_await(on_delta(ev.text, session_id))
			elif isinstance(ev, ToolCallEvent):
				if on_status is not None:
					await _maybe_await(on_status(ev.name, session_id))
				if on_tool_call is not None:
					await _maybe_await(on_tool_call(ev.name, ev.input, session_id))
			elif isinstance(ev, ToolResultEvent):
				if on_tool_result is not None:
					await _maybe_await(
						on_tool_result(ev.name, ev.output, bool(ev.is_error), session_id)
					)
			elif isinstance(ev, PermissionPendingEvent):
				if on_permission is not None:
					await _maybe_await(
						on_permission(
							{
								"kind": "permission_pending",
								"request_id": ev.request_id,
								"tool_name": ev.tool_name,
								"prompt": ev.prompt,
								"reason": ev.reason,
							},
							session_id,
						)
					)
			elif isinstance(ev, PermissionResolvedEvent):
				if on_permission is not None:
					await _maybe_await(
						on_permission(
							{
								"kind": "permission_resolved",
								"request_id": ev.request_id,
								"approved": bool(ev.approved),
								"reason": ev.reason,
							},
							session_id,
						)
					)
			elif isinstance(ev, TaskStateEvent):
				if on_task_state is not None:
					await _maybe_await(on_task_state(ev.task_status, session_id))
			elif isinstance(ev, FinalEvent):
				if ev.text:
					final_text = ev.text
			elif isinstance(ev, StoppedEvent):
				stopped_note = f"[stopped: {ev.reason}]"
			elif isinstance(ev, ResultEvent):
				if ev.result:
					result_text = ev.result
				elif ev.is_error and not stopped_note:
					stopped_note = f"[stopped: {ev.subtype}]"
	finally:
		pool.end(session_id, lease_id)

	return (result_text or final_text or stopped_note or "").strip()


class FinalOnlyRunner:
	"""按 session_id 入队任务并串行处理。"""

	def __init__(
		self,
		pool: SessionPool,
		store: JobStore,
		on_complete: OnComplete | None = None,
	) -> None:
		self._pool = pool
		self._store = store
		# 多播回调：ilink / filehelper 各自注册、各自注销，互不感知。
		self._on_complete_cbs: list[OnComplete] = (
			[on_complete] if on_complete is not None else []
		)
		self._on_delta: OnDelta | None = None
		self._on_status: OnStatus | None = None
		self._on_tool_call: OnToolCall | None = None
		self._on_tool_result: OnToolResult | None = None
		self._on_permission: OnPermission | None = None
		self._on_task_state: OnTaskState | None = None
		self._session_locks: dict[str, asyncio.Lock] = {}
		self._locks_guard = asyncio.Lock()
		self._tasks: set[asyncio.Task[None]] = set()

	def set_on_complete(self, on_complete: OnComplete | None) -> None:
		"""单值语义（兼容旧调用方）：替换为只有这一个回调。"""
		self._on_complete_cbs = [on_complete] if on_complete is not None else []

	def add_on_complete(self, on_complete: OnComplete) -> None:
		"""追加多播回调（ilink/filehelper 各自注册）。"""
		if on_complete not in self._on_complete_cbs:
			self._on_complete_cbs.append(on_complete)

	def remove_on_complete(self, on_complete: OnComplete) -> None:
		if on_complete in self._on_complete_cbs:
			self._on_complete_cbs.remove(on_complete)

	@property
	def _on_complete(self) -> OnComplete | None:
		"""兼容旧属性读取：返回首个回调或 None。"""
		return self._on_complete_cbs[0] if self._on_complete_cbs else None

	def set_on_delta(self, on_delta: OnDelta | None) -> None:
		self._on_delta = on_delta

	def set_on_status(self, on_status: OnStatus | None) -> None:
		self._on_status = on_status

	def set_on_tool_call(self, on_tool_call: OnToolCall | None) -> None:
		self._on_tool_call = on_tool_call

	def set_on_tool_result(self, on_tool_result: OnToolResult | None) -> None:
		self._on_tool_result = on_tool_result

	def set_on_permission(self, on_permission: OnPermission | None) -> None:
		self._on_permission = on_permission

	def set_on_task_state(self, on_task_state: OnTaskState | None) -> None:
		self._on_task_state = on_task_state

	def interrupt_session(self, session_id: str) -> bool:
		return self._pool.interrupt(session_id)

	def session_busy(self, session_id: str) -> bool:
		return self._pool.is_busy(session_id)

	async def _lock_for(self, session_id: str) -> asyncio.Lock:
		async with self._locks_guard:
			lock = self._session_locks.get(session_id)
			if lock is None:
				if len(self._session_locks) > 512:
					# 有界化：丢弃未被持有的锁，防 session_id 空间无限增长。
					for sid in [
						s
						for s, lk in self._session_locks.items()
						if not lk.locked()
					]:
						self._session_locks.pop(sid, None)
				lock = asyncio.Lock()
				self._session_locks[session_id] = lock
			return lock

	def enqueue(
		self,
		*,
		session_id: str,
		text: str,
		images: list[str] | None = None,
		reply_peer: str | None = None,
		reply_ctx: str | None = None,
	) -> str:
		from prompt.fence import fence_remote_user_text

		# γ4：微信/远程入站标记为不可信数据（桌面 GUI 不走此路径）
		safe_text = fence_remote_user_text(text or "", source="wechat")
		rec = self._store.create(
			session_id=session_id,
			text=safe_text,
			images=images,
			reply_peer=reply_peer,
			reply_ctx=reply_ctx,
		)
		task = asyncio.create_task(self._process(rec.job_id))
		if not hasattr(self, "_tasks"):
			self._tasks = set()
		self._tasks.add(task)
		task.add_done_callback(self._tasks.discard)
		return rec.job_id

	async def _process(self, job_id: str) -> None:
		rec = self._store.get(job_id)
		if rec is None:
			return
		lock = await self._lock_for(rec.session_id)
		async with lock:
			self._store.mark_running(job_id)

			async def _on_permission(payload: dict[str, Any], session_id: str) -> None:
				if self._on_permission is not None:
					await _maybe_await(self._on_permission(payload, session_id))
				kind = payload.get("kind")
				if kind == "permission_pending":
					self._store.mark_waiting_permission(job_id)
				elif kind == "permission_resolved":
					self._store.mark_running(job_id)

			try:
				final = await run_final_only(
					self._pool,
					session_id=rec.session_id,
					text=rec.text,
					on_delta=self._on_delta,
					on_status=self._on_status,
					on_tool_call=self._on_tool_call,
					on_tool_result=self._on_tool_result,
					on_permission=_on_permission,
					on_task_state=self._on_task_state,
					images=rec.images,
				)
				self._store.mark_done(job_id, final)
			except Exception as e:  # noqa: BLE001
				self._store.mark_error(job_id, friendly_error(e))
			await self._emit_complete(job_id)

	async def _emit_complete(self, job_id: str) -> None:
		rec = self._store.get(job_id)
		if rec is None:
			return
		callbacks = list(self._on_complete_cbs)
		for cb in callbacks:
			try:
				result = cb(rec)
				if inspect.isawaitable(result):
					await result
			except Exception:
				pass
