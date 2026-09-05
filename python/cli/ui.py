"""Shared Rich visual chrome for the XEYO CLI (human mode only)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from cli.logo import LOGO_GLYPH, banner_body

# Soft teal + amber — readable on dark/light terminals, not purple/glow.
ACCENT = "cyan"
WARN = "yellow"
OK = "green"
ERR = "red"
MUTED = "dim"

out = Console(stderr=False)
err = Console(stderr=True)


def brand_mark() -> Text:
	t = Text()
	t.append(f"{LOGO_GLYPH} ", style=f"bold {ACCENT}")
	t.append("XEYO", style=f"bold {ACCENT}")
	return t


def print_banner(
	*,
	session_id: str,
	cwd: str,
	mode: str,
	provider: str = "",
	model: str = "",
	restored: int = 0,
) -> None:
	"""Startup header for interactive chat / attach — icon + I am XEYO."""
	cwd_name = Path(cwd).name or cwd
	meta = Table.grid(padding=(0, 2))
	meta.add_column(style=MUTED, justify="right")
	meta.add_column()
	meta.add_row("session", Text(session_id, style="bold"))
	meta.add_row("workspace", Text(f"{cwd_name}  ", style="bold") + Text(cwd, style=MUTED))
	meta.add_row("mode", Text(mode, style=f"bold {ACCENT}"))
	if provider or model:
		meta.add_row(
			"model",
			f"{provider}/{model}" if provider and model else (model or provider),
		)
	meta.add_row(
		"history",
		f"{restored} message{'s' if restored != 1 else ''} restored",
	)

	out.print()
	out.print(
		Panel(
			banner_body(meta, accent=ACCENT, muted=MUTED),
			border_style=ACCENT,
			padding=(1, 2),
		)
	)
	out.print(
		Text(
			"  /help · /plan · /ask · /clear · /exit    Ctrl+C stops the turn",
			style=MUTED,
		)
	)
	out.print()


def print_rule(label: str = "") -> None:
	if label:
		out.print(Rule(label, style=MUTED))
	else:
		out.print(Rule(style=MUTED))


def session_chip(session_id: str, *, restored: int | None = None) -> None:
	line = Text()
	line.append(f"{LOGO_GLYPH} ", style=ACCENT)
	line.append("session ", style=MUTED)
	line.append(session_id, style="bold")
	if restored is not None:
		line.append(f"  ·  restored {restored}", style=MUTED)
	out.print(line)


def repl_prompt_text(*, mode: str = "agent") -> Text:
	t = Text()
	t.append(f"{LOGO_GLYPH} ", style=f"bold {ACCENT}")
	if mode and mode != "agent":
		t.append(f"{mode} ", style=WARN)
	return t


def help_panel() -> Panel:
	"""帮助面板 —— 由统一 manifest（slash.registry）生成，勿手写命令表。"""
	from slash.registry import COMMANDS

	table = Table(show_header=False, box=None, padding=(0, 1))
	table.add_column(style=f"bold {ACCENT}", width=24)
	table.add_column(style=MUTED)
	rows: list[tuple[str, str]] = []
	for c in COMMANDS:
		if "cli" not in c.surfaces:
			continue
		if c.name == "mode":
			# /mode 已含 plan/ask/agent 三个旧命令
			rows.append((c.usage, f"{c.summary}（原 /plan /ask /agent）"))
			continue
		note = f"（{'/'.join(c.aliases[:3])}）" if c.aliases else ""
		rows.append((c.usage, f"{c.summary}{note}"))
	for a, b in rows:
		table.add_row(a, b)
	return Panel(table, title=brand_mark(), subtitle="slash commands", border_style=ACCENT)


def permission_panel(
	*,
	tool: str,
	prompt: str,
	choices: list[str] | None = None,
	peer_summary: str = "",
) -> Panel:
	body = Text()
	body.append(tool, style=f"bold {WARN}")
	body.append("\n")
	body.append(prompt or "Needs confirmation", style="")
	if peer_summary.strip():
		body.append("\n")
		body.append(peer_summary.strip()[:120], style=MUTED)
	hint = Text("\n\n", style="")
	hint.append("[a]", style=f"bold {OK}")
	hint.append("llow  ", style=MUTED)
	hint.append("[d]", style=f"bold {ERR}")
	hint.append("eny  ", style=MUTED)
	hint.append("[r]", style=f"bold {WARN}")
	hint.append("emind", style=MUTED)
	if choices:
		hint.append(f"\nchoices: {', '.join(str(c) for c in choices)}", style=MUTED)
	return Panel(
		Group(body, hint),
		title=Text(" permission ", style=f"bold {WARN}"),
		border_style=WARN,
		padding=(0, 1),
	)


def ask_panel(*, question: str, options: list[str] | None = None) -> Panel:
	body = Text(question or "", style="bold")
	if options:
		body.append("\n")
		for i, opt in enumerate(options, 1):
			body.append(f"\n  {i}. {opt}", style=MUTED)
	return Panel(
		body,
		title=Text(" ask ", style=f"bold {ACCENT}"),
		border_style=ACCENT,
		padding=(0, 1),
	)


def plan_panel(preview: str) -> Panel:
	snip = (preview or "").strip()
	if len(snip) > 600:
		snip = snip[:597] + "..."
	return Panel(
		snip or "(empty plan)",
		title=Text(" plan ", style=f"bold {WARN}"),
		border_style=WARN,
		padding=(0, 1),
	)


def tool_call_line(name: str, summary: str) -> Text:
	t = Text()
	t.append("→ ", style=f"bold {ACCENT}")
	t.append(name, style=f"bold {ACCENT}")
	if summary:
		t.append("  ")
		t.append(summary, style=MUTED)
	return t


def tool_result_line(name: str, snip: str, *, is_error: bool) -> Text:
	t = Text()
	style = ERR if is_error else OK
	t.append("← ", style=f"bold {style}")
	t.append(name, style=f"bold {style}")
	if snip:
		t.append("  ")
		t.append(snip, style=MUTED)
	return t


def tool_progress_line(name: str, message: str, elapsed_ms: int) -> Text:
	t = Text()
	t.append("… ", style=MUTED)
	t.append(name, style=ACCENT)
	if message:
		t.append(f"  {message}", style=MUTED)
	if elapsed_ms:
		t.append(f"  {elapsed_ms}ms", style=MUTED)
	return t


def usage_line(
	*,
	prompt_tokens: int = 0,
	completion_tokens: int = 0,
	used_usd: float = 0.0,
) -> Text:
	t = Text()
	t.append("  ⌁ ", style=MUTED)
	parts: list[str] = []
	if prompt_tokens or completion_tokens:
		parts.append(f"in {prompt_tokens} · out {completion_tokens}")
	if used_usd:
		parts.append(f"${used_usd:.4f}")
	t.append("  ".join(parts) or "usage", style=MUTED)
	return t
