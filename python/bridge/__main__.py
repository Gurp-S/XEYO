"""
JSONL bridge 进程。

  cd python
  py -3.11 -u -m bridge

Ink / CLI 启动本模块并通信：
  → {"type":"submit","text":"..."}
  → {"type":"interrupt"}
  ← {"type":"assistant_delta","text":"..."}
  ← {"type":"tool_call",...} / tool_result / final / stopped / error
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from common.errors import friendly_error
from engine.query_engine import QueryEngine, build_default_engine
from msgtypes.envelope import EventIdGenerator
from msgtypes.events import EngineEvent


def _event_to_dict(ev: EngineEvent) -> dict[str, Any]:
	if is_dataclass(ev):
		return asdict(ev)
	raise TypeError(f"unsupported event: {type(ev)!r}")


def _write_event(obj: dict[str, Any]) -> None:
	sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
	sys.stdout.flush()


async def _run_submit(engine: QueryEngine, text: str) -> None:
	turn_id = uuid.uuid4().hex[:12]
	gen = EventIdGenerator()
	try:
		async for ev in engine.submit(text):
			obj = _event_to_dict(ev)
			obj.update(
				{
					"schema_version": "1.0",
					"session_id": "jsonl",
					"turn_id": turn_id,
					"event_id": gen.next(),
				}
			)
			_write_event(obj)
	except Exception as e:  # noqa: BLE001 — 向 CLI 暴露
		_write_event({"type": "error", "message": friendly_error(e)})


async def main() -> None:
	# 尽可能在 Windows 控制台强制 UTF-8
	try:
		sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
		sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
	except Exception:
		pass

	from session.workspace_path import boot_ui_cwd, is_python_package_root

	cwd = boot_ui_cwd()
	if not cwd:
		cwd = os.getcwd()
		if is_python_package_root(cwd):
			_write_event(
				{
					"type": "error",
					"message": "XEYO_CWD required: python package is not a workspace",
				}
			)
			return
	engine = build_default_engine(cwd=cwd)
	loop = asyncio.get_running_loop()
	queue: asyncio.Queue[str | None] = asyncio.Queue()

	def _stdin_thread() -> None:
		try:
			for line in sys.stdin:
				asyncio.run_coroutine_threadsafe(queue.put(line), loop)
		finally:
			asyncio.run_coroutine_threadsafe(queue.put(None), loop)

	threading.Thread(target=_stdin_thread, name="xeyo-stdin", daemon=True).start()

	current: asyncio.Task[None] | None = None

	while True:
		line = await queue.get()
		if line is None:
			break
		line = line.strip()
		if not line:
			continue
		try:
			cmd = json.loads(line)
		except json.JSONDecodeError as e:
			_write_event({"type": "error", "message": f"bad json: {e}"})
			continue

		ctype = cmd.get("type")
		if ctype == "interrupt":
			engine.interrupt()
			continue

		if ctype == "submit":
			if current is not None and not current.done():
				_write_event({"type": "error", "message": "会话正忙，请稍候或停止后重试"})
				continue
			text = str(cmd.get("text") or "")
			current = asyncio.create_task(_run_submit(engine, text))
			continue

		_write_event({"type": "error", "message": f"unknown command: {ctype}"})

	if current is not None and not current.done():
		engine.interrupt()
		try:
			await current
		except Exception:
			pass


if __name__ == "__main__":
	asyncio.run(main())
