"""Synthetic round channel（41/42 共用）— 请求环境快照 + ASGI 自调用提交。

41 号 goal 轮与 42 号 job 唤醒轮共用同一合成轮通道（42 号 §3.2）：载荷不同、
记账不同（goal cap vs 共享唤醒预算），但「复用整条 submit 管线」的机制一致。

- 请求环境（model/api_key/workspace 等）来自最近一次人类请求的内存快照——
  server 无 key 无法自过 Authorization 闸；仅内存、随进程消失（41 号开放 #3）。
- **分离式 ASGI 自调用**（2026-09-05 事故修正）：旧实现用 httpx ASGITransport，
  其 ``await self.app(...)`` 内联执行且**全量缓冲响应体**——整个 turn 跑在
  submit 调用方 task 里，导致 ① chat.py 让位逻辑自取消合成轮 ② admit 落在
  turn 结束后与 mark_candidate CAS 竞速 ③ settlement ``_schedule`` 见 pending
  未 done 而 skip（链条每轮停摆）。现改为裸 ASGI 调用：拿到
  ``http.response.start``（turn 将随 body 迭代惰性启动）即返回，随后发出
  ``http.disconnect`` 让 SSE 泵停止——turn 在 TurnRunner detached 续跑（T31
  语义与 41/42 号 docstring 对齐）。
- ``X-Xeyo-Surface`` 区分来源（goal-driver / job-wake / inbox），GUI 与日志可归因。
- busy 语义：仅 inbox 面（真实用户消息）``queue_if_busy=True`` 走 202 排队；
  goal-driver / job-wake 面 busy 直接 409（合成轮让位于人类 turn，由下一次
  settlement 重新预约，轮号/唤醒预算语义不变形）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

_logger = logging.getLogger("xeyo.synthetic")

#: 请求环境 stash（per-session；仅内存）。
_REQUEST_ENVS: dict[str, dict[str, Any]] = {}

#: 等 ``http.response.start`` 的上限（handler 需完成 engine 创建等前置工作）。
_RESPONSE_START_TIMEOUT_S = 20.0

#: 在途 app task 强引用（防 GC；done 回调自清）。
_APP_TASKS: set[asyncio.Task] = set()


def note_request_env(session_id: str, env: dict[str, Any]) -> None:
	"""记录最近一次人类请求的模型环境（api_key 含在内；仅内存、随进程消失）。"""
	try:
		_REQUEST_ENVS[session_id] = dict(env or {})
	except Exception:  # noqa: BLE001
		pass


def env_for(session_id: str) -> dict[str, Any] | None:
	env = _REQUEST_ENVS.get(session_id)
	return env if isinstance(env, dict) and env.get("model") else None


def clear_request_env(session_id: str) -> None:
	"""单会话清环境快照（回溯 / 删除会话时调用，防陈旧 env 被合成轮复用）。"""
	try:
		_REQUEST_ENVS.pop((session_id or "").strip(), None)
	except Exception:  # noqa: BLE001
		pass


def clear_request_envs() -> None:
	_REQUEST_ENVS.clear()


def _app_task_done(task: asyncio.Task) -> None:
	"""在途 app task 收尾：清引用 + 记录未处理异常（分离式调用的兜底观测）。"""
	_APP_TASKS.discard(task)
	if task.cancelled():
		return
	exc = task.exception()
	if exc is not None:
		_logger.debug("synthetic asgi app ended with exception", exc_info=exc)


async def _invoke_asgi_head(
	app: Any,
	scope: dict[str, Any],
	body: bytes,
) -> int | None:
	"""运行 ASGI app 到 ``http.response.start`` 即返回状态码；不等响应体完成。

	- 拿到响应头后立即发 ``http.disconnect``：SSE 泵（chat 的 event_stream 生成器）
	  在下一帧/tick 检测断开并退出，turn 本体在 TurnRunner detached 续跑。
	- 超时未见响应头 → 取消 app（此时尚未进入 body 迭代，turn 未启动，取消安全）。
	- 返回 None = 未拿到响应头（超时 / app 异常）；调用方按 False 处理。
	"""
	status: dict[str, int] = {}
	got_start = asyncio.Event()
	disconnected = asyncio.Event()
	body_sent = False

	async def receive() -> dict[str, Any]:
		nonlocal body_sent
		if not body_sent:
			body_sent = True
			return {"type": "http.request", "body": body, "more_body": False}
		# Starlette 的 request.is_disconnected() 用「已取消的 CancelScope」探测
		# receive：断开已置位时必须**同步**返回（不经 await 悬挂），探测才读得到。
		if disconnected.is_set():
			return {"type": "http.disconnect"}
		await disconnected.wait()
		return {"type": "http.disconnect"}

	async def send(message: dict[str, Any]) -> None:
		if message.get("type") == "http.response.start":
			try:
				status["code"] = int(message.get("status") or 0)
			except (TypeError, ValueError):
				status["code"] = 0
			got_start.set()

	task = asyncio.create_task(app(scope, receive, send))
	_APP_TASKS.add(task)
	task.add_done_callback(_app_task_done)
	try:
		try:
			await asyncio.wait_for(
				got_start.wait(), timeout=_RESPONSE_START_TIMEOUT_S
			)
		except asyncio.TimeoutError:
			if got_start.is_set():
				pass  # 头已到（竞态窗口），按成功处理
			else:
				if not task.done():
					task.cancel()
				_logger.warning(
					"synthetic asgi no response start in %.1fs path=%s",
					_RESPONSE_START_TIMEOUT_S,
					scope.get("path", ""),
				)
				return None
		# 响应头已到：turn 将随 body 迭代启动。通知断开 → SSE 泵停，turn detached。
		if not task.done():
			disconnected.set()
		return status.get("code")
	except Exception:  # noqa: BLE001 — 调用方异常全隔离（照 submit 降级铁律）
		_logger.debug("synthetic asgi invoke failed", exc_info=True)
		return None


async def submit_synthetic(
	session_id: str,
	user_text: str,
	*,
	surface: str,
	extra_headers: dict[str, str] | None = None,
	media_refs: list[str] | None = None,
	message_id: str | None = None,
) -> bool:
	"""以最近人类请求的环境自调用 chat 管线。返回 True = turn 已被引擎接受。

	分离式语义（2026-09-05 修正）：拿到 ``http.response.start``（200/202）即返回，
	**不等待轮次结束**——turn 在 TurnRunner detached 续跑（T31：客户端断流 ≠ 停
	turn）。调用方（goal driver / inbox drain）因此不被轮次时长阻塞，settlement
	的 ``_schedule`` 也不再被未完成的 pending 卡住。

	``queue_if_busy`` 仅 inbox 面开启：busy 时 202 排队（消息回 FIFO）；
	goal-driver / job-wake 面 busy 返回 409 → False（合成轮让位，等下次 settlement）。

	模型环境缺失 / 未拿到响应头 / 状态码非 200/202 → False。
	"""
	env = env_for(session_id)
	if env is None:
		_logger.warning(
			"synthetic round missing request env session=%s surface=%s（尚无人类请求记录）",
			session_id,
			surface,
		)
		return False
	try:
		from server.app import app
	except Exception:  # noqa: BLE001
		_logger.warning(
			"synthetic submit unavailable session=%s surface=%s",
			session_id,
			surface,
			exc_info=True,
		)
		return False

	headers = {
		"Authorization": f"Bearer {env.get('api_key') or 'local'}",
		"X-Session-Id": session_id,
		"X-Xeyo-Surface": surface,
		**(extra_headers or {}),
	}
	payload: dict[str, Any] = {
		"model": env.get("model"),
		"messages": [{"role": "user", "content": user_text}],
		"session_id": session_id,
		"stream": True,
		# busy 语义按面区分（见模块 docstring）：仅 inbox 面排队。
		"queue_if_busy": surface == "inbox",
	}
	if media_refs:
		payload["media_refs"] = list(media_refs)
	if message_id:
		# 客户端乐观气泡 id：chat 管线据此把投递消息 id 回传给 GUI。
		payload["messages"][0]["id"] = message_id
	for key in (
		"provider",
		"base_url",
		"thinking",
		"reasoning_effort",
		"max_budget_usd",
		"context_limit",
		"permission_preset",
		"permission_mode",
		"workspace",
	):
		if env.get(key) is not None:
			payload[key] = env[key]

	body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
	header_pairs: list[tuple[bytes, bytes]] = [
		(b"content-type", b"application/json"),
		(b"content-length", str(len(body)).encode("ascii")),
	]
	for k, v in headers.items():
		header_pairs.append((k.lower().encode("ascii"), str(v).encode("utf-8")))

	scope: dict[str, Any] = {
		"type": "http",
		"asgi": {"version": "3.0", "spec_version": "2.3"},
		"http_version": "1.1",
		"method": "POST",
		"scheme": "http",
		"path": "/v1/chat/completions",
		"raw_path": b"/v1/chat/completions",
		"query_string": b"",
		"root_path": "",
		"headers": header_pairs,
		"client": ("127.0.0.1", 0),
		"server": ("xeyo-synthetic", 80),
	}
	_logger.info("synthetic submit session=%s surface=%s", session_id, surface)
	try:
		code = await _invoke_asgi_head(app, scope, body)
	except Exception:  # noqa: BLE001
		_logger.debug(
			"synthetic submit failed session=%s surface=%s",
			session_id,
			surface,
			exc_info=True,
		)
		return False
	started = code in (200, 202)
	if not started:
		_logger.warning(
			"synthetic submit rejected session=%s surface=%s status=%s",
			session_id,
			surface,
			code,
		)
	return started
