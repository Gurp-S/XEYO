"""xeyo attach — HTTP SSE against a running server session."""

from __future__ import annotations

import json
import sys
from typing import Any, Iterator

import httpx
from rich.markup import escape

from cli import http_api
from cli import ui
from cli.config_store import (
	load_config,
	resolve_api_key,
	resolve_model,
	resolve_permission_mode,
	resolve_provider,
	resolve_server_base_url,
)
from cli.cwdutil import ensure_utf8_stdio, resolve_cwd
from cli.interact import prompt_ask, prompt_permission, prompt_plan

console = ui.err


def parse_data_line(line: str) -> dict[str, Any] | None:
	"""Parse one SSE ``data:`` line (tolerates ``\\r``)."""
	line = line.strip().lstrip("\ufeff")
	if line.endswith("\r"):
		line = line[:-1]
	line = line.strip()
	if not line.startswith("data:"):
		return None
	payload = line[5:].strip()
	if not payload or payload == "[DONE]":
		return None
	try:
		obj = json.loads(payload)
	except json.JSONDecodeError:
		return None
	return obj if isinstance(obj, dict) else None


def iter_sse_objects(chunks: Iterator[str]) -> Iterator[dict[str, Any]]:
	"""Yield parsed SSE JSON objects; flush trailing buffer without final newline."""
	buf = ""
	for chunk in chunks:
		buf += chunk.replace("\r\n", "\n").replace("\r", "\n")
		while "\n" in buf:
			one, buf = buf.split("\n", 1)
			obj = parse_data_line(one)
			if obj is not None:
				yield obj
	if buf.strip():
		obj = parse_data_line(buf)
		if obj is not None:
			yield obj


def extract_xy(obj: dict[str, Any]) -> dict[str, Any] | None:
	for key in ("xy", "xeyo"):
		val = obj.get(key)
		if isinstance(val, dict):
			return val
	return None


def delta_text(obj: dict[str, Any]) -> str:
	choices = obj.get("choices")
	if not isinstance(choices, list) or not choices:
		return ""
	c0 = choices[0]
	if not isinstance(c0, dict):
		return ""
	delta = c0.get("delta")
	if isinstance(delta, dict) and isinstance(delta.get("content"), str):
		return delta["content"]
	return ""


def _read_line(mode: str) -> str:
	try:
		from rich.prompt import Prompt

		return Prompt.ask(ui.repl_prompt_text(mode=mode), console=ui.out, default="")
	except Exception:
		ui.out.print(ui.repl_prompt_text(mode=mode), end="")
		return input()


def attach_repl(
	session_id: str,
	*,
	base_url: str | None = None,
	api_key: str | None = None,
	provider: str | None = None,
	model: str | None = None,
	cwd: str | None = None,
	permission_mode: str | None = None,
	agent_mode: str = "agent",
	json_mode: bool = False,
) -> int:
	ensure_utf8_stdio()
	cfg = load_config()
	url = resolve_server_base_url(base_url, cfg=cfg)
	key = resolve_api_key(api_key, cfg=cfg)
	prov = resolve_provider(provider, cfg=cfg)
	mod = resolve_model(model, cfg=cfg) or "deepseek-chat"
	perm = resolve_permission_mode(permission_mode, cfg=cfg)
	work = resolve_cwd(cwd)
	client = http_api.make_client(url, key, timeout=None)
	mode = agent_mode
	if not json_mode:
		ui.print_banner(
			session_id=session_id,
			cwd=work,
			mode=mode,
			provider=prov,
			model=mod,
			restored=0,
		)
		ui.out.print(f"[dim]attached to {url}[/dim]")
	try:
		while True:
			try:
				line = _read_line(mode)
			except (EOFError, KeyboardInterrupt):
				if not json_mode:
					ui.out.print()
					ui.out.print(f"[dim]{ui.brand_mark()} bye[/dim]")
				break
			text = (line or "").strip()
			if not text:
				continue
			if text in ("/exit", "/quit", "/q"):
				if not json_mode:
					ui.out.print(f"[dim]{ui.brand_mark()} bye[/dim]")
				break
			if text in ("/help", "/h", "/?"):
				if not json_mode:
					ui.out.print(ui.help_panel())
					ui.out.print("[dim]attach: messages go to the HTTP session[/dim]")
				continue
			if text in ("/plan", "/ask", "/agent"):
				mode = text[1:]
				if not json_mode:
					ui.out.print(
						f"[bold {ui.ACCENT}]mode[/bold {ui.ACCENT}] → [bold]{mode}[/bold]"
					)
				continue
			if not json_mode:
				ui.print_rule()
			body: dict[str, Any] = {
				"model": mod,
				"stream": True,
				"session_id": session_id,
				"provider": prov,
				"permission_mode": perm,
				"agent_mode": mode,
				"workspace": work,
				"messages": [{"role": "user", "content": text}],
			}
			try:
				with client.stream(
					"POST",
					"/v1/chat/completions",
					json=body,
					headers={"Accept": "text/event-stream"},
				) as resp:
					if resp.status_code >= 400:
						detail = resp.read().decode(errors="replace")
						console.print(
							f"[bold red]✗ HTTP {resp.status_code}[/bold red] {detail}\n"
							f"[dim]Is the server up? Try: xeyo serve[/dim]"
						)
						continue
					saw_delta = False
					for obj in iter_sse_objects(resp.iter_text()):
						saw = handle_sse_obj(
							client, obj, json_mode=json_mode, saw_delta=saw_delta
						)
						if saw:
							saw_delta = True
					if saw_delta and not json_mode:
						ui.out.print()
			except KeyboardInterrupt:
				try:
					http_api.interrupt_http(client, session_id)
				except Exception:
					pass
				console.print("\n[dim]■ interrupted[/dim]")
			except httpx.ConnectError as exc:
				console.print(
					f"[bold red]✗ cannot reach {url}[/bold red]: {exc}\n"
					f"[dim]Start the backend with: xeyo serve[/dim]"
				)
			except Exception as exc:  # noqa: BLE001
				console.print(f"[bold red]✗ attach error[/bold red]: {exc}")
	finally:
		client.close()
	return 0


def handle_sse_obj(
	client: httpx.Client,
	obj: dict[str, Any],
	*,
	json_mode: bool,
	saw_delta: bool = False,
) -> bool:
	"""Handle one SSE JSON object. Returns True if assistant delta was printed."""
	if json_mode:
		sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
		sys.stdout.flush()
		# Still resolve pending panels in headless/json mode (fail-closed).
		xy = extract_xy(obj)
		if xy:
			_resolve_xy(client, xy, json_mode=True)
		return False

	printed_delta = False
	text = delta_text(obj)
	if text:
		ui.out.print(escape(text), end="")
		printed_delta = True

	xy = extract_xy(obj)
	if not xy:
		# OpenAI finish_reason stop → newline if we streamed text
		choices = obj.get("choices")
		if (
			isinstance(choices, list)
			and choices
			and isinstance(choices[0], dict)
			and choices[0].get("finish_reason")
			and saw_delta
		):
			ui.out.print()
		return printed_delta

	kind = str(xy.get("type") or "")
	if kind in (
		"permission_pending",
		"ask_user_pending",
		"plan_pending",
		"tool_call",
		"tool_result",
		"stopped",
	):
		if saw_delta or printed_delta:
			ui.out.print()
	_resolve_xy(client, xy, json_mode=False)
	return printed_delta


def _resolve_xy(
	client: httpx.Client, xy: dict[str, Any], *, json_mode: bool
) -> None:
	kind = str(xy.get("type") or "")
	try:
		if kind == "permission_pending":
			rid = str(xy.get("request_id") or "")
			if not rid:
				return
			decision = prompt_permission(
				tool=str(xy.get("tool_name") or ""),
				prompt=str(xy.get("prompt") or xy.get("reason") or ""),
				choices=list(xy.get("choices") or []),
				peer_summary=str(xy.get("peer_summary") or ""),
				json_mode=json_mode,
			)
			http_api.resolve_permission_http(
				client,
				rid,
				approved=decision.approved,
				choice=decision.choice,
			)
		elif kind == "ask_user_pending":
			rid = str(xy.get("request_id") or "")
			if not rid:
				return
			decision = prompt_ask(
				question=str(xy.get("question") or ""),
				options=list(xy.get("options") or []),
				default=xy.get("default"),
				json_mode=json_mode,
			)
			http_api.resolve_ask_http(client, rid, decision.answer)
		elif kind == "plan_pending":
			rid = str(xy.get("request_id") or "")
			if not rid:
				return
			decision = prompt_plan(
				plan_preview=str(xy.get("plan") or ""),
				json_mode=json_mode,
			)
			http_api.resolve_plan_http(client, rid, decision.approved)
		elif kind == "tool_call" and not json_mode:
			name = str(xy.get("name") or xy.get("tool_name") or "?")
			summary = ""
			inp = xy.get("input") or xy.get("tool_input")
			if isinstance(inp, dict):
				for key in ("path", "file_path", "command", "pattern", "query", "url"):
					val = inp.get(key)
					if isinstance(val, str) and val.strip():
						summary = val.strip().replace("\n", " ")
						if len(summary) > 100:
							summary = summary[:97] + "..."
						break
			ui.out.print(ui.tool_call_line(name, summary))
		elif kind == "tool_result" and not json_mode:
			name = str(xy.get("name") or xy.get("tool_name") or "?")
			err = bool(xy.get("is_error"))
			out = str(xy.get("output") or "").replace("\n", " ").strip()
			if len(out) > 120:
				out = out[:117] + "..."
			ui.out.print(ui.tool_result_line(name, out, is_error=err))
		elif kind == "stopped" and not json_mode:
			ui.out.print("[dim]■ stopped[/dim]")
	except Exception as exc:  # noqa: BLE001
		console.print(f"[bold red]✗ resolve failed[/bold red]: {exc}")
