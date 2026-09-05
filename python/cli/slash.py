"""REPL 斜杠命令 —— 统一 manifest 的 CLI-Py 面。

命令元数据全部来自 :mod:`slash.registry`；server 命令进程内调
:func:`slash.dispatch`（同引擎），client 命令在此本地处理。**不要在此新增
命令条目**——新命令先加 registry，再决定各面本地行为。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from slash.dispatch import CommandResult, DispatchContext, dispatch
from slash.registry import parse_slash


@dataclass
class SlashResult:
	handled: bool
	message: str = ""
	exit_repl: bool = False
	rebuild_engine: bool = False
	agent_mode: str | None = None
	# --- 扩展字段（client 命令向 REPL 传意图） ---
	#: /run <cmd> → 本轮改发这段提示词（交给模型用 Bash 工具，走权限门禁）
	prompt_override: str | None = None
	#: /retry → 重发上一条用户消息
	resend_last: bool = False
	#: /load <sid> → 用该 session id 重建 engine
	load_session: str | None = None
	#: /model <id> → 用该模型重建 engine
	model_override: str | None = None


def _mode_result(mode: str, set_agent_mode: Callable[[str], None]) -> SlashResult:
	set_agent_mode(mode)
	return SlashResult(handled=True, agent_mode=mode, message="")


def _client_level(lvl: str) -> tuple[bool, str]:
	"""/output /code 档位解析：返回 (开启?, 归一档位)。"""
	l = (lvl or "").strip().lower()
	if l in ("", "lite", "full", "ultra"):
		return True, (l or "lite")
	if l in ("off", "on", "关", "开"):
		return l not in ("off", "关"), "lite"
	return True, "lite"


def handle_slash(
	line: str,
	*,
	engine: Any,
	set_agent_mode: Callable[[str], None],
) -> SlashResult:
	text = (line or "").strip()
	if not text.startswith("/"):
		return SlashResult(handled=False)

	cmd, arg = parse_slash(text)
	if cmd is None:
		unknown = text[1:].split(None, 1)[0] if text[1:].strip() else ""
		return SlashResult(
			handled=True,
			message=f"未知命令 /{unknown}，试试 /help",
		)

	# ---- client 命令 ----
	name = cmd.name
	if name == "help":
		# chat_cmd 对 /help 走 ui.help_panel()；这里不重复输出
		return SlashResult(handled=True, message="")
	if name == "exit":
		return SlashResult(handled=True, exit_repl=True, message="")
	if name == "clear":
		return SlashResult(
			handled=True, rebuild_engine=True, message="cleared — new session"
		)
	if name == "mode":
		m = (arg or "").strip().lower()
		if m not in ("agent", "plan", "ask"):
			return SlashResult(
				handled=True, message="用法：/mode <agent|plan|ask>"
			)
		return _mode_result(m, set_agent_mode)
	if name in ("output", "code"):
		from permissions.policy import (
			set_code_compact,
			set_code_mode,
			set_output_compact,
			set_output_mode,
		)

		on, lvl = _client_level(arg)
		if name == "output":
			set_output_compact(on)
			set_output_mode(lvl if on else None)
		else:
			set_code_compact(on)
			set_code_mode(lvl if on else None)
		which = "输出精简" if name == "output" else "写代码精简"
		return SlashResult(
			handled=True,
			message=f"{which} {'on' if on else 'off'}"
			+ (f"（{lvl}）" if on else ""),
		)
	if name == "reasoning-tail":
		val = (arg or "").strip().lower()
		if val not in ("on", "off", "开", "关"):
			return SlashResult(
				handled=True, message="用法：/reasoning-tail <on|off>"
			)
		from permissions.policy import set_reasoning_tail_enabled

		on = val in ("on", "开")
		set_reasoning_tail_enabled(on)
		return SlashResult(
			handled=True, message=f"上一轮思考回顾 {'on' if on else 'off'}"
		)
	if name == "approval":
		from permissions.policy import set_permission_mode

		m = (arg or "").strip().lower()
		if m not in ("always", "risk", "never"):
			return SlashResult(
				handled=True, message="用法：/approval <always|risk|never>"
			)
		set_permission_mode(m)
		return SlashResult(handled=True, message=f"审批模式 → {m}")
	if name == "model":
		mid = (arg or "").strip()
		if not mid:
			return SlashResult(handled=True, message="用法：/model <model_id>")
		return SlashResult(handled=True, model_override=mid, message="")
	if name == "theme":
		return SlashResult(handled=True, message="主题切换仅桌面端可用。")
	if name == "retry":
		return SlashResult(handled=True, resend_last=True, message="")
	if name == "run":
		cmd_text = (arg or "").strip()
		if not cmd_text:
			return SlashResult(handled=True, message="用法：/run <command>")
		prompt = (
			"[slash:/run] 请用 Bash 工具执行以下命令并汇总结果（遵守权限门禁，"
			"不要执行无关命令）：\n\n" + cmd_text
		)
		return SlashResult(handled=True, prompt_override=prompt, message="")
	if name == "load":
		sid = (arg or "").strip()
		if not sid:
			return SlashResult(handled=True, message="用法：/load <session_id>")
		return SlashResult(handled=True, load_session=sid, message="")
	if name == "version":
		from cli import __version__

		return SlashResult(handled=True, message=f"XEYO CLI v{__version__}")
	if name == "docs":
		import os
		from pathlib import Path

		docs = Path(__file__).resolve().parents[2] / "docs"
		msg = f"文档目录：{docs}"
		if os.name == "nt" and docs.is_dir():
			try:
				os.startfile(str(docs))  # noqa: S606
			except OSError:
				pass
		return SlashResult(handled=True, message=msg)
	if name == "demo":
		return SlashResult(handled=True, message="/demo 仅 TypeScript CLI 提供。")

	# ---- server 命令：进程内 dispatch（同引擎） ----
	ctx = DispatchContext(
		session_id=str(getattr(engine, "session_id", "") or ""),
		engine=engine,
		surfaces=("cli",),
	)
	res = dispatch(cmd.name, arg, ctx=ctx)
	return SlashResult(handled=True, message=res.message)
