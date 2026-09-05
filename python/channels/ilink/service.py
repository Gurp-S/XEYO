"""iLink 单例：QR 登录、长轮询、镜像事件、SSE。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from pathlib import Path
from typing import Any

import channels.ilink._state as _st

import httpx

from channels.base import InboundMessage
from channels.filehelper.commands import parse_command, with_screenshot_nudge
from channels.filehelper.inbound_queue import InboundQueue
from channels.filehelper.prefix import is_own_reply, xeyo_reply
from common.errors import safe_error_text
from channels.ilink import SESSION_ID, session_id_for
from channels.ilink import broadcast as il_broadcast
from channels.ilink.channel import ILinkChannel
from channels.ilink.client import (
	ILinkClient,
	collect_update_msgs,
	decode_qr_payload,
	extract_text,
	rpc_ok,
)
from channels.ilink.qr_png import looks_like_image_url, render_qr_png, sniff_image
from channels.ilink.store import clear_credentials, load_credentials, save_credentials
from channels.jobs import JobRecord, JobStore
from channels.mirror import ChannelMirror
from channels.runner import FinalOnlyRunner, set_runtime_model_config
from permissions.store import default_permission_store
from server.session_pool import ModelConfig

log = logging.getLogger("xeyo.ilink")

# 帮助文案与文件传输助手同源（统一 manifest 生成，白名单一致）。
from channels.filehelper.commands import help_text as _shared_remote_help_text

_HELP = _shared_remote_help_text()


from channels.ilink._state import _bridge, _inbound_q
from channels.ilink.bridge import ILinkBridge, _silent_typing
from channels.ilink.stream import (
	_mirror,
	accepts_stream_session,
	events_since,
	status_payload,
	_broadcast_state,
	_broadcast_stream,
	_cancel_stream_flush,
	_flush_stream,
	_mirror_sid,
	_push_event,
	_publish_stream,
	_state_payload,
)
_st._msg_lock: asyncio.Lock | None = None
_PERSIST_DELAY_S = 2.0
_EMPTY_FAST_S = 0.08
_EMPTY_SLEEP_S = 0.05
# 微信 getupdates 默认 hold 约 35s。读超时必须略大于 hold。
# wait_for 必须晚于 httpx 读超时：谁先取消请求，谁就会在微信侧留下僵尸槽，
# 下一条消息要等僵尸过期（再一轮 hold）才进得来。
_POLL_HOLD_DEFAULT_MS = 35_000
_POLL_GRACE_S = 8.0
_POLL_READ_S = _POLL_HOLD_DEFAULT_MS / 1000.0 + _POLL_GRACE_S  # 43
_POLL_DEADLINE_S = _POLL_READ_S + 12.0  # 55，仅作挂死看门狗
_POLL_TIMEOUT = httpx.Timeout(
	connect=15.0,
	read=_POLL_READ_S,
	write=20.0,
	pool=20.0,
)
_POLL_ERR_SLEEP_S = 0.25
_POLL_CONNECT_SLEEP_S = 1.0
_POLL_CLEAR_BUF_AFTER = 3
_EXPIRED_CODES = {-14, 401, -13, "-14", "401", "-13"}
_GATEWAY_DOWN_HINT = "连不上微信网关，请检查网络或系统代理是否已启动"
_LOGGED_IN_HINT = "ClawBot / iLink 已连接"


def empty_poll_sleep_s(prev_empty_at: float, now: float) -> float:
	"""连续立刻空返回才小睡，长轮询挂起后不再额外等。"""
	if prev_empty_at > 0 and (now - prev_empty_at) < _EMPTY_FAST_S:
		return _EMPTY_SLEEP_S
	return 0.0


def _session_expired(data: dict[str, Any]) -> bool:
	return data.get("errcode") in _EXPIRED_CODES or data.get("ret") in _EXPIRED_CODES


async def _notify_online(client: object, token: str) -> bool:
	"""告诉微信 bot 已上线。失败除非明确过期都当成功，避免误杀登录。"""
	try:
		data = await client.notifystart(token)  # type: ignore[attr-defined]
	except Exception as e:  # noqa: BLE001
		log.warning("ilink notifystart: %s", e)
		return True
	if _session_expired(data):
		log.warning("ilink notifystart expired: %s", data.get("errmsg") or data)
		return False
	return True


async def _notify_offline(client: object | None, token: str) -> None:
	if client is None or not token:
		return
	try:
		await asyncio.wait_for(client.notifystop(token), 2.5)  # type: ignore[attr-defined]
	except Exception:
		pass


async def _recover_poll(
	client: object,
	token: str,
	*,
	reason: str,
	streak: int,
	notify: bool = True,
) -> None:
	"""关掉套接字；传输错误才重报上线。本地超时不要 notifystop，避免把会话打冷。"""
	_bridge.last_poll_error = reason
	_bridge.poll_timeouts = streak
	log.warning("ilink getupdates %s (streak=%s)", reason, streak)
	reset = getattr(client, "reset_poll_http", None)
	if callable(reset):
		try:
			await reset()
		except Exception:
			pass
	if notify and streak >= 2:
		await _notify_offline(client, token)
		await _notify_online(client, token)
		await asyncio.sleep(0.3)
	if streak >= _POLL_CLEAR_BUF_AFTER and _bridge._buf:
		log.warning("ilink clearing stuck get_updates_buf after %s failed polls", streak)
		_bridge._buf = ""
		_flush_persist()


def _poll_timeout_pair() -> tuple[httpx.Timeout, float]:
	hold_s = max(8.0, (_bridge.hold_ms or _POLL_HOLD_DEFAULT_MS) / 1000.0)
	read_s = hold_s + _POLL_GRACE_S
	# 生产：看门狗晚于读超时。测试可把 _POLL_DEADLINE_S 压到读超时以下以切断挂起。
	if _POLL_DEADLINE_S >= _POLL_READ_S:
		deadline_s = max(_POLL_DEADLINE_S, read_s + 12.0)
	else:
		deadline_s = _POLL_DEADLINE_S
	return (
		httpx.Timeout(connect=15.0, read=read_s, write=20.0, pool=20.0),
		deadline_s,
	)


def _cancel_persist() -> None:
	if _st._persist_handle is not None:
		_st._persist_handle.cancel()
		_st._persist_handle = None


def _flush_persist() -> None:
	_cancel_persist()
	if not _bridge._token:
		return
	base = ""
	client = _bridge._client
	if client is not None:
		base = str(getattr(client, "base_url", "") or "")
	save_credentials(
		{
			"bot_token": _bridge._token,
			"base_url": base,
			"get_updates_buf": _bridge._buf,
		}
	)


def _schedule_persist() -> None:
	try:
		loop = asyncio.get_running_loop()
	except RuntimeError:
		_flush_persist()
		return
	if _st._persist_handle is not None:
		_st._persist_handle.cancel()
	_st._persist_handle = loop.call_later(_PERSIST_DELAY_S, _flush_persist)


def _take_updates_buf(result: dict[str, Any]) -> None:
	buf = result.get("get_updates_buf")
	if isinstance(buf, str) and buf and buf != _bridge._buf:
		_bridge._buf = buf
		_schedule_persist()


def get_bridge() -> ILinkBridge:
	return _bridge


def is_running() -> bool:
	return _bridge.state not in {"stopped"}


async def _begin_inbound(
	text: str,
	channel: ILinkChannel,
	*,
	images: list[str] | None = None,
	peer: str = "",
	ctx: str = "",
	session_id: str = "",
) -> None:
	sid = (session_id or "").strip() or session_id_for(peer) or SESSION_ID
	_st._last_session_id = sid
	_st._stream_session_id = sid
	if peer:
		_bridge.peer_id = peer
	if ctx:
		_bridge.context_token = ctx
	_mirror.begin_stream()
	_broadcast_state()
	raw = {"ctx": ctx} if ctx else None
	await channel.handle_inbound(
		InboundMessage(
			text=with_screenshot_nudge(text),
			session_id=sid,
			sender_id=(peer or "").strip() or "ilink",
			images=tuple(images or ()),
			raw=raw,
		)
	)


async def _drain_inbound_queue(channel: ILinkChannel, runner: FinalOnlyRunner) -> None:
	nxt = _inbound_q.pop_idle(runner.session_busy)
	if nxt:
		await _begin_inbound(
			nxt.text,
			channel,
			images=nxt.images or None,
			peer=nxt.peer,
			ctx=nxt.ctx,
			session_id=nxt.session_id,
		)


async def _materialize_qr(client: ILinkClient, data: dict[str, Any]) -> None:
	raw = str(data.get("qrcode_img_content") or data.get("qrcode_img") or "")
	blob, url = decode_qr_payload(raw)
	payload = url or raw.strip()
	if blob is not None:
		mime = sniff_image(blob)
		if mime:
			_bridge._set_qr(blob, mime=mime)
			return
	if url and looks_like_image_url(url):
		try:
			got, _ctype = await client.fetch_bytes(url)
			mime = sniff_image(got)
			if mime:
				_bridge._set_qr(got, mime=mime)
				return
		except Exception as e:  # noqa: BLE001
			log.warning("ilink qr download failed: %s", e)
	if payload:
		try:
			_bridge._set_qr(render_qr_png(payload), mime="image/png")
			return
		except Exception as e:  # noqa: BLE001
			log.warning("ilink qr encode failed: %s", e)
			_bridge.hint = f"无法生成二维码：{e}"
			return
	_bridge.hint = "已向微信申请二维码，请稍候或检查网络。"


async def _login_with_qr(client: ILinkClient, saved_token: str) -> str:
	_bridge.state = "starting"
	_bridge.hint = "正在向微信申请登录码…"
	_bridge.error = None
	_broadcast_state()
	tokens = [saved_token] if saved_token else []
	data = await client.get_bot_qrcode(tokens)
	qrcode = str(data.get("qrcode") or "")
	if not qrcode:
		msg = str(data.get("errmsg") or data.get("error") or "get_bot_qrcode 未返回二维码")
		raise RuntimeError(msg)
	await _materialize_qr(client, data)
	_bridge.state = "qr"
	_bridge.hint = "用手机微信扫描二维码（ClawBot / iLink，不是文件传输助手网页）"
	_broadcast_state()

	poll_host = None
	while not _bridge._stop_event().is_set():
		t0 = time.monotonic()
		st = await client.get_qrcode_status(qrcode, base_url=poll_host)
		status = str(st.get("status") or "").lower()
		token = str(st.get("bot_token") or "")
		if status == "confirmed" or token:
			base = str(st.get("baseurl") or st.get("base_url") or "")
			if base:
				client.set_base_url(base)
			if not token:
				raise RuntimeError("扫码成功但未返回 bot_token")
			return token
		if status in {"scaned", "scanned"}:
			_bridge.state = "scanned"
			_bridge.hint = "已扫码，请在手机上点确认"
			_broadcast_state()
		elif status == "scaned_but_redirect":
			host = str(st.get("redirect_host") or "").strip()
			if host:
				poll_host = host if host.startswith("http") else f"https://{host}"
		elif status == "expired":
			data = await client.get_bot_qrcode(tokens)
			qrcode = str(data.get("qrcode") or qrcode)
			await _materialize_qr(client, data)
			_bridge.state = "qr"
			_bridge.hint = "二维码已刷新，请重新扫描"
			_broadcast_state()
		elif status == "need_verifycode":
			_bridge.hint = "微信要求输入配对码，请在手机上完成验证后等待"
			_broadcast_state()
		elif status in {"verify_code_blocked"}:
			data = await client.get_bot_qrcode(tokens)
			qrcode = str(data.get("qrcode") or qrcode)
			await _materialize_qr(client, data)
			_bridge.hint = "配对失败次数过多，已刷新二维码"
			_broadcast_state()
		elif status == "binded_redirect" and saved_token:
			return saved_token
		err = st.get("errmsg")
		if err and status in {"error", "fail", "failed"}:
			raise RuntimeError(str(err))
		# 服务端若立刻返回 wait，稍歇再问；已扫码则马上再问。
		elapsed = time.monotonic() - t0
		wait = 0.15 if status in {"scaned", "scanned"} else 0.45
		if elapsed < wait:
			await asyncio.sleep(wait - elapsed)
	raise asyncio.CancelledError()


async def _ensure_typing(client: ILinkClient, token: str, user_id: str, context_token: str) -> None:
	if user_id in _bridge._typing:
		return
	try:
		cfg = await client.getconfig(token, user_id, context_token)
		ticket = str(cfg.get("typing_ticket") or "")
		if ticket:
			_bridge._typing[user_id] = ticket
	except Exception:
		pass


def _msg_type(msg: dict[str, Any]) -> int:
	raw = msg.get("message_type")
	if raw is None:
		raw = msg.get("messageType")
	try:
		return int(raw or 0)
	except (TypeError, ValueError):
		return 0


def _from_user_id(msg: dict[str, Any]) -> str:
	return str(msg.get("from_user_id") or msg.get("fromUserId") or "")


def _reply_ctx(msg: dict[str, Any]) -> str:
	for key in ("context_token", "contextToken", "context"):
		v = str(msg.get(key) or "").strip()
		if v:
			return v
	return ""


def _summarize_inbound(msg: dict[str, Any], *, skip: str | None = None) -> dict[str, Any]:
	from_id = _from_user_id(msg)
	if "@im.wechat" in from_id:
		from_kind = "wechat"
	elif "@im.bot" in from_id:
		from_kind = "bot"
	elif from_id:
		from_kind = "other"
	else:
		from_kind = "none"
	items = msg.get("item_list") or msg.get("itemList") or []
	item_types: list[object] = []
	if isinstance(items, list):
		for it in items:
			if isinstance(it, dict):
				item_types.append(it.get("type"))
	text = extract_text(msg)
	preview = text[:40]
	return {
		"skip": skip,
		"message_type": _msg_type(msg),
		"from": from_kind,
		"item_types": item_types[:8],
		"text_len": len(text),
		"preview": preview,
		"has_group": bool(str(msg.get("group_id") or msg.get("groupId") or "").strip()),
		"keys": [str(k) for k in list(msg)[:16]],
	}


def _note_inbound(msg: dict[str, Any], *, skip: str | None = None) -> None:
	info = _summarize_inbound(msg, skip=skip)
	_bridge.last_inbound = info
	if skip:
		log.warning(
			"ilink inbound error skip=%s type=%s from=%s items=%s text_len=%s keys=%s",
			skip,
			info.get("message_type"),
			info.get("from"),
			info.get("item_types"),
			info.get("text_len"),
			info.get("keys"),
		)


def _is_user_sender(from_id: str) -> bool:
	return "@im.wechat" in from_id


async def _handle_user_msg(msg: dict[str, Any], channel: ILinkChannel, runner: FinalOnlyRunner) -> None:
	# 2 = bot 回声。来自 @im.wechat 的用户消息即使 type 填错也要处理。
	msg_type = _msg_type(msg)
	from_id = _from_user_id(msg)
	if msg_type == 2 and not _is_user_sender(from_id):
		_note_inbound(msg, skip="bot_echo")
		return
	group = str(msg.get("group_id") or msg.get("groupId") or "").strip()
	# 私聊也会带 group_id（会话 id）；只有不是微信用户发来的才当群消息丢掉。
	if group and not _is_user_sender(from_id):
		_note_inbound(msg, skip="group")
		return
	text = extract_text(msg)
	if text and is_own_reply(text):
		_note_inbound(msg, skip="own_reply")
		return

	# 纯文本不要 import media（会拉 cryptography）。系统 Python 没装时会把入站整条吞掉。
	need_media = False
	items = msg.get("item_list") or msg.get("itemList") or []
	for item in items:
		if not isinstance(item, dict):
			continue
		try:
			kind = int(item.get("type") or 0)
		except (TypeError, ValueError):
			kind = 0
		if kind in {2, 4}:  # image / file
			need_media = True
			break
	images: list[str] = []
	prompt = (text or "").strip()
	if need_media:
		from channels.ilink.media import collect_inbound_media, inbound_prompt

		media = await collect_inbound_media(_bridge._client, msg)
		prompt, images = inbound_prompt(text, media)
	if not prompt:
		if _is_user_sender(from_id):
			prompt = "[微信消息]"
		else:
			_note_inbound(msg, skip="empty")
			return
	_note_inbound(msg)
	peer = from_id
	ctx = _reply_ctx(msg)
	sid = session_id_for(peer)
	if not (peer or "").strip():
		log.warning("ilink inbound missing from_user_id; fallback session=%s", sid)
	if peer:
		_bridge.peer_id = peer
	if ctx:
		_bridge.context_token = ctx
	if _bridge._client and _bridge._token and peer and ctx:
		asyncio.create_task(
			_ensure_typing(_bridge._client, _bridge._token, peer, ctx)
		)

	if not need_media:
		hit = parse_command(text)
		if hit is not None:
			reply = await _run_command(hit.name, text, runner, session_id=sid)
			info = dict(_bridge.last_inbound or {})
			info["handled"] = "command"
			_bridge.last_inbound = info
			if reply:
				asyncio.create_task(
					_silent_send(xeyo_reply(reply), to_user_id=peer, context_token=ctx)
				)
			return

	_push_event("inbound", prompt, session_id=sid)
	try:
		busy = getattr(runner, "session_busy", None)
		if callable(busy) and busy(sid):
			pos = _inbound_q.push(
				prompt, images=images, peer=peer, ctx=ctx, session_id=sid
			)
			info = dict(_bridge.last_inbound or {})
			info["handled"] = "queued"
			info["queue_pos"] = pos
			_bridge.last_inbound = info
			asyncio.create_task(
				_silent_send(
					xeyo_reply(f"上一轮还在跑，你的消息已排队（#{pos}）。"),
					to_user_id=peer,
					context_token=ctx,
				)
			)
		else:
			await _begin_inbound(
				prompt,
				channel,
				images=images,
				peer=peer,
				ctx=ctx,
				session_id=sid,
			)
			info = dict(_bridge.last_inbound or {})
			info["handled"] = True
			_bridge.last_inbound = info
	except Exception as e:  # noqa: BLE001
		_note_inbound(msg, skip=f"begin:{type(e).__name__}")
		log.warning("ilink inbound error begin: %s", e)
		return
	handler = _bridge._on_inbound
	if handler is not None:
		try:
			await handler(prompt, images)
		except TypeError:
			await handler(prompt)


async def _silent_send(
	text: str,
	*,
	to_user_id: str = "",
	context_token: str = "",
) -> None:
	try:
		await _bridge.send_text(
			text,
			to_user_id=to_user_id or None,
			context_token=context_token or None,
		)
	except Exception as e:  # noqa: BLE001
		log.warning("ilink send: %s", e)


async def _run_command(
	name: str,
	raw: str,
	runner: FinalOnlyRunner,
	*,
	session_id: str = "",
) -> str | None:
	sid = (session_id or "").strip() or SESSION_ID
	_st._last_session_id = sid
	_push_event("inbound", raw, command=name, session_id=sid)
	if name == "stop":
		ok = runner.interrupt_session(sid)
		reply = "已请求停止当前任务" if ok else "当前没有正在运行的任务"
		_push_event("outbound", xeyo_reply(reply), command=name, session_id=sid)
		return reply
	if name == "status":
		busy = runner.session_busy(sid)
		try:
			from server.deps import _pool

			cwd = _pool.session_cwd(sid) or _pool.cwd or ""
		except Exception:
			cwd = ""
		reply = (
			f"通道：ClawBot / iLink\n"
			f"状态：{_bridge.state}\n"
			f"任务：{'进行中' if busy else '空闲'}\n"
			f"目录：{cwd or '(未设置)'}"
		)
		_push_event("outbound", xeyo_reply(reply), command=name, session_id=sid)
		return reply
	if name == "cwd":
		try:
			from server.deps import _pool

			cwd = _pool.session_cwd(sid) or _pool.cwd or ""
		except Exception as e:  # noqa: BLE001
			cwd = f"(无法读取: {e})"
		_push_event("outbound", xeyo_reply(cwd), command=name, session_id=sid)
		return cwd
	if name in {"allow", "deny"}:
		approved = name == "allow"
		item = default_permission_store().pending_for_session(sid)
		if item is None:
			reply = "当前没有待确认的操作"
		else:
			ok = default_permission_store().resolve(
				item.request_id, approved, actor="ilink"
			)
			reply = (
				"已允许，继续执行。"
				if ok and approved
				else "已拒绝该操作。"
				if ok
				else "请求已处理过或已过期。"
			)
		_push_event("outbound", xeyo_reply(reply), command=name, session_id=sid)
		return reply
	if name == "help":
		_push_event("outbound", xeyo_reply(_HELP), command=name, session_id=sid)
		return _HELP
	if name in {"rule", "doctor", "proposals"}:
		from channels.filehelper.commands import handle_instruction_command, parse_command

		hit = parse_command(raw)
		arg = hit.arg if hit is not None else ""
		reply = handle_instruction_command(name, arg) or "无法处理该指令"
		_push_event("outbound", xeyo_reply(reply), command=name, session_id=sid)
		return reply
	return None


async def _dispatch_msgs(
	msgs: list[dict[str, Any]],
	channel: ILinkChannel,
	runner: FinalOnlyRunner,
) -> None:
	if _st._msg_lock is None:
		_st._msg_lock = asyncio.Lock()
	async with _st._msg_lock:
		for msg in msgs:
			try:
				await _handle_user_msg(msg, channel, runner)
			except Exception as e:  # noqa: BLE001
				log.exception("ilink inbound error failed: %s", e)
				_note_inbound(msg, skip=f"exc:{type(e).__name__}")


async def _poll_loop(channel: ILinkChannel, runner: FinalOnlyRunner) -> None:
	client = _bridge._client
	token = _bridge._token
	if client is None or not token:
		return
	last_empty_at = 0.0
	fail_streak = 0
	while not _bridge._stop_event().is_set():
		_bridge.poll_started_at = time.monotonic()
		try:
			req_timeout, deadline_s = _poll_timeout_pair()
			# httpx 先超时；wait_for 只防彻底挂死，避免取消进行中的长轮询。
			result = await asyncio.wait_for(
				client.getupdates(token, _bridge._buf, timeout=req_timeout),
				timeout=deadline_s,
			)
		except asyncio.CancelledError:
			raise
		except (asyncio.TimeoutError, httpx.TimeoutException):
			# 本地超时 ≠ 服务端错误：当空成功立刻下一轮。
			fail_streak += 1
			_bridge.last_poll_error = "timeout"
			_bridge.poll_timeouts = fail_streak
			log.debug("ilink getupdates timeout (streak=%s)", fail_streak)
			if fail_streak >= _POLL_CLEAR_BUF_AFTER:
				await _recover_poll(
					client, token, reason="timeout", streak=fail_streak, notify=False
				)
			elif fail_streak >= 2:
				reset = getattr(client, "reset_poll_http", None)
				if callable(reset):
					try:
						await reset()
					except Exception:
						pass
			continue
		except httpx.TransportError as e:
			fail_streak += 1
			cause = e.__cause__ or e.__context__
			detail = str(e).strip() or type(e).__name__
			log.warning(
				"ilink getupdates transport: %s cause=%s",
				detail,
				cause or "-",
			)
			connect = isinstance(e, httpx.ConnectError)
			# 代理未启动时 notifystop 只会再失败一轮，把收消息拖得更死。
			await _recover_poll(
				client,
				token,
				reason=f"transport:{type(e).__name__}:{detail[:80]}",
				streak=fail_streak,
				notify=not connect,
			)
			if connect:
				if _bridge.hint != _GATEWAY_DOWN_HINT:
					_bridge.hint = _GATEWAY_DOWN_HINT
					_broadcast_state()
				await asyncio.sleep(min(_POLL_CONNECT_SLEEP_S * fail_streak, 8.0))
			else:
				await asyncio.sleep(_POLL_ERR_SLEEP_S)
			continue
		except Exception as e:  # noqa: BLE001
			fail_streak += 1
			log.warning("ilink getupdates: %s", e)
			await _recover_poll(client, token, reason=type(e).__name__, streak=fail_streak)
			await asyncio.sleep(_POLL_ERR_SLEEP_S)
			continue
		if fail_streak:
			log.info("ilink getupdates recovered after %s failures", fail_streak)
		fail_streak = 0
		_bridge.poll_timeouts = 0
		if _bridge.hint == _GATEWAY_DOWN_HINT:
			_bridge.hint = _LOGGED_IN_HINT
			_broadcast_state()
		if _session_expired(result):
			_cancel_persist()
			_bridge._token = ""
			_bridge._buf = ""
			clear_credentials()
			_bridge.state = "error"
			_bridge.error = str(result.get("errmsg") or "登录已过期，请重新扫码")
			_broadcast_state()
			return
		hold_ms = result.get("longpolling_timeout_ms")
		if isinstance(hold_ms, int) and 5_000 <= hold_ms <= 120_000:
			_bridge.hold_ms = hold_ms
		ret = result.get("ret")
		_bridge.last_poll_ret = ret
		_bridge.last_poll_error = str(result.get("errmsg") or "") or None
		if ret not in (None, 0, "0"):
			log.warning(
				"ilink getupdates ret=%s errcode=%s errmsg=%s keys=%s",
				ret,
				result.get("errcode"),
				result.get("errmsg"),
				list(result)[:16],
			)
			_bridge.last_poll_msgs = 0
			await asyncio.sleep(0.4)
			continue
		msgs = collect_update_msgs(result)
		_bridge.last_poll_msgs = len(msgs)
		_bridge.poll_ok_at = time.monotonic()
		_take_updates_buf(result)
		if msgs:
			log.info("ilink inbound batch size=%s", len(msgs))
			_bridge.last_inbound = _summarize_inbound(msgs[0])
			last_empty_at = 0.0
			try:
				await _dispatch_msgs(msgs, channel, runner)
			except Exception as e:  # noqa: BLE001
				log.warning("ilink inbound error dispatch: %s", e)
				info = dict(_bridge.last_inbound or {})
				info["skip"] = f"dispatch:{type(e).__name__}"
				_bridge.last_inbound = info
			info = dict(_bridge.last_inbound or {})
			if not info.get("handled") and not info.get("skip"):
				log.warning("ilink inbound not handled, retry: %s", info)
				try:
					await _handle_user_msg(msgs[0], channel, runner)
				except Exception as e:  # noqa: BLE001
					log.exception("ilink inbound retry failed: %s", e)
				info = dict(_bridge.last_inbound or {})
			if not info.get("skip"):
				info["delivered"] = True
			info["event_n"] = len(_mirror._events)
			_bridge.last_inbound = info
		else:
			now = time.monotonic()
			pause = empty_poll_sleep_s(last_empty_at, now)
			last_empty_at = now
			if pause:
				await asyncio.sleep(pause)
	if _bridge.state == "logged_in" and not _bridge._stop_event().is_set():
		_bridge.state = "error"
		_bridge.error = "收消息循环已停止，请重新连接远程"
		_broadcast_state()


def create_client() -> ILinkClient:
	"""供测试替换为带 MockTransport 的客户端。"""
	return ILinkClient()


async def _run(channel: ILinkChannel, runner: FinalOnlyRunner) -> None:
	client = create_client()
	_bridge._client = client
	_bridge._stop = asyncio.Event()
	saved = load_credentials()
	saved_token = str(saved.get("bot_token") or "")
	saved_base = str(saved.get("base_url") or "")
	if saved_base:
		client.set_base_url(saved_base)
	_bridge._buf = str(saved.get("get_updates_buf") or "")
	try:
		token = saved_token
		if token:
			_bridge.state = "starting"
			_bridge.hint = "正在用已保存的登录恢复…"
			_broadcast_state()
			# 先 notifystop 清掉上次进程留下的僵尸长轮询槽，再 notifystart。
			await _notify_offline(client, token)
			await asyncio.sleep(0.4)
			if not await _notify_online(client, token):
				token = ""
				_bridge._buf = ""
				clear_credentials()
		if not token:
			_bridge._buf = ""
			token = await _login_with_qr(client, saved_token)
			if not await _notify_online(client, token):
				raise RuntimeError("登录成功但会话无效，请重新扫码")
		_bridge._token = token
		save_credentials(
			{
				"bot_token": token,
				"base_url": client.base_url,
				"get_updates_buf": _bridge._buf,
			}
		)
		_bridge.state = "logged_in"
		_bridge.hint = _LOGGED_IN_HINT
		_bridge.error = None
		_bridge._set_qr(None)
		_broadcast_state()
		await _poll_loop(channel, runner)
	except asyncio.CancelledError:
		raise
	except Exception as e:  # noqa: BLE001
		_bridge.state = "error"
		_bridge.error = f"{type(e).__name__}: {e}"
		_bridge.hint = "可改回「文件传输助手」通道，或稍后重试 iLink"
		_broadcast_state()
	finally:
		await client.aclose()
		if _bridge._client is client:
			_bridge._client = None


async def start(
	runner: FinalOnlyRunner,
	store: JobStore,
	*,
	model_cfg: ModelConfig | None = None,
) -> None:
	if _bridge.state in {"starting", "qr", "scanned", "logged_in"}:
		if model_cfg is not None:
			set_runtime_model_config(model_cfg)
		_st._runner_ref = runner
		return
	if _bridge.state == "error":
		await _bridge.stop()

	from channels.filehelper.service import get_bridge as fh_bridge
	from channels.filehelper.service import stop as fh_stop

	if fh_bridge().state != "stopped":
		await fh_stop(runner)

	_mirror.reset_data()
	_inbound_q.clear()
	_st._last_session_id = SESSION_ID
	_st._stream_session_id = ""
	_st._runner_ref = runner
	if model_cfg is not None:
		set_runtime_model_config(model_cfg)

	channel = ILinkChannel(runner, _bridge)
	_st._channel = channel

	async def on_inbound(text: str, images: list[str] | None = None) -> None:
		# 生产路径在 _handle_user_msg 里直接 _begin_inbound。
		# 这里只给测试注入；切勿再 enqueue，否则会跑两遍。
		return

	def on_delta(chunk: str, session_id: str) -> None:
		if not accepts_stream_session(session_id):
			return
		_mirror.append_delta(chunk)

	def on_status(name: str, session_id: str) -> None:
		if not accepts_stream_session(session_id):
			return
		_mirror.set_status(f"使用 {name}…")

	def _emit_ui_tool(
		kind: str,
		*,
		name: str,
		session_id: str,
		input: dict[str, Any] | None = None,
		output: str = "",
		is_error: bool = False,
	) -> None:
		_mirror.emit_ui_tool(
			kind,
			name=name,
			session_id=session_id,
			input=input,
			output=output,
			is_error=is_error,
		)

	def on_tool_call(name: str, input: dict[str, Any], session_id: str) -> None:
		if not accepts_stream_session(session_id):
			return
		_emit_ui_tool("tool_call", name=name, session_id=session_id, input=input)

	def on_tool_result(
		name: str, output: str, is_error: bool, session_id: str
	) -> None:
		if not accepts_stream_session(session_id):
			return
		_emit_ui_tool(
			"tool_result",
			name=name,
			session_id=session_id,
			output=output,
			is_error=is_error,
		)

	def on_permission(payload: dict[str, Any], session_id: str) -> None:
		if not accepts_stream_session(session_id):
			return
		kind = str(payload.get("kind") or "")
		if kind == "permission_pending":
			_mirror.set_status("等待你确认…")
			prompt = str(payload.get("prompt") or "")
			_push_event(
				"permission",
				prompt,
				session_id=session_id,
				request_id=str(payload.get("request_id") or ""),
				tool_name=str(payload.get("tool_name") or ""),
				reason=str(payload.get("reason") or ""),
			)
			peer = _bridge.peer_id
			ctx = _bridge.context_token
			if peer and ctx:
				asyncio.create_task(
					_silent_send(
						xeyo_reply(
							f"{prompt}\n回复 /allow（允许）或 /deny（拒绝）来确认。"
						),
						to_user_id=peer,
						context_token=ctx,
					)
				)
		else:
			_mirror.set_status("")
		_mirror.broadcast_stream(reset=True)

	def on_task_state(status: str, session_id: str) -> None:
		if not accepts_stream_session(session_id):
			return
		if status == "waiting_permission":
			_mirror.set_status("等待你确认…")
		else:
			_mirror.set_status("")
		_mirror.broadcast_stream(reset=True)

	async def on_complete(rec: JobRecord) -> None:
		body = ""
		if rec.session_id.startswith("ilink:"):
			# T34：错误回帖经安全过滤，内部异常痕迹不出通道。
			body = (
				rec.final_text
				if rec.status == "done"
				else safe_error_text(rec.error or "", fallback="")
			)
			if rec.session_id == _st._stream_session_id or not _st._stream_session_id:
				_mirror.reset_stream()
				_st._stream_session_id = ""
				_broadcast_state()
		if body:
			reply = xeyo_reply(body)
			_push_event("outbound", reply, session_id=rec.session_id)

		async def _send() -> None:
			try:
				await channel.send_job_result(rec)
			except Exception as e:  # noqa: BLE001
				log.warning("ilink send failed: %s", e)
				_bridge.error = f"回复未能发到微信：{type(e).__name__}: {e}"
				_broadcast_state()

		asyncio.create_task(_send())
		await _drain_inbound_queue(channel, runner)

	_st._prev_complete = on_complete
	runner.add_on_complete(on_complete)
	runner.set_on_delta(on_delta)
	runner.set_on_status(on_status)
	runner.set_on_tool_call(on_tool_call)
	runner.set_on_tool_result(on_tool_result)
	runner.set_on_permission(on_permission)
	runner.set_on_task_state(on_task_state)
	_bridge.set_inbound_handler(on_inbound)
	_bridge._stop = asyncio.Event()
	_bridge.state = "starting"
	_bridge.error = None
	_broadcast_state()
	_bridge._loop_task = asyncio.create_task(_run(channel, runner))


async def stop(runner: FinalOnlyRunner | None = None) -> None:
	_mirror.reset_data()
	_flush_persist()
	_inbound_q.clear()
	_st._last_session_id = SESSION_ID
	_st._stream_session_id = ""
	_bridge.set_inbound_handler(None)
	if runner is not None:
		if _st._prev_complete is not None:
			runner.remove_on_complete(_st._prev_complete)
		runner.set_on_delta(None)
		runner.set_on_status(None)
		runner.set_on_tool_call(None)
		runner.set_on_tool_result(None)
		runner.set_on_permission(None)
		runner.set_on_task_state(None)
	_st._runner_ref = None
	await _notify_offline(_bridge._client, _bridge._token)
	await _bridge.stop()
	_broadcast_state()


async def stop_if_running(runner: FinalOnlyRunner | None = None) -> None:
	if is_running():
		await stop(runner)


async def shutdown(runner: FinalOnlyRunner | None = None) -> None:
	if _bridge.state == "stopped":
		return
	await stop(runner)
