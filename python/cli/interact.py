"""Shared permission / ask / plan prompts (fail-closed without TTY)."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Any, Literal

from cli import ui
from engine.plan import default_plan_engine
from permissions.ask_store import default_ask_store
from permissions.store import (
	USER_CHOICE_ALLOW,
	USER_CHOICE_DENY,
	USER_CHOICE_REMIND,
	default_permission_store,
)

console = ui.err

PermissionChoice = Literal["allow", "deny", "remind"]


@dataclass(frozen=True)
class PermissionDecision:
	choice: PermissionChoice
	approved: bool
	actor: str
	headless: bool = False


@dataclass(frozen=True)
class AskDecision:
	answer: str
	actor: str
	headless: bool = False


@dataclass(frozen=True)
class PlanDecision:
	approved: bool
	actor: str
	headless: bool = False


def is_tty() -> bool:
	try:
		return bool(sys.stdin.isatty())
	except Exception:
		return False


def parse_permission_choice(raw: str) -> PermissionChoice:
	text = (raw or "").strip().lower()
	if text in ("a", "allow", "y", "yes", "1") or text == USER_CHOICE_ALLOW:
		return USER_CHOICE_ALLOW  # type: ignore[return-value]
	if text in ("r", "remind") or text == USER_CHOICE_REMIND:
		return USER_CHOICE_REMIND  # type: ignore[return-value]
	return USER_CHOICE_DENY  # type: ignore[return-value]


def parse_plan_approved(raw: str) -> bool:
	return (raw or "").strip().lower() in ("y", "yes", "a", "approve", "1")


def _readline(prompt: str) -> str:
	console.print(prompt, end="")
	try:
		return sys.stdin.readline()
	except Exception:
		return ""


def prompt_permission(
	*,
	tool: str,
	prompt: str,
	choices: list[str] | None = None,
	peer_summary: str = "",
	json_mode: bool = False,
	force_headless: bool = False,
) -> PermissionDecision:
	"""Interactive or fail-closed permission choice (no side effects)."""
	headless = force_headless or json_mode or not is_tty()
	if headless:
		if not json_mode:
			console.print(f"[bold red]✗ denied[/bold red] [dim]{tool} (no TTY; fail-closed)[/dim]")
		return PermissionDecision(
			choice="deny", approved=False, actor="cli-headless", headless=True
		)
	console.print(
		ui.permission_panel(
			tool=tool,
			prompt=prompt,
			choices=choices,
			peer_summary=peer_summary,
		)
	)
	line = _readline(f"[{ui.WARN}]decision[/] [a/d/r] › ")
	choice = parse_permission_choice(line)
	if choice == "allow":
		console.print(f"[bold {ui.OK}]✓ allowed[/bold {ui.OK}] [dim]{tool}[/dim]")
	elif choice == "remind":
		console.print(f"[bold {ui.WARN}]↻ remind[/bold {ui.WARN}] [dim]{tool}[/dim]")
	else:
		console.print(f"[bold {ui.ERR}]✗ denied[/bold {ui.ERR}] [dim]{tool}[/dim]")
	return PermissionDecision(
		choice=choice,
		approved=choice == "allow",
		actor="cli",
		headless=False,
	)


def prompt_ask(
	*,
	question: str,
	options: list[str] | None = None,
	default: str | None = None,
	json_mode: bool = False,
	force_headless: bool = False,
) -> AskDecision:
	headless = force_headless or json_mode or not is_tty()
	if headless:
		answer = str(default) if default is not None else ""
		if not json_mode:
			console.print("[dim]ask answered with default (no TTY)[/dim]")
		return AskDecision(answer=answer, actor="cli-headless", headless=True)
	console.print(ui.ask_panel(question=question, options=options))
	line = _readline(f"[{ui.ACCENT}]answer[/] › ")
	answer = (line or "").rstrip("\n")
	if not answer and default is not None:
		answer = str(default)
	return AskDecision(answer=answer, actor="cli", headless=False)


def prompt_plan(
	*,
	plan_preview: str = "",
	json_mode: bool = False,
	force_headless: bool = False,
) -> PlanDecision:
	headless = force_headless or json_mode or not is_tty()
	if headless:
		if not json_mode:
			console.print(f"[bold {ui.ERR}]✗ plan rejected[/bold {ui.ERR}] [dim](no TTY; fail-closed)[/dim]")
		return PlanDecision(approved=False, actor="cli-headless", headless=True)
	if plan_preview.strip():
		console.print(ui.plan_panel(plan_preview))
	line = _readline(f"[{ui.WARN}]approve plan?[/] [y/n] › ")
	approved = parse_plan_approved(line)
	if approved:
		console.print(f"[bold {ui.OK}]✓ plan approved[/bold {ui.OK}]")
	else:
		console.print(f"[bold {ui.ERR}]✗ plan rejected[/bold {ui.ERR}]")
	return PlanDecision(approved=approved, actor="cli", headless=False)


async def resolve_permission_interactive(ev: Any, *, json_mode: bool = False) -> None:
	request_id = str(getattr(ev, "request_id", "") or "")
	if not request_id:
		return
	decision = await asyncio.to_thread(
		prompt_permission,
		tool=str(getattr(ev, "tool_name", "") or ""),
		prompt=str(getattr(ev, "prompt", "") or getattr(ev, "reason", "") or ""),
		choices=list(getattr(ev, "choices", None) or []),
		peer_summary=str(getattr(ev, "peer_summary", "") or ""),
		json_mode=json_mode,
	)
	default_permission_store().resolve(
		request_id,
		decision.approved,
		actor=decision.actor,
		choice=decision.choice,
	)


async def resolve_ask_interactive(ev: Any, *, json_mode: bool = False) -> None:
	request_id = str(getattr(ev, "request_id", "") or "")
	if not request_id:
		return
	decision = await asyncio.to_thread(
		prompt_ask,
		question=str(getattr(ev, "question", "") or ""),
		options=list(getattr(ev, "options", None) or []),
		default=getattr(ev, "default", None),
		json_mode=json_mode,
	)
	default_ask_store().resolve_answer(
		request_id, decision.answer, actor=decision.actor
	)


async def resolve_plan_interactive(ev: Any, *, json_mode: bool = False) -> None:
	request_id = str(getattr(ev, "request_id", "") or "")
	if not request_id:
		return
	decision = await asyncio.to_thread(
		prompt_plan,
		plan_preview=str(getattr(ev, "plan", "") or ""),
		json_mode=json_mode,
	)
	default_plan_engine().resolve(
		request_id, decision.approved, actor=decision.actor
	)
