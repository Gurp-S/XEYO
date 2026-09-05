"""File Helper 单例：启停桥、接 runner、镜像事件、SSE 广播、供 HTTP / UI 查询。"""



from __future__ import annotations



import asyncio

from typing import Any



from channels.base import InboundMessage

from channels.filehelper import SESSION_ID

from channels.filehelper.bridge import FileHelperBridge, filehelper_autostart

from channels.filehelper.channel import FileHelperChannel

from channels.filehelper import broadcast as fh_broadcast

from channels.filehelper.inbound_queue import InboundQueue

from channels.filehelper.commands import with_screenshot_nudge

from channels.filehelper.prefix import is_own_reply, xeyo_reply

from common.errors import safe_error_text

from channels.jobs import JobRecord, JobStore

from channels.mirror import ChannelMirror

from channels.runner import FinalOnlyRunner, set_runtime_model_config

from server.session_pool import ModelConfig



_bridge = FileHelperBridge()

_channel: FileHelperChannel | None = None

_runner_ref: FinalOnlyRunner | None = None

_prev_complete = None

# 事件/流/工具事件镜像状态收归 ChannelMirror（测试与 conftest 通过 _mirror 访问）。
_mirror = ChannelMirror(broadcast=fh_broadcast, session_prefix="filehelper:")

_inbound_q = InboundQueue()





def get_bridge() -> FileHelperBridge:

	return _bridge





def _state_payload() -> dict[str, Any]:

	b = _bridge

	return {

		"state": b.state,

		"logged_in": b.logged_in,

		"has_qr": b.qr_png() is not None,

		"qr_rev": b.qr_rev,

		"error": b.error,

		"hint": b.hint,

		"session_id": SESSION_ID,

		"streaming": _stream_active,

	}





def _broadcast_state() -> None:

	payload = _state_payload()

	if _mirror.stream_active:

		payload["stream_len"] = len(_mirror._stream_text)

		if _mirror._stream_status:

			payload["stream_status"] = _mirror._stream_status

	fh_broadcast.publish("state", payload)





def _push_event(kind: str, text: str, *, command: str | None = None) -> dict[str, Any]:

	return _mirror.push_event(kind, text, command=command)





def _broadcast_stream(*, reset: bool = False) -> None:

	_mirror.broadcast_stream(reset=reset)





def events_since(after_id: str = "") -> list[dict[str, Any]]:

	return _mirror.events_since(after_id)





def status_payload(

	store: JobStore | None = None,

	*,

	after_id: str = "",

	omit_jobs: bool = False,

	stream_from: int | None = None,

) -> dict[str, object]:

	b = _bridge

	payload: dict[str, object] = {

		"state": b.state,

		"logged_in": b.logged_in,

		"has_qr": b.qr_png() is not None,

		"qr_rev": b.qr_rev,

		"error": b.error,

		"hint": b.hint,

		"session_id": SESSION_ID,

		"events": _mirror.events_since(after_id),

		"streaming": _mirror.stream_active,

	}

	if not omit_jobs:

		jobs: list[dict[str, object]] = []

		if store is not None:

			jobs = [r.to_public() for r in store.recent(8, session_id=SESSION_ID)]

		payload["recent_jobs"] = jobs

	if _mirror.stream_active:

		payload.update(_mirror.stream_payload_section(stream_from))

	return payload





async def _begin_inbound(text: str, channel: FileHelperChannel) -> None:

	_mirror.begin_stream()

	_broadcast_state()

	await channel.handle_inbound(

		InboundMessage(
			text=with_screenshot_nudge(text),
			session_id=SESSION_ID,
			sender_id="filehelper",
		)

	)





async def _drain_inbound_queue(channel: FileHelperChannel, runner: FinalOnlyRunner) -> None:

	if runner.session_busy(SESSION_ID):

		return

	nxt = _inbound_q.pop()

	if nxt:

		await _begin_inbound(nxt, channel)





async def start(

	runner: FinalOnlyRunner,

	store: JobStore,

	*,

	model_cfg: ModelConfig | None = None,

) -> None:

	global _channel, _prev_complete, _runner_ref

	if _bridge.state in {"starting", "qr", "scanned", "logged_in"}:

		return

	if _bridge.state == "error":

		await _bridge.stop()



	from channels.ilink.service import stop_if_running as _stop_ilink

	await _stop_ilink(runner)



	_mirror.reset_data()

	_inbound_q.clear()

	_runner_ref = runner

	if model_cfg is not None:

		set_runtime_model_config(model_cfg)



	channel = FileHelperChannel(runner, _bridge)

	_channel = channel



	async def on_inbound(text: str) -> None:

		if is_own_reply(text):

			return

		_push_event("inbound", text)

		if runner.session_busy(SESSION_ID):

			pos = _inbound_q.push(text)

			_mirror.begin_stream()

			_mirror.set_status(f"排队中（{pos}）…" if pos > 1 else "排队中…")

			_broadcast_state()

			try:

				await _bridge.send_text(

					xeyo_reply(f"上一轮还在跑，你的消息已排队（#{pos}）。")

				)

			except Exception:

				pass

			return

		await _begin_inbound(text, channel)



	def on_delta(chunk: str, session_id: str) -> None:

		if not session_id.startswith("filehelper:"):

			return

		_mirror.append_delta(chunk)



	def on_status(name: str, session_id: str) -> None:

		if not session_id.startswith("filehelper:"):

			return

		_mirror.set_status(f"使用 {name}…")



	def _emit_ui_tool(

		kind: str,

		*,

		name: str,

		input: dict[str, Any] | None = None,

		output: str = "",

		is_error: bool = False,

	) -> None:

		_mirror.emit_ui_tool(kind, name=name, input=input, output=output, is_error=is_error)



	def on_tool_call(name: str, input: dict[str, Any], session_id: str) -> None:

		if not session_id.startswith("filehelper:"):

			return

		_emit_ui_tool("tool_call", name=name, input=input)



	def on_tool_result(

		name: str, output: str, is_error: bool, session_id: str

	) -> None:

		if not session_id.startswith("filehelper:"):

			return

		_emit_ui_tool("tool_result", name=name, output=output, is_error=is_error)



	def on_permission(payload: dict[str, Any], session_id: str) -> None:

		if not session_id.startswith("filehelper:"):

			return

		kind = str(payload.get("kind") or "")

		if kind == "permission_pending":

			_mirror.set_status("等待你确认…")

			prompt = str(payload.get("prompt") or "")

			_push_event(
				"permission",
				prompt,
				command=None,
				request_id=str(payload.get("request_id") or ""),
				tool_name=str(payload.get("tool_name") or ""),
				reason=str(payload.get("reason") or ""),
			)

			async def _notify() -> None:

				try:

					await _bridge.send_text(
						xeyo_reply(
							f"{prompt}\n回复 /allow（允许）或 /deny（拒绝）来确认。"
						)
					)

				except Exception:

					pass

			asyncio.create_task(_notify())

		else:

			_mirror.set_status("")

		_broadcast_stream(reset=True)



	async def on_command(name: str, raw: str) -> str | None:

		_push_event("inbound", raw, command=name)

		if name == "stop":

			ok = runner.interrupt_session(SESSION_ID)

			reply = "已请求停止当前任务" if ok else "当前没有正在运行的任务"

			_push_event("outbound", xeyo_reply(reply), command=name)

			return reply

		if name == "status":

			busy = runner.session_busy(SESSION_ID)

			try:

				from engine.workspace_context import get_cwd



				cwd = get_cwd()

			except Exception:

				cwd = ""

			reply = (

				f"状态：{_bridge.state}\n"

				f"任务：{'进行中' if busy else '空闲'}\n"

				f"目录：{cwd or '(未设置)'}"

			)

			_push_event("outbound", xeyo_reply(reply), command=name)

			return reply

		if name == "cwd":

			try:

				from engine.workspace_context import get_cwd



				cwd = get_cwd()

			except Exception as e:  # noqa: BLE001

				cwd = f"(无法读取: {e})"

			_push_event("outbound", xeyo_reply(cwd), command=name)

			return cwd

		if name in {"allow", "deny"}:

			from permissions.store import default_permission_store



			approved = name == "allow"

			item = default_permission_store().pending_for_session(SESSION_ID)

			if item is None:

				reply = "当前没有待确认的操作"

			else:

				ok = default_permission_store().resolve(

					item.request_id, approved, actor="filehelper"

				)

				reply = (

					"已允许，继续执行。"

					if ok and approved

					else "已拒绝该操作。"

					if ok

					else "请求已处理过或已过期。"

				)

			_push_event("outbound", xeyo_reply(reply), command=name)

			return reply

		if name == "help":
			from channels.filehelper.commands import help_text

			_push_event("outbound", xeyo_reply(help_text()), command=name)
			return None
		if name in {"rule", "doctor", "proposals"}:
			from channels.filehelper.commands import handle_instruction_command, parse_command

			hit = parse_command(raw)
			arg = hit.arg if hit is not None else ""
			reply = handle_instruction_command(name, arg) or "无法处理该指令"
			_push_event("outbound", xeyo_reply(reply), command=name)
			return reply

		return None



	async def on_complete(rec: JobRecord) -> None:

		body = ""

		if rec.session_id.startswith("filehelper:"):

			# T34：错误回帖经安全过滤，内部异常痕迹不出通道。
			body = (
				rec.final_text
				if rec.status == "done"
				else safe_error_text(rec.error or "", fallback="")
			)

			_mirror.reset_stream()

			_broadcast_state()



		if body:

			reply = xeyo_reply(body)

			_push_event("outbound", reply)



		async def _send_wechat() -> None:

			try:

				await channel.send_job_result(rec)

			except Exception as e:  # noqa: BLE001

				import logging

				logging.getLogger(__name__).warning(

					"filehelper wechat send follow-up failed: %s", e

				)



		asyncio.create_task(_send_wechat())

		await _drain_inbound_queue(channel, runner)



	_prev_complete = on_complete

	runner.add_on_complete(on_complete)

	runner.set_on_delta(on_delta)

	runner.set_on_status(on_status)

	runner.set_on_tool_call(on_tool_call)

	runner.set_on_tool_result(on_tool_result)

	runner.set_on_permission(on_permission)

	_bridge.set_inbound_handler(on_inbound)

	_bridge.set_command_handler(on_command)

	_bridge.set_state_listener(_broadcast_state)

	try:

		await _bridge.start()

		_broadcast_state()

	except Exception:

		if _prev_complete is not None:
			runner.remove_on_complete(_prev_complete)

		runner.set_on_delta(None)

		runner.set_on_status(None)

		runner.set_on_tool_call(None)

		runner.set_on_tool_result(None)

		runner.set_on_permission(None)

		_bridge.set_inbound_handler(None)

		_bridge.set_command_handler(None)

		_bridge.set_state_listener(None)

		raise





async def stop(runner: FinalOnlyRunner | None = None) -> None:

	global _runner_ref

	_mirror.reset_data()

	_inbound_q.clear()

	_bridge.set_inbound_handler(None)

	_bridge.set_command_handler(None)

	_bridge.set_state_listener(None)

	if runner is not None:

		if _prev_complete is not None:
			runner.remove_on_complete(_prev_complete)

		runner.set_on_delta(None)

		runner.set_on_status(None)

		runner.set_on_tool_call(None)

		runner.set_on_tool_result(None)

		runner.set_on_permission(None)

	_runner_ref = None

	await _bridge.stop()

	_broadcast_state()





async def autostart(runner: FinalOnlyRunner | None, store: JobStore | None) -> None:

	if not filehelper_autostart():

		return

	if runner is None or store is None:

		return

	await start(runner, store)





async def shutdown(runner: FinalOnlyRunner | None = None) -> None:

	if _bridge.state == "stopped":

		return

	await stop(runner)


