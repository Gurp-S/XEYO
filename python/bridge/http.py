"""
DEPRECATED — 请使用 FastAPI 主服务：`py -3.11 -m server`（`server/app.py`）。

本模块为早期 stdlib HTTP/SSE 桥，与 `server/` 并行维护 EnginePool，仅作历史参考。
新代码与 GUI/tui 均通过 `server/routers/chat.py` 访问引擎。

  cd python
  py -3.11 -u -m bridge.http   # 不推荐

端点:
  GET  /api/health
  POST /api/chat       body { sessionId, text }  → text/event-stream
  POST /api/interrupt  body { sessionId }
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import uuid
from dataclasses import asdict, is_dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from engine.query_engine import QueryEngine, build_default_engine
from msgtypes.envelope import EventIdGenerator
from msgtypes.events import EngineEvent

_HOST = os.environ.get("XEYO_HTTP_HOST", "127.0.0.1")
_PORT = int(os.environ.get("XEYO_HTTP_PORT", "8765"))
_CORS_ORIGIN = os.environ.get("XEYO_CORS_ORIGIN", "http://localhost:5173")


def _event_to_dict(ev: EngineEvent) -> dict[str, Any]:
	if is_dataclass(ev):
		return asdict(ev)
	raise TypeError(f"unsupported event: {type(ev)!r}")


class EnginePool:
	"""每个 browser sessionId 一个 QueryEngine。"""

	def __init__(self, cwd: str) -> None:
		self._cwd = cwd
		self._engines: dict[str, QueryEngine] = {}
		self._session_cwd: dict[str, str] = {}
		self._busy: set[str] = set()
		self._lock = threading.Lock()

	def get(self, session_id: str, cwd: str | None = None) -> QueryEngine:
		from session.workspace_path import resolve_physical_cwd

		requested = (cwd or "").strip()
		with self._lock:
			pinned = self._session_cwd.get(session_id)
			if requested:
				physical = resolve_physical_cwd(requested)
				if pinned and pinned != physical:
					raise ValueError(
						f"session {session_id} is pinned to {pinned}, not {physical}"
					)
				use = physical
			elif pinned:
				use = pinned
			elif self._cwd:
				use = resolve_physical_cwd(self._cwd)
			else:
				raise ValueError("workspace cwd is required")
			eng = self._engines.get(session_id)
			if eng is None:
				eng = build_default_engine(cwd=use)
				self._engines[session_id] = eng
				self._session_cwd[session_id] = use
			return eng

	def try_begin(self, session_id: str) -> bool:
		with self._lock:
			if session_id in self._busy:
				return False
			self._busy.add(session_id)
			return True

	def end(self, session_id: str) -> None:
		with self._lock:
			self._busy.discard(session_id)

	def interrupt(self, session_id: str) -> bool:
		with self._lock:
			eng = self._engines.get(session_id)
			if eng is None:
				return False
			eng.interrupt()
			return True

	def usage_snapshot(self) -> dict[str, Any]:
		"""L1.2：跨 engine 聚合的预算观测（供 GET /api/health）。"""
		last_usd = 0.0
		last_tokens = 0
		session_usd = 0.0
		session_tokens = 0
		with self._lock:
			for eng in self._engines.values():
				snap = eng.budget_snapshot()
				session_usd += float(snap["used_usd"] or 0)
				session_tokens += int(snap["used_tokens"] or 0)
				if float(snap["last_usage_usd"] or 0) > last_usd:
					last_usd = float(snap["last_usage_usd"] or 0)
				if int(snap["last_usage_tokens"] or 0) > last_tokens:
					last_tokens = int(snap["last_usage_tokens"] or 0)
		return {
			"last_turn_usd": round(last_usd, 8),
			"last_turn_tokens": last_tokens,
			"session_used_usd": round(session_usd, 8),
			"session_used_tokens": session_tokens,
		}


class AsyncLoop:
	"""在 daemon 线程中运行的专用 asyncio 循环。"""

	def __init__(self) -> None:
		self.loop = asyncio.new_event_loop()
		self._thread = threading.Thread(
			target=self._run, name="xeyo-asyncio", daemon=True
		)
		self._thread.start()

	def _run(self) -> None:
		asyncio.set_event_loop(self.loop)
		self.loop.run_forever()

	def submit(self, coro: Any) -> None:
		asyncio.run_coroutine_threadsafe(coro, self.loop)


_pool: EnginePool | None = None
_async: AsyncLoop | None = None


def _ensure_runtime() -> tuple[EnginePool, AsyncLoop]:
	global _pool, _async
	if _pool is None:
		from session.workspace_path import boot_ui_cwd

		_pool = EnginePool(cwd=boot_ui_cwd())
	if _async is None:
		_async = AsyncLoop()
	return _pool, _async


async def _pump_submit(
	engine: QueryEngine,
	text: str,
	out_q: queue.Queue[dict[str, Any] | None],
	session_id: str,
) -> None:
	turn_id = uuid.uuid4().hex[:12]
	gen = EventIdGenerator()
	try:
		async for ev in engine.submit(text):
			item = _event_to_dict(ev)
			item.update(
				{
					"schema_version": "1.0",
					"session_id": session_id,
					"turn_id": turn_id,
					"event_id": gen.next(),
				}
			)
			out_q.put(item)
	except Exception as e:  # noqa: BLE001
		out_q.put({"type": "error", "message": str(e)})
	finally:
		out_q.put(None)


class MalformedRequestBody(ValueError):
	"""请求体读不成一个 JSON 对象：非 UTF-8 字节，或 Content-Length 不是非负整数。

	单独立一个类型（而不是继续挂 `json.JSONDecodeError`）：
	- 非文本字节被报成 "bad json" 会把客户端引向"我的 JSON 写错了"这条错路；
	- ValueError 的子类 ⇒ 任何按 ValueError 兜这一层的调用点仍然兜得住。
	两类都必须在这里收口：它们逃过 `except json.JSONDecodeError` 后，
	`BaseHTTPRequestHandler` 只会打 traceback 然后关连接 ⇒ 客户端收不到任何 HTTP 响应
	（2026-10-03 在 127.0.0.1 真端口上实测两种都是 RemoteDisconnected）。
	"""


class Handler(BaseHTTPRequestHandler):
	protocol_version = "HTTP/1.1"

	def log_message(self, fmt: str, *args: Any) -> None:
		sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

	def _cors(self) -> None:
		self.send_header("Access-Control-Allow-Origin", _CORS_ORIGIN)
		self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		self.send_header("Access-Control-Allow-Headers", "Content-Type")
		self.send_header("Access-Control-Allow-Credentials", "true")

	def _read_json(self) -> dict[str, Any]:
		raw_len = self.headers.get("Content-Length") or "0"
		try:
			length = int(raw_len)
		except ValueError as exc:
			# 长度不可信 ⇒ 没法排空请求体，余下的字节会在这条 keep-alive 连接上被当成
			# 下一个请求行解析（实测：畸形 Content-Length 之后的第二枪拿到 501
			# `Unsupported method ('{"sessionId":"s"}')`）。只能关连接。
			self.close_connection = True
			raise MalformedRequestBody(f"Content-Length 不是整数：{raw_len!r}") from exc
		if length < 0:
			# read(-5) 会一路读到 EOF：连接不结束就永远卡在这枪上
			self.close_connection = True
			raise MalformedRequestBody(f"Content-Length 是负数：{length}")
		raw = self.rfile.read(length) if length > 0 else b"{}"
		if not raw:
			return {}
		try:
			text = raw.decode("utf-8")
		except UnicodeDecodeError as exc:
			raise MalformedRequestBody(
				f"请求体不是合法 UTF-8（{exc.reason}，字节位置 {exc.start}）"
			) from exc
		return json.loads(text)

	def _send_json(self, code: int, obj: dict[str, Any]) -> None:
		body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
		self.send_response(code)
		self._cors()
		if self.close_connection:
			# 关连接必须说给客户听：否则客户端会把下一枪写进一个已死的 socket。
			self.send_header("Connection", "close")
		self.send_header("Content-Type", "application/json; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def do_OPTIONS(self) -> None:  # noqa: N802
		self.send_response(204)
		self._cors()
		self.end_headers()

	def do_GET(self) -> None:  # noqa: N802
		path = urlparse(self.path).path
		if path == "/api/health":
			payload = {"ok": True, "service": "xeyo-bridge-http"}
			try:
				pool, _async = _ensure_runtime()
				payload.update(pool.usage_snapshot())
			except Exception:
				pass
			self._send_json(200, payload)
			return
		self._send_json(404, {"error": "not found"})

	def do_POST(self) -> None:  # noqa: N802
		path = urlparse(self.path).path
		pool, async_loop = _ensure_runtime()

		if path == "/api/interrupt":
			try:
				payload = self._read_json()
			except MalformedRequestBody as e:
				self._send_json(400, {"error": str(e)})
				return
			except json.JSONDecodeError as e:
				self._send_json(400, {"error": f"bad json: {e}"})
				return
			sid = str(payload.get("sessionId") or "").strip()
			if not sid:
				self._send_json(400, {"error": "sessionId required"})
				return
			ok = pool.interrupt(sid)
			self._send_json(200, {"ok": ok})
			return

		if path != "/api/chat":
			self._send_json(404, {"error": "not found"})
			return

		try:
			payload = self._read_json()
		except MalformedRequestBody as e:
			self._send_json(400, {"error": str(e)})
			return
		except json.JSONDecodeError as e:
			self._send_json(400, {"error": f"bad json: {e}"})
			return

		sid = str(payload.get("sessionId") or "").strip()
		text = str(payload.get("text") or "").strip()
		workspace = str(payload.get("workspace") or "").strip() or None
		if not sid:
			self._send_json(400, {"error": "sessionId required"})
			return
		if not text:
			self._send_json(400, {"error": "text required"})
			return

		if not pool.try_begin(sid):
			self._send_json(409, {"error": "busy", "type": "error", "message": "会话正忙，请稍候或停止后重试"})
			return

		try:
			engine = pool.get(sid, cwd=workspace)
		except (ValueError, FileNotFoundError, NotADirectoryError) as e:
			pool.end(sid)
			self._send_json(400, {"error": str(e)})
			return
		out_q: queue.Queue[dict[str, Any] | None] = queue.Queue()
		async_loop.submit(_pump_submit(engine, text, out_q, sid))

		self.send_response(200)
		self._cors()
		self.send_header("Content-Type", "text/event-stream; charset=utf-8")
		self.send_header("Cache-Control", "no-cache")
		self.send_header("Connection", "keep-alive")
		self.send_header("X-Accel-Buffering", "no")
		self.end_headers()

		try:
			while True:
				item = out_q.get()
				if item is None:
					break
				chunk = f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode(
					"utf-8"
				)
				self.wfile.write(chunk)
				self.wfile.flush()
		except (BrokenPipeError, ConnectionResetError):
			pool.interrupt(sid)
		finally:
			pool.end(sid)


def main() -> None:
	try:
		sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
		sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
	except Exception:
		pass

	_ensure_runtime()
	server = ThreadingHTTPServer((_HOST, _PORT), Handler)
	print(f"XEYO HTTP bridge on http://{_HOST}:{_PORT}", flush=True)
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		print("\nshutting down", flush=True)
	finally:
		server.server_close()


if __name__ == "__main__":
	main()
