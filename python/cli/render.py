"""Rich / JSONL event renderer."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

from rich.markup import escape

from cli import ui
from msgtypes.events import (
	AskUserPendingEvent,
	AssistantDelta,
	FinalEvent,
	PermissionPendingEvent,
	PlanPendingEvent,
	ReasoningDelta,
	ResultEvent,
	StoppedEvent,
	ToolCallEvent,
	ToolProgressEvent,
	ToolResultEvent,
	UsageEvent,
)

console = ui.out


def event_to_dict(ev: Any) -> dict[str, Any]:
	if is_dataclass(ev):
		return asdict(ev)
	if isinstance(ev, dict):
		return ev
	return {"type": type(ev).__name__, "repr": repr(ev)}


class EventRenderer:
	def __init__(self, *, json_mode: bool = False) -> None:
		self.json_mode = json_mode
		self._open = False
		self._saw_assistant_delta = False
		self._status = None
		self._last_usage: UsageEvent | None = None

	def reset_turn(self) -> None:
		self.stop_status()
		self.newline()
		self._saw_assistant_delta = False
		self._last_usage = None
		if not self.json_mode:
			self._status = console.status(
				"[dim]thinking…[/dim]", spinner="dots", spinner_style=ui.ACCENT
			)
			self._status.start()

	def stop_status(self) -> None:
		if self._status is not None:
			try:
				self._status.stop()
			except Exception:
				pass
			self._status = None

	def emit(self, ev: Any) -> None:
		if self.json_mode:
			sys.stdout.write(json.dumps(event_to_dict(ev), ensure_ascii=False) + "\n")
			sys.stdout.flush()
			return
		self._rich(ev)

	def newline(self) -> None:
		if self._open:
			console.print()
			self._open = False

	def finish_turn(self) -> None:
		self.stop_status()
		self.newline()
		if self._last_usage and not self.json_mode:
			u = self._last_usage
			console.print(
				ui.usage_line(
					prompt_tokens=int(u.prompt_tokens or 0),
					completion_tokens=int(u.completion_tokens or 0),
					used_usd=float(u.used_usd or u.usd or 0.0),
				)
			)

	def _rich(self, ev: Any) -> None:
		if isinstance(ev, AssistantDelta):
			text = ev.text or ""
			if text:
				self.stop_status()
				console.print(escape(text), end="")
				self._open = True
				self._saw_assistant_delta = True
			return
		if isinstance(ev, ReasoningDelta):
			text = ev.text or ""
			if text and not self._saw_assistant_delta:
				# Soft dim stream for reasoning before answer.
				self.stop_status()
				console.print(f"[dim italic]{escape(text)}[/dim italic]", end="")
				self._open = True
			return
		if isinstance(ev, UsageEvent):
			self._last_usage = ev
			return
		if isinstance(ev, ToolProgressEvent):
			self.stop_status()
			self.newline()
			console.print(
				ui.tool_progress_line(
					ev.name or "tool",
					ev.message or "",
					int(ev.elapsed_ms or 0),
				)
			)
			return

		self.stop_status()
		self.newline()
		if isinstance(ev, ToolCallEvent):
			summary = _summary(ev.input if isinstance(ev.input, dict) else {})
			console.print(ui.tool_call_line(ev.name, summary))
		elif isinstance(ev, ToolResultEvent):
			snip = str(ev.output or "").replace("\n", " ").strip()
			if len(snip) > 120:
				snip = snip[:117] + "..."
			console.print(ui.tool_result_line(ev.name, snip, is_error=bool(ev.is_error)))
		elif isinstance(ev, (PermissionPendingEvent, AskUserPendingEvent, PlanPendingEvent)):
			# Full panels are drawn by interact prompts to avoid double chrome.
			pass
		elif isinstance(ev, FinalEvent):
			if ev.text and not self._saw_assistant_delta:
				console.print(escape(ev.text))
		elif isinstance(ev, ResultEvent) and ev.is_error:
			console.print(f"[bold red]✗[/bold red] [red]{escape(ev.subtype or 'error')}[/red]")
		elif isinstance(ev, StoppedEvent):
			console.print("[dim]■ stopped[/dim]")


def _summary(inp: dict[str, Any]) -> str:
	for key in ("path", "file_path", "command", "pattern", "query", "url"):
		val = inp.get(key)
		if isinstance(val, str) and val.strip():
			s = val.strip().replace("\n", " ")
			return s if len(s) <= 100 else s[:97] + "..."
	raw = json.dumps(inp, ensure_ascii=False)
	return raw if len(raw) <= 100 else raw[:97] + "..."
