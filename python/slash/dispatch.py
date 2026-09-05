"""服务端斜杠命令 dispatcher —— 统一执行 ``handler=server`` 的命令。

被以下面复用：
- HTTP 路由 ``POST /v1/slash``（GUI / CLI-TS 调它）
- CLI-Py 进程内（``cli/slash.py`` 处理 server 命令时直接调 :func:`dispatch`）
- 微信远程通道（``filehelper/commands.py`` / ``ilink/service.py`` 命令处理改调此处）

设计约束：
- **不通模型、不改 MessageStore / JSONL**：本模块只做「查询会话状态 / 触发已存在的
  后端动作 / 只读 git / 扩展清单 / XEYO.md 维护」类事务。模式/精简/模型/主题/审批
  等开关是 client 命令，由发起面改请求体 / contextvar（AGENTS.md 的 T_now 范式）。
- 依赖全部惰性导入 + try/except 降级：单条命令失败不影响其它命令与请求主链路。
- 返回结构化 :class:`CommandResult`，各面据此渲染。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .registry import Command, get_command, help_text


@dataclass
class CommandResult:
	handled: bool
	kind: str  # info|control|memory|tool|extension|session|help|unknown
	message: str = ""
	result: dict[str, Any] | None = None


@dataclass
class DispatchContext:
	"""命令执行上下文。

	- 进程内（CLI-Py / 远程通道）：给 ``session_id``/``workspace`` + 可选 ``engine``。
	- HTTP（``/v1/slash``）：给 ``session_id``/``workspace``/``provider``/``api_key``/
	  ``base_url``/``model``；engine 由 pool 按 session_id 解析。
	"""

	session_id: str = ""
	workspace: str = ""
	engine: Any | None = None
	provider: str = ""
	api_key: str = ""
	base_url: str = ""
	model: str = ""
	surfaces: tuple[str, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
# 解析辅助
# --------------------------------------------------------------------------- #

def _workspace(ctx: DispatchContext) -> str:
	ws = (ctx.workspace or "").strip()
	if ws:
		return ws
	engine = ctx.engine
	if engine is None and ctx.session_id:
		try:
			from server.deps import _pool

			engine = _pool.get_if_present(ctx.session_id)
		except Exception:
			engine = None
	if engine is not None:
		try:
			cfg_cwd = str((getattr(engine, "config", None) or {}).get("cwd") or "")
			if cfg_cwd:
				return cfg_cwd
		except Exception:
			pass
		try:
			from engine.workspace_context import get_cwd

			return str(get_cwd() or "")
		except Exception:
			return ""
	return ""


def _session_engine(ctx: DispatchContext) -> Any:
	if ctx.engine is not None:
		return ctx.engine
	if not ctx.session_id:
		return None
	try:
		from server.deps import _pool

		return _pool.get_if_present(ctx.session_id)
	except Exception:
		return None


def _turn_running(ctx: DispatchContext) -> bool | None:
	try:
		from engine.turn_runner import get_turn_runner

		return bool(get_turn_runner().is_running(ctx.session_id))
	except Exception:
		return None


def _reject_if_busy(ctx: DispatchContext) -> CommandResult | None:
	"""改会话状态的命令在回合运行中拒绝（/status /allow /deny /stop 除外）。"""
	if _turn_running(ctx) is True:
		return CommandResult(
			handled=True,
			kind="control",
			message="会话正忙，请先停止当前回合再试。",
			result={"ok": False, "busy": True},
		)
	return None


def _parse_int(raw: str, *, default: int, lo: int, hi: int) -> int:
	try:
		val = int((raw or "").strip())
	except (TypeError, ValueError):
		return default
	return max(lo, min(hi, val))


def _flatten_content(content: Any, *, limit: int = 240) -> str:
	if content is None:
		return ""
	if isinstance(content, str):
		text = content
	elif isinstance(content, list):
		parts: list[str] = []
		for block in content:
			if not isinstance(block, dict):
				continue
			t = block.get("text") or block.get("content")
			if isinstance(t, str):
				parts.append(t)
			elif block.get("type") == "tool_result":
				out = block.get("output") or block.get("content")
				if isinstance(out, str):
					parts.append(out)
		text = " ".join(parts)
	else:
		text = str(content)
	text = " ".join(text.split())
	return text if len(text) <= limit else text[:limit] + "…"


# --------------------------------------------------------------------------- #
# info
# --------------------------------------------------------------------------- #

def _cmd_status(ctx: DispatchContext, arg: str) -> CommandResult:
	payload: dict[str, Any] = {"session_id": ctx.session_id}
	payload["cwd"] = _workspace(ctx)
	payload["running"] = _turn_running(ctx)
	try:
		from permissions.store import default_permission_store

		pend = default_permission_store().pending_for_session(ctx.session_id)
		if pend:
			payload["pending_permission"] = {
				"request_id": pend.request_id,
				"tool_name": pend.tool_name,
				"prompt": pend.prompt,
			}
	except Exception:
		pass
	try:
		from channels.api import get_store

		store = get_store()
		if store is not None:
			payload["recent_jobs"] = [
				r.to_public()
				for r in store.recent(8, session_id=ctx.session_id or None)
			]
	except Exception:
		pass

	lines = [
		f"会话 {ctx.session_id or '(未指定)'}",
		f"工作区 {payload['cwd'] or '(未绑定)'}",
	]
	if payload["running"] is True:
		lines.append("状态 运行中")
	elif payload["running"] is False:
		lines.append("状态 空闲")
	pend = payload.get("pending_permission")
	if pend:
		lines.append(f"待批准 {pend['tool_name']}：{str(pend['prompt'])[:80]}")
	jobs = payload.get("recent_jobs") or []
	if jobs:
		lines.append(f"最近任务 {len(jobs)} 条（最新 {jobs[0].get('status')}）")
	return CommandResult(handled=True, kind="info", message="\n".join(lines), result=payload)


def _cmd_cwd(ctx: DispatchContext, arg: str) -> CommandResult:
	ws = _workspace(ctx)
	return CommandResult(
		handled=True,
		kind="info",
		message=f"工作区 {ws or '(未绑定)'}",
		result={"cwd": ws},
	)


def _cmd_usage(ctx: DispatchContext, arg: str) -> CommandResult:
	days = _parse_int(arg, default=30, lo=1, hi=366)
	from usage.combine import compose_usage_report
	from usage.ledger import query_usage

	prov = (ctx.provider or "deepseek").lower()
	local = query_usage(days=days, model=None, provider=prov, key_fp=None)
	vendor: dict[str, Any] = {"vendor_ok": False, "vendor_error": "no api key"}
	if (ctx.api_key or "").strip():
		try:
			from usage.vendor import fetch_vendor_usage

			vendor = fetch_vendor_usage(
				api_key=ctx.api_key,
				provider=prov,
				base_url=ctx.base_url or None,
				days=days,
				model=None,
				key_fp=None,
			)
		except Exception as exc:  # noqa: BLE001
			vendor = {"vendor_ok": False, "vendor_error": str(exc)}
	report = compose_usage_report(vendor, local)
	totals = report.get("totals") or {}
	tokens = totals.get("tokens") or totals.get("total_tokens") or 0
	cost = totals.get("cost") or totals.get("total_cost") or 0
	reqs = totals.get("requests") or 0
	source = report.get("source") or "local"
	msg = f"近 {days} 天用量（来源 {source}）：请求 {reqs}，tokens {tokens}，成本 {cost}"
	return CommandResult(handled=True, kind="info", message=msg, result={"report": report})


def _cmd_context(ctx: DispatchContext, arg: str) -> CommandResult:
	engine = _session_engine(ctx)
	session = getattr(engine, "_session", None) if engine is not None else None
	if session is None:
		return CommandResult(
			handled=True,
			kind="info",
			message="context：没有可用会话。",
			result={"ok": False},
		)
	working = getattr(session, "working", None)
	msgs = session.messages.as_api_messages()
	payload: dict[str, Any] = {
		"session_id": ctx.session_id,
		"messages": len(msgs),
		"compact_cursor": int(getattr(working, "compact_cursor", 0) or 0),
		"c2_summary_chars": len(getattr(working, "c2_summary_text", "") or ""),
		"todos": len(getattr(working, "todos", None) or []),
	}
	lines = [
		f"消息 {payload['messages']} 条",
		f"压缩游标 {payload['compact_cursor']}",
		f"C2 摘要 {payload['c2_summary_chars']} 字",
		f"todos {payload['todos']} 项",
	]
	return CommandResult(handled=True, kind="info", message="\n".join(lines), result=payload)


def _cmd_ls(ctx: DispatchContext, arg: str) -> CommandResult:
	ws = _workspace(ctx)
	if not ws:
		return CommandResult(handled=True, kind="info", message="未绑定工作区。", result={"ok": False})
	base = Path(ws).resolve()
	target = base
	if (arg or "").strip():
		cand = (base / arg.strip()).resolve()
		try:
			cand.relative_to(base)
		except ValueError:
			return CommandResult(
				handled=True,
				kind="info",
				message="路径越出工作区，已拒绝。",
				result={"ok": False},
			)
		target = cand
	if not target.is_dir():
		return CommandResult(
			handled=True, kind="info", message=f"不是目录：{target}", result={"ok": False}
		)
	try:
		entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
	except OSError as exc:
		return CommandResult(handled=True, kind="info", message=f"读取失败：{exc}", result={"ok": False})
	rows = [f"{p.name}{'/' if p.is_dir() else ''}" for p in entries[:60]]
	rel = target.relative_to(base) if target != base else Path(".")
	suffix = "，显示前 60" if len(entries) > 60 else ""
	msg = f"{rel}（{len(entries)} 项{suffix}）\n" + "\n".join(rows)
	return CommandResult(
		handled=True,
		kind="info",
		message=msg,
		result={"path": str(target), "count": len(entries)},
	)


# --------------------------------------------------------------------------- #
# control
# --------------------------------------------------------------------------- #

def _cmd_stop(ctx: DispatchContext, arg: str) -> CommandResult:
	if not ctx.session_id:
		return CommandResult(
			handled=True, kind="control", message="当前无会话，无法中断。", result={"ok": False}
		)
	try:
		from engine.turn_runner import get_turn_runner

		get_turn_runner().mark_stopping(ctx.session_id, reason="user_stop")
	except Exception:
		pass
	ok = False
	if ctx.engine is not None:
		try:
			ctx.engine.interrupt()
			ok = True
		except Exception:
			ok = False
	else:
		try:
			from server.deps import _pool

			ok = bool(_pool.interrupt(ctx.session_id))
		except Exception:
			ok = False
	return CommandResult(
		handled=True,
		kind="control",
		message="已请求中断。" if ok else "未找到正在运行的回合。",
		result={"ok": ok},
	)


def _cmd_allow_deny(ctx: DispatchContext, arg: str, *, approved: bool) -> CommandResult:
	from permissions.store import default_permission_store

	store = default_permission_store()
	request_id = arg.strip()
	if not request_id:
		pend = store.pending_for_session(ctx.session_id)
		if pend is None:
			return CommandResult(
				handled=True,
				kind="control",
				message="当前没有待确认的操作。",
				result={"ok": False},
			)
		request_id = pend.request_id
	ok = store.resolve(
		request_id,
		approved,
		actor="slash",
		choice="allow" if approved else "deny",
	)
	verb = "已批准" if approved else "已拒绝"
	return CommandResult(
		handled=True,
		kind="control",
		message=f"{verb}请求 {request_id}" if ok else "未找到该请求（可能已过期或已处理）。",
		result={"ok": ok, "request_id": request_id},
	)


# --------------------------------------------------------------------------- #
# memory
# --------------------------------------------------------------------------- #

def _cmd_compact(ctx: DispatchContext, arg: str) -> CommandResult:
	blocked = _reject_if_busy(ctx)
	if blocked is not None:
		return blocked
	engine = _session_engine(ctx)
	session = getattr(engine, "_session", None) if engine is not None else None
	if session is None:
		return CommandResult(
			handled=True, kind="memory", message="compact：没有可用会话。", result={"ok": False}
		)
	try:
		from memory.runtime import force_compact
		from memory.working import flush

		msgs = session.messages.as_api_messages()
		before = int(getattr(session.working, "compact_cursor", 0) or 0)
		force_compact(msgs, session.working)
		flush(session.session_id, session.working)
		after = int(getattr(session.working, "compact_cursor", 0) or 0)
		chars = len(getattr(session.working, "c2_summary_text", "") or "")
		msg = (
			f"已压缩到 cursor {after}（此前 {before}），摘要 {chars} 字。"
			if after > before or chars
			else "历史过短或无可压缩区间，未推进 cursor。"
		)
		return CommandResult(
			handled=True,
			kind="memory",
			message=msg,
			result={"ok": True, "compact_cursor": after, "c2_summary_chars": chars},
		)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="memory", message=f"compact 失败：{exc}", result={"ok": False}
		)


def _cmd_transcript(ctx: DispatchContext, arg: str) -> CommandResult:
	engine = _session_engine(ctx)
	session = getattr(engine, "_session", None) if engine is not None else None
	if session is None:
		return CommandResult(
			handled=True, kind="memory", message="transcript：没有可用会话。", result={"ok": False}
		)
	n = _parse_int(arg, default=12, lo=1, hi=60)
	msgs = session.messages.as_api_messages()
	tail = msgs[-n:]
	role_zh = {"user": "你", "assistant": "XEYO", "tool": "工具", "system": "系统"}
	lines = [
		f"[{role_zh.get(str(m.get('role')), m.get('role'))}] {_flatten_content(m.get('content'))}"
		for m in tail
	]
	msg = "\n".join(lines) if lines else "(空会话)"
	return CommandResult(
		handled=True, kind="memory", message=msg, result={"ok": True, "count": len(tail)}
	)


def _cmd_export(ctx: DispatchContext, arg: str) -> CommandResult:
	blocked = _reject_if_busy(ctx)
	if blocked is not None:
		return blocked
	target_name = (arg or "").strip()
	if not target_name:
		return CommandResult(
			handled=True, kind="session", message="用法：/export <file.md>", result={"ok": False}
		)
	ws = _workspace(ctx)
	if not ws:
		return CommandResult(handled=True, kind="session", message="未绑定工作区。", result={"ok": False})
	base = Path(ws).resolve()
	out = (base / target_name).resolve()
	if out.suffix.lower() not in (".md", ".markdown"):
		out = out.with_name(out.name + ".md")
	try:
		out.relative_to(base)
	except ValueError:
		return CommandResult(
			handled=True, kind="session", message="导出路径越出工作区，已拒绝。", result={"ok": False}
		)
	engine = _session_engine(ctx)
	session = getattr(engine, "_session", None) if engine is not None else None
	if session is None:
		return CommandResult(
			handled=True, kind="session", message="export：没有可用会话。", result={"ok": False}
		)
	msgs = session.messages.as_api_messages()
	role_zh = {"user": "用户", "assistant": "XEYO", "tool": "工具", "system": "系统"}
	md_lines = [f"# XEYO 会话导出 — {ctx.session_id}", ""]
	for m in msgs:
		role = role_zh.get(str(m.get("role")), str(m.get("role")))
		md_lines += [f"## {role}", "", str(m.get("content") or ""), ""]
	try:
		out.write_text("\n".join(md_lines), encoding="utf-8")
	except OSError as exc:
		return CommandResult(
			handled=True, kind="session", message=f"写文件失败：{exc}", result={"ok": False}
		)
	return CommandResult(
		handled=True,
		kind="session",
		message=f"已导出 {len(msgs)} 条消息 → {out}",
		result={"ok": True, "path": str(out), "messages": len(msgs)},
	)


def _cmd_memory_instruction(ctx: DispatchContext, arg: str, *, name: str) -> CommandResult:
	ws = _workspace(ctx) or "."
	try:
		if name == "rule":
			from memory.instruction_maintain import append_rule_line

			return CommandResult(
				handled=True,
				kind="memory",
				message=append_rule_line(ws, arg.strip()),
				result={"ok": True},
			)
		if name == "doctor":
			from memory.instruction_maintain import doctor_xeyo_md, format_doctor_report

			return CommandResult(
				handled=True,
				kind="memory",
				message=format_doctor_report(doctor_xeyo_md(ws)),
				result={"ok": True},
			)
		if name == "proposals":
			from memory.instruction_maintain import (
				format_proposals_digest,
				list_pending_proposals,
			)
			from memory.memdir import workspace_id

			wsid = workspace_id(ws)
			digest = format_proposals_digest(wsid)
			if digest:
				msg = digest
			else:
				n = len(list_pending_proposals(wsid))
				msg = "暂无 XEYO.md 写入提案。" if n == 0 else f"提案 {n} 条（格式异常）。"
			return CommandResult(handled=True, kind="memory", message=msg, result={"ok": True})
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="memory", message=f"{name} 失败：{exc}", result={"ok": False}
		)
	return CommandResult(handled=True, kind="memory", message="", result={"ok": False})


# --------------------------------------------------------------------------- #
# tool：git / diff / revert（git 只读；revert 复用 rewind 热路径 + 二段确认）
# --------------------------------------------------------------------------- #

def _run_git(ctx: DispatchContext, args: list[str]) -> tuple[int, str]:
	ws = _workspace(ctx)
	if not ws:
		return 1, "未绑定工作区。"
	git = shutil.which("git")
	if not git:
		return 1, "本机没有 git 可执行文件。"
	try:
		proc = subprocess.run(  # noqa: S603
			[git, *args],
			cwd=ws,
			capture_output=True,
			text=True,
			timeout=10,
			encoding="utf-8",
			errors="replace",
		)
	except (OSError, subprocess.TimeoutExpired) as exc:
		return 1, f"git 执行失败：{exc}"
	out = (proc.stdout or "").strip()
	err = (proc.stderr or "").strip()
	if proc.returncode != 0:
		return proc.returncode, err or f"git 退出码 {proc.returncode}"
	return 0, out


def _cmd_git(ctx: DispatchContext, arg: str) -> CommandResult:
	op = (arg or "status").strip().lower().split(None, 1)[0]
	git_args = {
		"status": ["status", "--short", "--branch"],
		"log": ["log", "--oneline", "-10"],
		"branch": ["branch", "--list"],
	}.get(op)
	if git_args is None:
		return CommandResult(
			handled=True,
			kind="tool",
			message="用法：/git <status|log|branch>（只读操作）",
			result={"ok": False},
		)
	code, out = _run_git(ctx, git_args)
	if code != 0:
		return CommandResult(handled=True, kind="tool", message=out, result={"ok": False})
	return CommandResult(
		handled=True, kind="tool", message=out or "(空)", result={"ok": True, "op": op}
	)


def _cmd_diff(ctx: DispatchContext, arg: str) -> CommandResult:
	rev = (arg or "").strip()
	git_args = ["diff", "--stat"] + ([rev] if rev else [])
	code, out = _run_git(ctx, git_args)
	if code != 0:
		return CommandResult(handled=True, kind="tool", message=out, result={"ok": False})
	msg = out if out else ("无改动。" if not rev else f"{rev} 无差异。")
	return CommandResult(handled=True, kind="tool", message=msg, result={"ok": True})


def _cmd_revert(ctx: DispatchContext, arg: str) -> CommandResult:
	blocked = _reject_if_busy(ctx)
	if blocked is not None:
		return blocked
	parts = (arg or "").split()
	rewind_id = parts[0] if parts else ""
	confirmed = len(parts) > 1 and parts[1].lower() == "confirm"
	if not ctx.session_id:
		return CommandResult(
			handled=True, kind="tool", message="当前无会话，无法回溯。", result={"ok": False}
		)
	try:
		from rewind.hotpath import RewindHotpath
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="tool", message=f"rewind 不可用：{exc}", result={"ok": False}
		)
	ws = _workspace(ctx) or None
	try:
		hot = RewindHotpath(ctx.session_id, workspace_root=ws)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="tool", message=f"rewind 初始化失败：{exc}", result={"ok": False}
		)
	if not rewind_id:
		try:
			events = hot.list_events()
		except Exception as exc:  # noqa: BLE001
			return CommandResult(
				handled=True, kind="tool", message=f"读取回溯事件失败：{exc}", result={"ok": False}
			)
		if not events:
			return CommandResult(
				handled=True,
				kind="tool",
				message="本会话暂无回溯事件。",
				result={"ok": True, "events": []},
			)
		rows = [
			f"{e.get('rewind_id')}  {e.get('mode', '')}  {e.get('status', '')}"
			for e in events[-8:]
		]
		msg = "最近的回溯事件（用法：/revert <rewind_id> confirm）：\n" + "\n".join(rows)
		return CommandResult(
			handled=True, kind="tool", message=msg, result={"ok": True, "events": events[-8:]}
		)
	try:
		event = hot.get_event(rewind_id)
	except Exception:
		event = None
	if event is None:
		return CommandResult(
			handled=True, kind="tool", message=f"未找到回溯事件 {rewind_id}。", result={"ok": False}
		)
	if not confirmed:
		msg = (
			f"即将恢复到 {rewind_id}（mode={event.get('mode', '')}）。"
			f"确认请执行：/revert {rewind_id} confirm"
		)
		return CommandResult(
			handled=True, kind="tool", message=msg, result={"ok": False, "needs_confirm": True}
		)
	target = str(event.get("target_message_id") or "").strip()
	if not target:
		return CommandResult(
			handled=True,
			kind="tool",
			message="事件缺少 target_message_id，无法恢复。",
			result={"ok": False},
		)
	try:
		res = hot.rewind(
			mode="restore",
			target_message_id=target,
			checkpoint_id=(
				str(event.get("checkpoint_id")) if event.get("checkpoint_id") else None
			),
			confirmed=True,
		)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="tool", message=f"回溯失败：{exc}", result={"ok": False}
		)
	return CommandResult(
		handled=True,
		kind="tool",
		message=(
			f"已回溯 {res.rewind_id}（移除 {res.removed_rows} 行，保留 {res.retained_rows} 行，"
			f"status={res.status}）。"
		),
		result={"ok": True, **res.to_dict()},
	)


# --------------------------------------------------------------------------- #
# extension：skills / mcp / plugins
# --------------------------------------------------------------------------- #

def _cmd_skills(ctx: DispatchContext, arg: str) -> CommandResult:
	from extension.config import load_ext_config
	from extension.skill_loader import discover_skills

	ws = _workspace(ctx) or None
	cfg = load_ext_config(ws)
	if not cfg.enabled_extensions:
		return CommandResult(
			handled=True,
			kind="extension",
			message="扩展层默认关闭（.xeyo/settings.json 的 enabled_extensions）。",
			result={"ok": True, "enabled": False, "skills": []},
		)
	try:
		entries = discover_skills(ws, config=cfg)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="extension", message=f"技能发现失败：{exc}", result={"ok": False}
		)
	parts = (arg or "").split(None, 1)
	if parts and parts[0].lower() == "show" and len(parts) > 1:
		want = parts[1].strip().casefold()
		for e in entries:
			if e.name.casefold() == want:
				plugin_note = f" / plugin {e.plugin}" if e.plugin else ""
				msg = (
					f"{e.name}（{e.source}{plugin_note}）\n"
					f"路径 {e.path}\n"
					f"{e.description or '(无描述)'}"
				)
				return CommandResult(
					handled=True,
					kind="extension",
					message=msg,
					result={
						"ok": True,
						"skill": {"name": e.name, "path": str(e.path), "source": e.source},
					},
				)
		return CommandResult(
			handled=True, kind="extension", message=f"未找到技能 {parts[1]}。", result={"ok": False}
		)
	# F4（§2 决策 3）：user_invocable:false → 用户菜单不展示；show 按名详情不受限。
	visible = [e for e in entries if e.user_invocable]
	if not visible:
		msg = "未发现技能。"
	else:
		rows = [
			f"{e.name}  {e.source}" + (f"  {e.description[:48]}" if e.description else "")
			for e in visible
		]
		msg = f"技能 {len(visible)} 个：\n" + "\n".join(rows)
	return CommandResult(
		handled=True, kind="extension", message=msg, result={"ok": True, "count": len(entries)}
	)


def _cmd_mcp(ctx: DispatchContext, arg: str) -> CommandResult:
	from extension.config import load_ext_config, set_mcp_enabled
	from extension.loader import discover_plugins

	ws = _workspace(ctx) or None
	cfg = load_ext_config(ws)
	parts = (arg or "").split()
	op = parts[0].lower() if parts else "list"

	# F2.5 最小控制路径：/mcp enable|disable <id> —— push reconcile（活页块下轮注入）。
	if op in ("enable", "disable"):
		if len(parts) < 2 or not parts[1].strip():
			return CommandResult(
				handled=True,
				kind="extension",
				message=f"用法：/mcp {op} <server_id>",
				result={"ok": False},
			)
		sid = parts[1].strip()
		try:
			set_mcp_enabled(ws, sid, op == "enable")
		except Exception as exc:  # noqa: BLE001
			return CommandResult(
				handled=True, kind="extension", message=f"写入失败：{exc}", result={"ok": False}
			)
		verb = "启用" if op == "enable" else "停用"
		return CommandResult(
			handled=True,
			kind="extension",
			message=(
				f"MCP {sid} → {verb}（会话内调用侧即时生效"
				+ ("；" if op == "enable" else "，调用将被拒绝；")
				+ "原生工具目录下个会话重塑）。"
			),
			result={"ok": True, "id": sid, "enabled": op == "enable"},
		)

	# F2.5 最小控制路径：/mcp tool <server> <raw_name> <on|off> —— 单工具勾选。
	if op == "tool":
		if len(parts) < 4:
			return CommandResult(
				handled=True,
				kind="extension",
				message="用法：/mcp tool <server_id> <raw_tool_name> <on|off>",
				result={"ok": False},
			)
		from extension.mcp_manager import set_mcp_tool_enabled

		sid, raw, state = parts[1].strip(), parts[2].strip(), parts[3].lower()
		if state not in ("on", "off"):
			return CommandResult(
				handled=True,
				kind="extension",
				message="用法：/mcp tool <server_id> <raw_tool_name> <on|off>（state 只能 on/off）",
				result={"ok": False},
			)
		try:
			msg = set_mcp_tool_enabled(ws, sid, raw, state == "on")
		except Exception as exc:  # noqa: BLE001
			return CommandResult(
				handled=True, kind="extension", message=f"勾选失败：{exc}", result={"ok": False}
			)
		return CommandResult(handled=True, kind="extension", message=msg, result={"ok": True})

	if op not in ("list", "status"):
		return CommandResult(
			handled=True,
			kind="extension",
			message="用法：/mcp [list|status|enable|disable <id>|tool <id> <raw> <on|off>]",
			result={"ok": False},
		)
	if not cfg.enabled_extensions:
		return CommandResult(
			handled=True,
			kind="extension",
			message="扩展层默认关闭（.xeyo/settings.json 的 enabled_extensions）。",
			result={"ok": True, "enabled": False, "servers": []},
		)
	rows: list[str] = []
	servers: list[dict[str, Any]] = []
	for mcp_id in sorted((cfg.mcp_servers or {})):
		enabled = cfg.mcp_enabled(str(mcp_id))
		rows.append(f"{mcp_id}  {'on' if enabled else 'off'}")
		servers.append({"id": str(mcp_id), "enabled": enabled, "from": "config"})
	try:
		for lp in discover_plugins(ws, config=cfg):
			for spec in getattr(lp.plugin, "mcp_servers", None) or []:
				sid = str(getattr(spec, "id", "") or "")
				if not sid:
					continue
				enabled = lp.enabled and cfg.mcp_enabled(sid)
				rows.append(f"{sid}  {'on' if enabled else 'off'}  plugin:{lp.plugin.name}")
				servers.append(
					{"id": sid, "enabled": enabled, "from": f"plugin:{lp.plugin.name}"}
				)
	except Exception:
		pass
	msg = "\n".join(rows) if rows else "未声明 MCP 服务器。"
	return CommandResult(
		handled=True, kind="extension", message=msg, result={"ok": True, "servers": servers}
	)


def _cmd_plugins_manage(ws: str | None, op: str, parts: list[str], cfg) -> "CommandResult":
	"""插件安装/更新/卸载体（需扩展层主开关开；fail-closed 语义见上层）。"""
	from extension.mcp_scopes import plugin_denied
	from extension.plugin_fetcher import (
		install_from_spec,
		update_from_registry,
		remove_plugin,
	)
	from extension.plugin_store import default_lock_path, load_plugins

	def _err(msg: str) -> "CommandResult":
		return CommandResult(handled=True, kind="extension", message=msg, result={"ok": False})

	if op == "install":
		if len(parts) < 2 or not (parts[1] or "").strip():
			return _err("用法：/plugins install <source> [update]（source 形如 github:owner/repo 或本地路径）")
		source = parts[1].strip()
		allow_update = bool(parts[2:]) and parts[2].lower() in ("update", "force", "true", "1")
		res = install_from_spec(ws, source, allow_update=allow_update)
		name = str(res["name"])
		entry = res["entry"]
		# 企业 deny 一票否决：命中 → 回滚。
		if plugin_denied(name):
			try:
				remove_plugin(ws, name, owner_source=str(entry.get("source") or ""))
			except Exception:  # noqa: BLE001
				pass
			return _err(f"插件 {name} 被企业策略拒绝。")
		note = "（已存在，已覆盖）" if allow_update else ""
		return CommandResult(
			handled=True,
			kind="extension",
			message=f"插件 {name} 安装成功{note}：source={entry.get('source')}。",
			result={"ok": True, "name": name, "entry": entry},
		)

	if op == "update":
		if len(parts) < 2 or not (parts[1] or "").strip():
			return _err("用法：/plugins update <name>")
		name = parts[1].strip()
		entry = update_from_registry(ws, name)
		return CommandResult(
			handled=True,
			kind="extension",
			message=f"插件 {name} 更新完成（source={entry.get('source')}）。",
			result={"ok": True, "name": name, "entry": entry},
		)

	if op == "remove":
		if len(parts) < 2 or not (parts[1] or "").strip():
			return _err("用法：/plugins remove <name>")
		name = parts[1].strip()
		entry = load_plugins(default_lock_path(ws)).get(name) or {}
		existed = remove_plugin(ws, name, owner_source=str(entry.get("source") or ""))
		return CommandResult(
			handled=True,
			kind="extension",
			message=f"插件 {name} {'已卸载' if existed else '不在登记表中'}。",
			result={"ok": True, "name": name, "removed": existed},
		)

	return _err("内部错误：未知 manage 子命令")


def _cmd_plugins(ctx: DispatchContext, arg: str) -> CommandResult:
	from extension.config import load_ext_config, set_plugin_enabled
	from extension.loader import discover_plugins

	ws = _workspace(ctx) or None
	cfg = load_ext_config(ws)
	parts = (arg or "").split(None, 1)
	op = parts[0].lower() if parts else "list"
	if op in ("enable", "disable"):
		if len(parts) < 2 or not parts[1].strip():
			return CommandResult(
				handled=True,
				kind="extension",
				message=f"用法：/plugins {op} <name>",
				result={"ok": False},
			)
		name = parts[1].strip()
		try:
			set_plugin_enabled(ws, name, op == "enable")
		except Exception as exc:  # noqa: BLE001
			return CommandResult(
				handled=True, kind="extension", message=f"写入失败：{exc}", result={"ok": False}
			)
		return CommandResult(
			handled=True,
			kind="extension",
			message=f"插件 {name} → {'启用' if op == 'enable' else '禁用'}（重载会话后生效）。",
			result={"ok": True, "name": name, "enabled": op == "enable"},
		)

	# P0 控制路径扩展：install / update / remove —— 均要求扩展层主开关开（fail-closed）。
	if op in ("install", "update", "remove"):
		if not cfg.enabled_extensions:
			return CommandResult(
				handled=True,
				kind="extension",
				message="扩展层默认关闭（.xeyo/settings.json 的 enabled_extensions）。",
				result={"ok": False, "enabled": False},
			)
		try:
			return _cmd_plugins_manage(ws, op, parts, cfg)
		except Exception as exc:  # noqa: BLE001
			return CommandResult(
				handled=True,
				kind="extension",
				message=f"插件 {op} 失败：{exc}",
				result={"ok": False, "error": str(exc)},
			)

	if not cfg.enabled_extensions:
		return CommandResult(
			handled=True,
			kind="extension",
			message="扩展层默认关闭（.xeyo/settings.json 的 enabled_extensions）。",
			result={"ok": True, "enabled": False, "plugins": []},
		)
	try:
		loaded = discover_plugins(ws, config=cfg)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="extension", message=f"插件发现失败：{exc}", result={"ok": False}
		)
	if not loaded:
		msg = "未发现插件（<workspace>/.xeyo/plugins/ 或 ~/.xeyo/plugins/）。"
	else:
		rows = [
			f"{lp.plugin.name}  {'on' if lp.enabled else 'off'}  {getattr(lp, 'source', '')}"
			for lp in loaded
		]
		msg = f"插件 {len(loaded)} 个：\n" + "\n".join(rows)
	return CommandResult(
		handled=True, kind="extension", message=msg, result={"ok": True, "count": len(loaded)}
	)


# --------------------------------------------------------------------------- #
# 分发
# --------------------------------------------------------------------------- #

def _cmd_goal(ctx: DispatchContext, arg: str) -> CommandResult:
	"""创建/绑定当前会话目标（DSH 式显式新建；对齐 41 号 P1）。

	``/goal <目标>`` —— 用参数作为目标正文，新建并绑定到当前会话；若已绑定则
	替换（与 PATCH ``action=new`` 同语义）。仅当前会话可能未绑定目标时生效。
	"""
	objective = (arg or "").strip()
	if not objective:
		return CommandResult(
			handled=True,
			kind="info",
			message="请提供目标内容，例如：/goal 重构登录模块并跑通测试",
			result={"ok": False},
		)
	sid = (ctx.session_id or "").strip()
	if not sid:
		return CommandResult(
			handled=True, kind="info", message="当前无会话，无法绑定目标。",
			result={"ok": False},
		)
	ws = _workspace(ctx)
	if not ws:
		return CommandResult(
			handled=True, kind="info", message="未找到工作区，无法绑定目标。",
			result={"ok": False},
		)
	try:
		from engine.goal_state import GoalStore

		gstore = GoalStore(ws)
		goal = gstore.create(
			title=objective[:48], text=objective, owner=sid, origin="api"
		)
		gstore.bind(sid, goal.goal_id)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True, kind="unknown",
			message=f"/goal 创建失败：{exc}",
			result={"ok": False},
		)
	return CommandResult(
		handled=True,
		kind="info",
		message=f"已创建目标：{objective[:60]}",
		result={"ok": True, "goal_id": goal.goal_id, "title": objective[:48]},
	)


_HANDLERS: dict[str, Any] = {
	"status": _cmd_status,
	"cwd": _cmd_cwd,
	"usage": _cmd_usage,
	"context": _cmd_context,
	"ls": _cmd_ls,
	"stop": _cmd_stop,
	"allow": lambda c, a: _cmd_allow_deny(c, a, approved=True),
	"deny": lambda c, a: _cmd_allow_deny(c, a, approved=False),
	"compact": _cmd_compact,
	"transcript": _cmd_transcript,
	"export": _cmd_export,
	"rule": lambda c, a: _cmd_memory_instruction(c, a, name="rule"),
	"doctor": lambda c, a: _cmd_memory_instruction(c, a, name="doctor"),
	"proposals": lambda c, a: _cmd_memory_instruction(c, a, name="proposals"),
	"git": _cmd_git,
	"diff": _cmd_diff,
	"revert": _cmd_revert,
	"goal": _cmd_goal,
	"skills": _cmd_skills,
	"mcp": _cmd_mcp,
	"plugins": _cmd_plugins,
}


def dispatch(
	name: str, arg: str = "", *, ctx: DispatchContext | None = None
) -> CommandResult:
	"""执行一个 server 命令。未知 / client 命令返回 handled=False。"""
	cmd = get_command(name)
	if cmd is None:
		return CommandResult(
			handled=False, kind="unknown", message=f"未知命令 /{name}，试试 /help。"
		)
	if cmd.handler != "server":
		return CommandResult(
			handled=False,
			kind="unknown",
			message=f"/{cmd.name} 由界面本地处理，不应发送到服务端。",
		)
	ctx = ctx or DispatchContext()
	handler = _HANDLERS.get(cmd.name)
	if handler is None:
		return CommandResult(
			handled=True,
			kind="unknown",
			message=f"/{cmd.name} 暂未注册实现。",
			result={"ok": False},
		)
	try:
		return handler(ctx, arg)
	except Exception as exc:  # noqa: BLE001
		return CommandResult(
			handled=True,
			kind="unknown",
			message=f"/{cmd.name} 执行失败：{exc}",
			result={"ok": False},
		)


def dispatch_command(
	cmd: Command, arg: str = "", *, ctx: DispatchContext | None = None
) -> CommandResult:
	return dispatch(cmd.name, arg, ctx=ctx)


def build_help(ctx: DispatchContext | None = None) -> CommandResult:
	ctx = ctx or DispatchContext()
	return CommandResult(
		handled=True,
		kind="help",
		message=help_text(surfaces=tuple(ctx.surfaces) if ctx.surfaces else None),
	)
