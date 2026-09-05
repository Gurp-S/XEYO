"""In-process `xeyo chat`."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

from rich.text import Text

from cli import ui
from cli.cwdutil import ensure_utf8_stdio, resolve_cwd
from cli.interact import (
	resolve_ask_interactive,
	resolve_permission_interactive,
	resolve_plan_interactive,
)
from cli.render import EventRenderer
from cli.slash import handle_slash
from engine.query_engine import QueryEngine, build_default_engine
from msgtypes.events import (
	AskUserPendingEvent,
	PermissionPendingEvent,
	PlanPendingEvent,
	ResultEvent,
	StoppedEvent,
)
from permissions.policy import agent_mode as current_agent_mode
from permissions.policy import current_surface as _current_surface
from permissions.policy import set_agent_mode, set_permission_mode, set_surface
from session.hydrate import load_session_messages

console = ui.err

_DRAIN_TIMEOUT_SEC = 2.0


def build_chat_engine(
	*,
	cwd: str,
	session_id: str,
	provider: str,
	model: str,
	api_key: str,
	base_url: str,
) -> tuple[QueryEngine, int]:
	messages = load_session_messages(session_id)
	backend = "fake" if provider == "fake" else provider
	engine = build_default_engine(
		cwd=cwd,
		model_backend=backend,
		session_id=session_id,
		api_key=api_key or None,
		provider=None if provider == "fake" else provider,
		model=model or None,
		base_url=base_url or None,
		initial_messages=messages or None,
	)
	return engine, len(messages)


async def _consume_turn(
	stream: AsyncIterator[Any],
	*,
	renderer: EventRenderer,
) -> None:
	async for ev in stream:
		renderer.emit(ev)
		if isinstance(ev, PermissionPendingEvent):
			await resolve_permission_interactive(ev, json_mode=renderer.json_mode)
		elif isinstance(ev, AskUserPendingEvent):
			await resolve_ask_interactive(ev, json_mode=renderer.json_mode)
		elif isinstance(ev, PlanPendingEvent):
			await resolve_plan_interactive(ev, json_mode=renderer.json_mode)


async def run_turn(
	engine: QueryEngine,
	prompt: str,
	*,
	renderer: EventRenderer,
	agent_mode: str,
	permission_mode: str,
) -> None:
	prev_agent = current_agent_mode()
	prev_surface = _current_surface()
	set_permission_mode(permission_mode)
	set_agent_mode(agent_mode)
	# T35：进程内脚本/管道是明确非 GUI 面；XeyoUI 据此诚实降级为「需要 GUI」。
	set_surface("cli")
	renderer.reset_turn()
	stream = engine.submit(prompt, {"agent_mode": agent_mode})
	aiter = stream.__aiter__()
	try:
		await _consume_turn(aiter, renderer=renderer)
	except KeyboardInterrupt:
		engine.interrupt()
		renderer.stop_status()
		if not renderer.json_mode:
			console.print("\n[dim]interrupted — draining…[/dim]")
		await _drain_after_interrupt(aiter, renderer=renderer)
	finally:
		renderer.finish_turn()
		set_permission_mode(None)
		set_agent_mode(prev_agent)
		set_surface(prev_surface)


async def _drain_after_interrupt(
	aiter: Any,
	*,
	renderer: EventRenderer,
) -> None:
	"""Interrupt 后清尾：继续消费引擎事件，直到 Stopped/Result 或流自然结束。

	超时**绝不** cancel 在途的 ``aiter.__anext__()``——那会把 CancelledError
	注入引擎事件流生成器并拆毁它（与 server SSE 订阅 wait_for(__anext__) 同款
	bug）。这里用 ``shield`` 保住在途 resumption：超时后引擎流在后台自然收尾，
	结果/异常丢弃（aiter 为 per-turn 对象，本次 drain 之后不再复用）。
	"""

	def _swallow_result(task: "asyncio.Task[object]") -> None:
		if not task.cancelled():
			task.exception()  # 标记异常已取回，避免 "exception was never retrieved"

	try:
		while True:
			next_ev = asyncio.ensure_future(aiter.__anext__())
			try:
				ev = await asyncio.wait_for(
					asyncio.shield(next_ev), timeout=_DRAIN_TIMEOUT_SEC
				)
			except asyncio.TimeoutError:
				# 不得 cancel next_ev；挂回调丢弃其最终结果/异常即可。
				next_ev.add_done_callback(_swallow_result)
				break
			except Exception:  # noqa: BLE001 — 含 StopAsyncIteration：流自然结束
				break
			renderer.emit(ev)
			if isinstance(ev, (StoppedEvent, ResultEvent)):
				break
	except Exception:  # noqa: BLE001
		pass
	if not renderer.json_mode:
		console.print("[dim]■ stopped[/dim]")


def _read_repl_line(mode: str) -> str:
	"""Styled prompt; falls back to plain input if Prompt unavailable."""
	try:
		from rich.prompt import Prompt

		return Prompt.ask(ui.repl_prompt_text(mode=mode), console=ui.out, default="")
	except Exception:
		ui.out.print(ui.repl_prompt_text(mode=mode), end="")
		return input()


async def chat_async(
	*,
	prompt: str | None,
	cwd: str | None,
	session_id: str | None,
	provider: str,
	model: str,
	api_key: str,
	base_url: str,
	permission_mode: str,
	agent_mode: str,
	print_mode: bool,
	json_mode: bool,
) -> int:
	ensure_utf8_stdio()
	work = resolve_cwd(cwd, persist=True)
	sid = (session_id or "").strip() or uuid.uuid4().hex
	renderer = EventRenderer(json_mode=json_mode)
	mode = agent_mode
	model_cur = model
	last_prompt: str | None = None
	engine, restored = build_chat_engine(
		cwd=work,
		session_id=sid,
		provider=provider,
		model=model,
		api_key=api_key,
		base_url=base_url,
	)
	if not json_mode:
		model_label = model or getattr(engine, "_model_name", "") or ""
		if print_mode:
			ui.session_chip(engine.session_id, restored=restored)
			ui.out.print(
				Text.assemble(
					("  ", ""),
					(f"{provider}/{model_label}" if model_label else provider, "dim"),
					("  ·  ", "dim"),
					(work, "dim"),
				)
			)
		else:
			ui.print_banner(
				session_id=engine.session_id,
				cwd=work,
				mode=mode,
				provider=provider,
				model=model_label,
				restored=restored,
			)

	async def _run_turn_text(turn_text: str) -> None:
		nonlocal last_prompt
		if not json_mode:
			ui.print_rule()
		last_prompt = turn_text
		await run_turn(
			engine,
			turn_text,
			renderer=renderer,
			agent_mode=mode,
			permission_mode=permission_mode,
		)

	async def _one(text: str) -> None:
		nonlocal engine, mode, model_cur, last_prompt
		slash = handle_slash(text, engine=engine, set_agent_mode=set_agent_mode)
		if slash.handled:
			if slash.message and not json_mode:
				if text.strip().lower() in ("/help", "/h", "/?"):
					ui.out.print(ui.help_panel())
				else:
					ui.out.print(f"[dim]{slash.message}[/dim]")
			if slash.agent_mode:
				mode = slash.agent_mode
				if not json_mode:
					ui.out.print(
						f"[bold {ui.ACCENT}]mode[/bold {ui.ACCENT}] → "
						f"[bold]{mode}[/bold]"
					)
			if slash.model_override:
				model_cur = slash.model_override
			if slash.rebuild_engine or slash.model_override or slash.load_session:
				engine, restored_n = build_chat_engine(
					cwd=work,
					session_id=slash.load_session or uuid.uuid4().hex,
					provider=provider,
					model=model_cur,
					api_key=api_key,
					base_url=base_url,
				)
				if not json_mode:
					ui.session_chip(engine.session_id, restored=restored_n)
			if slash.exit_repl:
				if not json_mode:
					ui.out.print()
					ui.out.print(f"[dim]{ui.brand_mark()}  bye[/dim]")
				raise SystemExit(0)
			if slash.resend_last:
				if not last_prompt:
					if not json_mode:
						ui.out.print("[dim]还没有可重试的消息[/dim]")
					return
				await _run_turn_text(last_prompt)
				return
			if slash.prompt_override:
				await _run_turn_text(slash.prompt_override)
				return
			return
		await _run_turn_text(text)

	if prompt is not None and prompt.strip():
		await _one(prompt.strip())
		return 0
	if print_mode:
		console.print("[bold red]--print requires a prompt[/bold red]")
		return 2
	while True:
		try:
			line = await asyncio.to_thread(_read_repl_line, mode)
		except (EOFError, KeyboardInterrupt):
			if not json_mode:
				ui.out.print()
				ui.out.print(f"[dim]{ui.brand_mark()} bye[/dim]")
			break
		text = (line or "").strip()
		if text:
			await _one(text)
	return 0


def run_chat(**kwargs: Any) -> int:
	return asyncio.run(chat_async(**kwargs))
