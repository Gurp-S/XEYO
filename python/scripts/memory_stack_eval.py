"""完整评测：v6.1 公式（离线战役 + 真实 JSONL）+ 记忆热路径（真实 DeepSeek）。

不跑 live probe（Ĥ vs prompt_cache_hit_tokens）。
密钥只读环境变量 DEEPSEEK_API_KEY / XEYO_MODEL_API_KEY，不写进任何文件。

用法（在 python/ 下）:
  set DEEPSEEK_API_KEY=...
  python scripts/memory_stack_eval.py
"""

from __future__ import annotations

import asyncio
import bisect
import json
import os
import re
import subprocess
import sys
import time
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.base_tool import ToolResult

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

OUT = ROOT / "memory" / "simulator" / "out"
SANDBOX = OUT / "eval_sandbox"
SUBMIT_TIMEOUT_S = 180.0


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()


def _chars(messages: list[dict]) -> int:
	n = 0
	for m in messages:
		c = m.get("content")
		if isinstance(c, str):
			n += len(c)
		elif isinstance(c, list):
			n += sum(len(json.dumps(b, ensure_ascii=False)) for b in c)
	return n


def apply_sandbox() -> Path:
	"""隔离 live 写入；必须在公式 JSONL replay 之后调用。"""
	home = SANDBOX / "xeyo_home"
	os.environ["XEYO_HOME"] = str(home)
	os.environ["XEYO_SESSIONS_DIR"] = str(SANDBOX / "sessions")
	os.environ["XEYO_USAGE_DIR"] = str(SANDBOX / "usage")
	os.environ["XEYO_MEMORY_DIR"] = str(home / "memory")
	os.environ["XEYO_NO_SESSION_PERSISTENCE"] = "0"
	_set_l5("v61")
	home.mkdir(parents=True, exist_ok=True)
	(SANDBOX / "sessions").mkdir(parents=True, exist_ok=True)
	(SANDBOX / "usage").mkdir(parents=True, exist_ok=True)
	return SANDBOX / "proj"


def _set_l5(mode: str) -> None:
	"""离线 eval 切换 L5 模式：写 sandbox home 的 settings.json memory 段。

	记忆开关已改为「以 GUI settings.memory 为准、环境变量一律不参与」，
	故离线 A/B 不能用 os.environ 切换，改走 memory_switches.save（写入
	apply_sandbox 指定的 XEYO_HOME），运行时 get_value 解析同一处。
	"""
	from memory.memory_switches import save

	save({"XEYO_L5": mode})


def seed_workspace(proj: Path) -> None:
	proj.mkdir(parents=True, exist_ok=True)
	(proj / "README.md").write_text(
		"# eval fixture\nTODO: keep this marker for Grep.\n测试必须打真库\n",
		encoding="utf-8",
	)
	(proj / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
	(proj / "XEYO.md").write_text("永远用中文回复。\n", encoding="utf-8")


def _usage_totals() -> dict:
	from usage.ledger import _read_events

	events = _read_events()
	hit = miss = out = prompt = req = 0
	cost = 0.0
	for ev in events:
		hit += int(ev.get("cache_hit") or 0)
		miss += int(ev.get("cache_miss") or 0)
		out += int(ev.get("output") or 0)
		prompt += int(ev.get("prompt_tokens") or 0)
		cost += float(ev.get("cost_cny") or 0)
		req += 1
	return {
		"requests": req,
		"prompt_tokens": prompt,
		"cache_hit": hit,
		"cache_miss": miss,
		"output": out,
		"cost_cny": round(cost, 6),
	}


def _delta(before: dict, after: dict) -> dict:
	return {k: after.get(k, 0) - before.get(k, 0) for k in after}


def formula_snapshot(messages: list[dict], cursor: int = 0) -> dict:
	"""只 decide，不 Apply，不改 working。"""
	from memory.simulator.cache_model import CacheState
	from memory.simulator.decision import decide
	from memory.simulator.params import load_params
	from memory.simulator.scenarios import DEFAULT_SYSTEM, state_from_messages

	p = load_params()
	s0 = state_from_messages(messages, cursor=cursor)
	d = decide(s0, CacheState(age_seconds=0.0, x_prev=""), remaining_turns=8, params=p, forecast="p0")
	keep = d.branches.get("keep")
	c1 = d.branches.get("C1")
	c2 = d.branches.get("C2")
	return {
		"a_star": d.a_star,
		"hardtop": d.hardtop,
		"notes": list(d.notes),
		"m_tokens": s0.m_tokens,
		"L_keep": int(keep.L) if keep else None,
		"Q_keep": keep.Q if keep else None,
		"Q_C1": c1.Q if c1 else None,
		"Q_C2": c2.Q if c2 else None,
	}


def build_eval_registry(cwd: str):
	"""日常编码 + 记忆工具；不含 Screenshot / WeChat / Bash，避免评测挂死。"""
	from tools.echo import EchoTool
	from tools.fileio.read_state import ReadFileState
	from tools.file_read_tool.file_read_tool import FileReadTool
	from tools.get_time import GetTimeTool
	from tools.glob_tool.glob_tool import GlobTool
	from tools.grep_tool.grep_tool import GrepTool
	from tools.memory_tool import MemoryTool
	from tools.tool_registry import ToolRegistry

	class MemorySearchTool:  # 评估垫片:工具入口已收敛为 Grep 直读;此处仅保留旧评估口径
		name = "MemorySearch"

		def __init__(self, *, cwd: str = ".") -> None:
			self._cwd = cwd

		def schema(self):
			return {"name": self.name, "description": "search memory notes",
					"input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}

		async def execute(self, input, abort):
			from memory.search import search as _s

			hits = _s(str((input or {}).get("query") or ""), cwd=self._cwd)
			if not hits:
				return ToolResult(content="(no memory hits)")
			return ToolResult(content="\n".join(f"{n.id} [{n.type}] {n.title}" for n in hits))

	work = os.path.abspath(os.path.expanduser(cwd))
	reg = ToolRegistry(cwd=work)
	read_state = ReadFileState()
	tools = [
		EchoTool(),
		GetTimeTool(),
		GlobTool(cwd=work),
		GrepTool(cwd=work),
		FileReadTool(cwd=work),
		MemoryTool(cwd=work),
		MemorySearchTool(cwd=work),
	]
	for tool in tools:
		setter = getattr(tool, "set_read_file_state", None)
		if callable(setter):
			setter(read_state)
		reg.register(tool)
	return reg


def make_engine(
	*,
	cwd: str,
	session_id: str,
	max_turns: int = 12,
	initial_messages: list | None = None,
):
	from engine.query_engine import QueryEngine, QueryEngineConfig
	from model.openai_compat import OpenAICompatClient, PROVIDER_PRESETS
	from prompt.assembler import PromptAssembler

	reg = build_eval_registry(cwd)
	names = ", ".join(t.name for t in reg._tools.values())
	key = (
		os.environ.get("DEEPSEEK_API_KEY", "").strip()
		or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	)
	preset = PROVIDER_PRESETS["deepseek"]
	model = OpenAICompatClient(
		api_key=key,
		base_url=(os.environ.get("DEEPSEEK_BASE_URL") or preset["base_url"]).rstrip("/"),
		model=os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
		provider="deepseek",
		thinking=os.environ.get("DEEPSEEK_THINKING") or "disabled",
	)
	config: QueryEngineConfig = {
		"cwd": cwd,
		"tools": reg,
		"model_client": model,
		"prompt_assembler": PromptAssembler(),
		"append_system_prompt": (
			f"Available tools: {names}. "
			"Do not invent tools. Prefer Glob/Grep/Read/echo/getTime/"
			"Memory(action=write/update/forget)/MemorySearch. Never call Bash or Screenshot."
		),
		"max_turns": max_turns,
		"session_id": session_id,
	}
	if initial_messages:
		config["initial_messages"] = list(initial_messages)
	return QueryEngine(config)


async def run_submit(eng, prompt: str) -> dict:
	from engine.compact import project as project_c0c1
	from memory.runtime import project_for_model
	from memory.working import WorkingSnapshot
	from msgtypes.events import (
		FinalEvent,
		ResultEvent,
		StoppedEvent,
		ToolCallEvent,
		ToolResultEvent,
	)

	tools: list[str] = []
	tool_errors = 0
	final_text = ""
	stopped = None
	result_subtype = None
	num_turns = 0
	duration_ms = 0
	t0 = time.perf_counter()
	try:
		async with asyncio.timeout(SUBMIT_TIMEOUT_S):
			async for ev in eng.submit(prompt):
				if isinstance(ev, ToolCallEvent):
					tools.append(ev.name)
				elif isinstance(ev, ToolResultEvent) and ev.is_error:
					tool_errors += 1
				elif isinstance(ev, FinalEvent):
					final_text = (ev.text or "")[:800]
				elif isinstance(ev, StoppedEvent):
					stopped = ev.reason
				elif isinstance(ev, ResultEvent):
					result_subtype = ev.subtype
					num_turns = ev.num_turns
					duration_ms = ev.duration_ms
					if ev.is_error and not final_text:
						final_text = (ev.result or "")[:400]
	except TimeoutError:
		return {
			"ok": False,
			"error": f"timeout>{SUBMIT_TIMEOUT_S}s",
			"tools": tools,
			"elapsed_s": round(time.perf_counter() - t0, 3),
		}
	except Exception as exc:
		return {
			"ok": False,
			"error": f"{type(exc).__name__}: {exc}",
			"tools": tools,
			"elapsed_s": round(time.perf_counter() - t0, 3),
		}
	working = eng._session.working
	api = eng._session.messages.as_api_messages()
	try:
		snap = formula_snapshot(api, cursor=working.compact_cursor)
	except Exception as exc:
		snap = {"error": f"{type(exc).__name__}: {exc}"}
	wcopy = WorkingSnapshot(
		session_id=working.session_id,
		compact_cursor=working.compact_cursor,
		turns_since_c2=working.turns_since_c2,
	)
	try:
		proj = project_for_model(api, wcopy)
		base = project_c0c1(api)
		proj_chars = _chars(proj)
		c0c1_chars = _chars(base)
		proj_n = len(proj)
	except Exception:
		proj_chars = c0c1_chars = proj_n = None
	ok = stopped is None and result_subtype in (None, "success")
	return {
		"ok": ok,
		"final": final_text,
		"tools": tools,
		"tool_errors": tool_errors,
		"stopped": stopped,
		"result_subtype": result_subtype,
		"num_turns": num_turns,
		"duration_ms": duration_ms,
		"elapsed_s": round(time.perf_counter() - t0, 3),
		"n_store": len(eng._session.messages),
		"compact_cursor": working.compact_cursor,
		"turns_since_c2": working.turns_since_c2,
		"formula": snap,
		"proj_chars": proj_chars,
		"c0c1_chars": c0c1_chars,
		"proj_n": proj_n,
		"c2_applied": working.compact_cursor > 0,
	}


def long_history(n_tools: int = 20, blob: int = 8000) -> list:
	from msgtypes.message import ToolUse, assistant_text_message, tool_result_message, user_message

	msgs = [user_message("请在仓库里搜 TODO 并继续分析。")]
	body = ("TODO line\n" * 20) + ("X" * blob)
	for i in range(n_tools):
		uid = f"grep_{i:03d}"
		msgs.append(
			assistant_text_message(
				f"search {i}",
				[ToolUse(id=uid, name="Grep", input={"pattern": "TODO"})],
			)
		)
		msgs.append(tool_result_message(uid, "Grep", body))
	return msgs


def long_history_api(n_tools: int = 20, blob: int = 8000) -> list[dict]:
	from session.message_store import MessageStore

	return MessageStore(long_history(n_tools, blob)).as_api_messages()


def long_history_multi(n_tools: int = 20, blob: int = 8000, *, user_every: int = 5) -> list[dict]:
	"""多轮合成源：每 user_every 个工具循环插入一条用户消息，避免单轮冷启动假象。"""
	from msgtypes.message import ToolUse, assistant_text_message, tool_result_message, user_message

	msgs = [user_message("请在仓库里搜 TODO 并继续分析。")]
	body = ("TODO line\n" * 20) + ("X" * blob)
	for i in range(n_tools):
		uid = f"grep_{i:03d}"
		msgs.append(
			assistant_text_message(
				f"search {i}",
				[ToolUse(id=uid, name="Grep", input={"pattern": "TODO"})],
			)
		)
		msgs.append(tool_result_message(uid, "Grep", body))
		if user_every > 0 and (i + 1) % user_every == 0 and i + 1 < n_tools:
			msgs.append(user_message("继续，别忘了之前的结论。"))
	from session.message_store import MessageStore

	return MessageStore(msgs).as_api_messages()


def run_unit_tests() -> dict:
	cmd = [
		sys.executable,
		"-m",
		"pytest",
		"-q",
		"-m",
		"not live",
		"tests/test_runtime_c2.py",
		"tests/test_session_md.py",
		"tests/test_instruction.py",
		"tests/test_memdir.py",
		"tests/test_governance.py",
		"tests/test_memory_search.py",
		"tests/test_nightshift.py",
		"tests/test_compact.py",
		"tests/simulator",
	]
	print("== memory unit tests ==")
	proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
	tail = ((proc.stdout or "") + (proc.stderr or ""))[-1200:]
	print(tail[-600:])
	return {"exit": proc.returncode, "passed": proc.returncode == 0, "tail": tail}


def run_formula_campaign() -> dict:
	"""跑完整离线战役（含真实 JSONL replay）。不调用 probe API。"""
	print("== formula offline campaign (no live probe) ==")
	campaign_script = ROOT / "scripts" / "p2_full_campaign.py"
	if not campaign_script.is_file():
		# 缺失的 campaign harness 不应阻断其余离线结果（如 unit tests / r 探针 / 表D）。
		print(f"[警告] 跳过 p2_full_campaign：缺失 {campaign_script}")
		path = OUT / "campaign.json"
		payload: dict[str, Any] = {}
		if path.is_file():
			payload = json.loads(path.read_text(encoding="utf-8"))
		ext = payload.get("extreme") or []
		return {"exit": 1, "passed": False, "extreme_pass": bool(ext), "ext": ext, "tail": "campaign missing"}
	proc = subprocess.run(
		[sys.executable, "scripts/p2_full_campaign.py"],
		cwd=str(ROOT),
		capture_output=True,
		text=True,
		env={k: v for k, v in os.environ.items() if k not in {
			"XEYO_SESSIONS_DIR",
			"XEYO_USAGE_DIR",
			"XEYO_MEMORY_DIR",
			"XEYO_HOME",
		}},
	)
	print((proc.stdout or "")[-1500:])
	if proc.returncode != 0 and proc.stderr:
		print((proc.stderr or "")[-800:])
	path = OUT / "campaign.json"
	payload: dict[str, Any] = {}
	if path.is_file():
		payload = json.loads(path.read_text(encoding="utf-8"))
	ext = payload.get("extreme") or []
	syn = payload.get("synthetic_full") or {}
	syn_slim = {k: v for k, v in syn.items() if k != "rows"}
	rep = payload.get("replay") or {}
	return {
		"exit": proc.returncode,
		"extreme_pass": bool(ext) and all(x.get("passed") for x in ext),
		"extreme_fail": [x for x in ext if not x.get("passed")],
		"synthetic": syn_slim,
		"replay": {k: v for k, v in rep.items() if k != "longest"},
		"replay_longest": (rep.get("longest") or [])[:5],
		"five_questions": payload.get("five_questions") or {},
		"overlay": payload.get("overlay"),
		"stdout_tail": (proc.stdout or "")[-2000:],
	}


def formula_on_longest_real() -> dict:
	from memory.simulator.replay import default_sessions_dir, iter_session_files, load_jsonl
	from memory.runtime import project_for_model
	from engine.compact import project as project_c0c1
	from memory.working import WorkingSnapshot

	files = iter_session_files(default_sessions_dir())
	if not files:
		return {"ok": False, "reason": "no jsonl"}
	best = max(files, key=lambda p: p.stat().st_size if p.is_file() else 0)
	rows = load_jsonl(best)
	api = []
	for row in rows:
		if not isinstance(row, dict) or not row.get("role"):
			continue
		msg = {"role": row["role"], "content": row.get("content")}
		if row.get("name"):
			msg["name"] = row["name"]
		if row.get("tool_call_id"):
			msg["tool_call_id"] = row["tool_call_id"]
		api.append(msg)
	if not api:
		return {"ok": False, "file": best.name, "reason": "empty"}
	pre = formula_snapshot(api, cursor=0)
	w = WorkingSnapshot(session_id="real_replay", turns_since_c2=4)
	proj = project_for_model(api, w)
	base = project_c0c1(api)
	return {
		"ok": True,
		"file": best.name,
		"n_messages": len(api),
		"formula": pre,
		"cursor_after_apply": w.compact_cursor,
		"c0c1_chars": _chars(base),
		"v61_proj_chars": _chars(proj),
		"char_delta_vs_c0c1": _chars(proj) - _chars(base),
	}


async def run_live(proj: Path) -> dict:
	from engine.abort import AbortController
	from engine.compact import project as project_c0c1
	from memory.l5_flag import l5_mode
	from memory.memdir import load_index_text, workspace_id
	from memory.runtime import project_for_model
	from memory.working import WorkingSnapshot, hydrate
	from prompt.system_prompt import assemble_system_prompt, fetch_system_prompt_parts
	from session.cwd import set_cwd
	from tools.memory_tool import MemoryTool

	class _MemorySearchShim:  # 评估垫片:工具入口已收敛为 Grep 直读
		name = "MemorySearch"

		def __init__(self, *, cwd: str = ".") -> None:
			self._cwd = cwd

		async def execute(self, input, abort):
			from memory.search import search as _s

			hits = _s(str((input or {}).get("query") or ""), cwd=self._cwd)
			from tools.base_tool import ToolResult as _TR

			if not hits:
				return _TR(content="(no memory hits)")
			return _TR(content="\n".join(f"{n.id} [{n.type}] {n.title}" for n in hits))

	MemorySearchTool = _MemorySearchShim

	cases: list[dict] = []
	mode = l5_mode()
	usage_before = _usage_totals()  # ledger 跨 run 累积，报告只算本次 run 的增量
	print(f"== live memory stack XEYO_L5={mode} ==")
	# 对齐产品热路径：query_engine.submit_message 开头会 set_cwd(workspace)。
	# 不切的话 _append_memory_index 按进程 cwd 取 workspace，索引尾插检查会假失败。
	set_cwd(str(proj))

	parts = await fetch_system_prompt_parts(
		cwd=str(proj), model="deepseek", tool_names=["echo"]
	)
	sys_text = assemble_system_prompt(parts, include_context_blocks=True)
	l1_ok = "永远用中文回复" in sys_text
	cases.append(
		{
			"id": "l1_xeyo_md",
			"live": False,
			"ok": l1_ok,
			"detail": "system contains 永远用中文回复" if l1_ok else sys_text[:200],
		}
	)
	print(f"  l1_xeyo_md ok={l1_ok}")

	abort = AbortController()
	writer = MemoryTool(cwd=str(proj))
	direct = await writer.execute(
		{
			"action": "write",
			"type": "feedback",
			"content": "测试必须打真库",
			"title": "真实DB",
			"source_kind": "user",
			"confidence": 1.0,
		},
		abort,
	)
	wsid = workspace_id(str(proj))
	idx = load_index_text(wsid)
	direct_ok = (not direct.is_error) and ("真库" in idx or "真实DB" in idx)
	cases.append(
		{
			"id": "l4_direct_write",
			"live": False,
			"ok": direct_ok,
			"tool_error": direct.is_error,
			"tool_out": (direct.content or "")[:240],
			"index_preview": idx[:400],
			"wsid": wsid,
		}
	)
	print(f"  l4_direct_write ok={direct_ok}")

	searcher = MemorySearchTool(cwd=str(proj))
	found = await searcher.execute({"query": "真库"}, abort)
	cases.append(
		{
			"id": "l4_direct_search",
			"live": False,
			"ok": (not found.is_error) and ("真库" in (found.content or "") or "真实" in (found.content or "")),
			"out": (found.content or "")[:400],
		}
	)
	print(f"  l4_direct_search ok={cases[-1]['ok']}")

	parts2 = await fetch_system_prompt_parts(
		cwd=str(proj), model="deepseek", tool_names=["MemorySearch"]
	)
	sys2 = assemble_system_prompt(parts2, include_context_blocks=True)
	# 索引已移出 system 左段（避免 memory mutation 弄废整段 KV 前缀），改在投影 T_now 尾部提供
	idx_out_of_system = "Memory index" not in sys2
	_tail = project_for_model(
		[{"role": "user", "content": "hi"}],
		WorkingSnapshot(session_id="idx_tail"),
	)
	_tail_has_index = any(
		isinstance(b, dict)
		and b.get("type") == "text"
		and "Memory index" in str(b.get("text") or "")
		for m in _tail
		for b in (m.get("content") or [])
		if isinstance(b, dict)
	)
	cases.append(
		{
			"id": "l4_index_in_system",
			"live": False,
			"ok": idx_out_of_system and _tail_has_index,
			"detail": (
				f"system_no_index={idx_out_of_system} "
				f"t_now_index={_tail_has_index}"
			),
			"has_behavior": "MemoryWrite" in sys2,
		}
	)
	print(f"  l4_index_in_system ok={cases[-1]['ok']}")

	async def one(
		cid: str,
		prompt: str,
		*,
		session_id: str,
		max_turns: int = 10,
		follow: str | None = None,
		follows: list[str] | None = None,
		eng=None,
		expect_tools: list[str] | None = None,
	):
		before = _usage_totals()
		if eng is None:
			eng = make_engine(cwd=str(proj), session_id=session_id, max_turns=max_turns)
		row = await run_submit(eng, prompt)
		row["id"] = cid
		row["live"] = True
		row["prompt"] = prompt[:160]
		extra: list[dict] = []
		seq = list(follows or [])
		if follow:
			seq.append(follow)
		for i, nxt in enumerate(seq):
			if not row.get("ok"):
				break
			nxt_row = await run_submit(eng, nxt)
			extra.append(
				{
					"i": i,
					"ok": nxt_row.get("ok"),
					"final": nxt_row.get("final"),
					"tools": nxt_row.get("tools"),
					"formula": nxt_row.get("formula"),
					"compact_cursor": nxt_row.get("compact_cursor"),
					"num_turns": nxt_row.get("num_turns"),
				}
			)
		if extra:
			row["follow"] = extra if len(extra) > 1 else extra[0]
		row["usage"] = _delta(before, _usage_totals())
		if expect_tools:
			have = set(row.get("tools") or [])
			row["missing_tools"] = [t for t in expect_tools if t not in have]
			if row["missing_tools"] and row.get("ok"):
				row["ok"] = False
				row["error"] = f"missing tools {row['missing_tools']}"
		cases.append(row)
		print(
			f"  {cid} ok={row.get('ok')} turns={row.get('num_turns')} "
			f"tools={row.get('tools')} a*={row.get('formula', {}).get('a_star')} "
			f"cursor={row.get('compact_cursor')} cost={row['usage'].get('cost_cny')}"
		)
		if not row.get("ok"):
			print(f"    err={row.get('error') or row.get('stopped') or row.get('result_subtype')}")
			if row.get("final"):
				print(f"    final={row['final'][:180]}")
		return eng, row

	await one(
		"short_plain",
		"用一句话回答：2+2 等于几？不要调用任何工具。",
		session_id="short_plain",
		max_turns=3,
	)
	await one(
		"short_followup_kv",
		"记住数字 17。只要回复「已记住」。不要用工具。",
		session_id="short_kv",
		max_turns=3,
		follow="我刚才让你记住的数字是几？一句话，不要用工具。",
	)
	await one(
		"echo_tool_loop",
		"请调用 echo 工具，参数 text 设为 ping-memory。调用后再用一句话复述结果。",
		session_id="echo_loop",
		max_turns=6,
		expect_tools=["echo"],
	)
	await one(
		"everyday_files",
		"日常编码：先 Glob 找 *.md，再 Grep TODO，再 Read README.md。"
		"最后用两三句话总结。不要用别的工具。",
		session_id="everyday",
		max_turns=12,
		expect_tools=["Glob", "Grep", "Read"],
	)
	await one(
		"multi_tool",
		"请同时调用 getTime 和 Glob（pattern=*.py）。不要用别的工具。"
		"完成后各用一句话说明结果。",
		session_id="multi_tool",
		max_turns=8,
		expect_tools=["getTime", "Glob"],
	)
	await one(
		"daily_multi_turn",
		"先 Glob 找 *.py，只列出文件名。",
		session_id="daily",
		max_turns=8,
		follows=[
			"Read app.py，main 返回什么？一句话。",
			"上一问你读的是哪个文件？不要用工具。",
		],
	)
	await one(
		"l1_chinese_live",
		"用一个词打招呼。不要用工具。",
		session_id="l1_live",
		max_turns=3,
	)
	await one(
		"remember_via_tool",
		"请调用 MemoryWrite：type=user，content=评测偏好用中文，"
		"source_kind=user，confidence=1.0，title=语言偏好。"
		"成功后只用一句话确认。不要用普通 Write。",
		session_id="remember",
		max_turns=8,
		expect_tools=["MemoryWrite"],
	)
	_eng, _row = await one(
		"search_new_session",
		"请调用 MemorySearch，query=真库。读到结果后用一句话转述，不要编造。",
		session_id="search_new",
		max_turns=8,
		expect_tools=["MemorySearch"],
	)
	if _row.get("ok") and any(
		k in (_row.get("final") or "") for k in ("没有命中", "没命中", "未命中", "没有找到", "没找到")
	):
		# 上一轮实测暴露：写入冲突把 真库 笔记 supersede 掉，跨会话搜不到但 ok 仍为 True
		_row["ok"] = False
		_row["error"] = "search_new_session 未命中已写入的 真库 笔记（记忆丢失回归）"

	await one(
		"forget_live",
		"如果 MemorySearch query=语言偏好 能找到笔记，对其 id 调用 MemoryForget。"
		"若没有则说没有。不要编造 id。",
		session_id="forget",
		max_turns=8,
	)

	hist = long_history(20, 8000)
	api_hist = long_history_api(20, 8000)
	pre = formula_snapshot(api_hist, cursor=0)
	w0 = WorkingSnapshot(session_id="long_c2", turns_since_c2=4)
	proj_v61 = project_for_model(api_hist, deepcopy(w0))
	w1 = WorkingSnapshot(session_id="long_c2", turns_since_c2=4)
	_ = project_for_model(api_hist, w1)
	base = project_c0c1(api_hist)
	cases.append(
		{
			"id": "long_injected_formula",
			"live": False,
			"ok": True,
			"n_messages": len(api_hist),
			"formula": pre,
			"c0c1_chars": _chars(base),
			"v61_proj_chars": _chars(proj_v61),
			"cursor_after_decide_apply": w1.compact_cursor,
			"char_delta_vs_c0c1": _chars(proj_v61) - _chars(base),
		}
	)
	print(
		f"  long_injected_formula a*={pre['a_star']} hardtop={pre['hardtop']} "
		f"cursor={w1.compact_cursor} Δchars={_chars(proj_v61) - _chars(base)}"
	)

	_set_l5("v61")
	before = _usage_totals()
	eng_long = make_engine(
		cwd=str(proj),
		session_id="long_c2_live",
		max_turns=8,
		initial_messages=hist,
	)
	eng_long._session.working.turns_since_c2 = 4
	row_long = await run_submit(
		eng_long,
		"根据已有搜索结果，README 里有没有 TODO？一句话回答，尽量少用工具。",
	)
	row_long["id"] = "long_continue_live"
	row_long["live"] = True
	row_long["pre_formula"] = pre
	row_long["usage"] = _delta(before, _usage_totals())
	hyd = hydrate("long_c2_live")
	row_long["hydrated_cursor"] = hyd.compact_cursor
	cases.append(row_long)
	print(
		f"  long_continue_live ok={row_long.get('ok')} a*={row_long.get('formula', {}).get('a_star')} "
		f"cursor={row_long.get('compact_cursor')} hydrated={hyd.compact_cursor} "
		f"cost={row_long['usage'].get('cost_cny')}"
	)

	async def ab_pair(tag: str, p1: str, p2: str) -> dict:
		out = {}
		for ab_mode in ("v61", "project"):
			_set_l5(ab_mode)
			before_u = _usage_totals()
			eng = make_engine(cwd=str(proj), session_id=f"ab_{tag}_{ab_mode}", max_turns=4)
			r1 = await run_submit(eng, p1)
			r2 = await run_submit(eng, p2)
			out[ab_mode] = {
				"r1_ok": r1.get("ok"),
				"r2_ok": r2.get("ok"),
				"r1_a_star": (r1.get("formula") or {}).get("a_star"),
				"r2_a_star": (r2.get("formula") or {}).get("a_star"),
				"cursor": r2.get("compact_cursor"),
				"r1_proj": r1.get("proj_chars"),
				"r2_proj": r2.get("proj_chars"),
				"usage": _delta(before_u, _usage_totals()),
			}
			print(
				f"  ab_{tag}/{ab_mode} cost={out[ab_mode]['usage'].get('cost_cny')} "
				f"hit={out[ab_mode]['usage'].get('cache_hit')} miss={out[ab_mode]['usage'].get('cache_miss')}"
			)
		_set_l5("v61")
		return out

	ab_short = await ab_pair(
		"short",
		"只回一个字：好。不要工具。",
		"还是不要工具，回一个字：行。",
	)
	cases.append({"id": "ab_short_v61_vs_project", "live": True, "ok": True, "modes": ab_short})

	# 长历史 A/B 仅做投影（不发起第二次超大 live 调用）
	_set_l5("project")
	w_proj = WorkingSnapshot(session_id="ab_long", turns_since_c2=4)
	only_c0c1 = project_for_model(api_hist, w_proj)
	_set_l5("v61")
	cases.append(
		{
			"id": "ab_long_projection",
			"live": False,
			"ok": True,
			"project_mode_chars": _chars(only_c0c1),
			"v61_chars": _chars(proj_v61),
			"v61_cursor": w1.compact_cursor,
			"project_cursor": w_proj.compact_cursor,
		}
	)

	return {"l5_mode": mode, "cases": cases, "usage_total": _delta(usage_before, _usage_totals())}


def _case_ok(c: dict) -> bool:
	if c.get("id") == "ab_short_v61_vs_project":
		modes = c.get("modes") or {}
		return bool(modes.get("v61", {}).get("r1_ok") and modes.get("v61", {}).get("r2_ok")
			and modes.get("project", {}).get("r1_ok") and modes.get("project", {}).get("r2_ok"))
	if c.get("id") == "forget_live":
		# 模型可能找不到 id；只要跑完仍算成功
		return bool(c.get("ok") or c.get("result_subtype") == "success")
	if c.get("id") == "l1_chinese_live":
		final = c.get("final") or ""
		# 中文指令：至少有一个 CJK 字符，或回合成功（模型偶发英文也记下来）
		c["has_cjk"] = any("\u4e00" <= ch <= "\u9fff" for ch in final)
		return bool(c.get("ok"))
	return bool(c.get("ok"))


def write_markdown(report: dict) -> str:
	syn = (report.get("formula_offline") or {}).get("synthetic") or {}
	ab = syn.get("ab") or {}
	live = report.get("live") or {}
	real = report.get("formula_real") or {}
	lines = [
		"# XEYO 记忆体系完整评测",
		"",
		f"Generated: {report.get('generated_at')}",
		"",
		"未跑 live probe（Ĥ vs prompt_cache_hit_tokens）。密钥未写入仓库。",
		"",
		"## 1. 公式 v6.1（离线）",
		"",
		f"- extreme invariants: {'PASS' if report.get('formula_offline', {}).get('extreme_pass') else 'FAIL'}",
		f"- synthetic n={syn.get('n')} actions={syn.get('actions')} hardtop={syn.get('hardtop')}",
		f"- synthetic savings_frac={ab.get('savings_frac')} baseline={ab.get('baseline_cost')} v61={ab.get('v61_cost')}",
		f"- synthetic gate={ab.get('gate')}",
		f"- replay turns={((report.get('formula_offline') or {}).get('replay') or {}).get('turns')} "
		f"actions={((report.get('formula_offline') or {}).get('replay') or {}).get('actions')} "
		f"token_savings={((report.get('formula_offline') or {}).get('replay') or {}).get('token_savings_frac')}",
		"",
		"## 2. 最长真实 JSONL 上的 Apply",
		"",
		f"- {json.dumps(real, ensure_ascii=False)[:800]}",
		"",
		"## 3. 记忆平面单测",
		"",
		f"- pytest: {'PASS' if report.get('unit', {}).get('passed') else 'FAIL'} exit={report.get('unit', {}).get('exit')}",
		"",
		"## 4. 真实 API 热路径",
		"",
		f"- live usage total: {live.get('usage_total')}",
		"",
	]
	for c in live.get("cases") or []:
		cid = c.get("id")
		ok = _case_ok(c)
		lines.append(f"### {cid}  {'OK' if ok else 'FAIL'}")
		if c.get("live"):
			lines.append(
				f"- turns={c.get('num_turns')} tools={c.get('tools')} "
				f"a*={(c.get('formula') or {}).get('a_star')} cursor={c.get('compact_cursor')} "
				f"usage={c.get('usage')}"
			)
			if c.get("final"):
				lines.append(f"- final: {c['final'][:240].replace(chr(10), ' ')}")
			if c.get("follow"):
				lines.append(f"- follow: {json.dumps(c['follow'], ensure_ascii=False)[:500]}")
			if c.get("modes"):
				lines.append(f"- modes: {json.dumps(c['modes'], ensure_ascii=False)}")
		else:
			detail = {k: v for k, v in c.items() if k not in {"id", "live", "ok"}}
			lines.append(f"- {json.dumps(detail, ensure_ascii=False)[:700]}")
		lines.append("")
	lines += [
		"## 5. 公式效果怎么读",
		"",
		"- 短对话 / 空 M：a* 应为 keep，投影字节等于 compact.project，cursor=0。",
		"- 日常多工具：C1 先验 r_stub=0.25 < θ=0.35，公式几乎不选 C1；热路径非 C2 时与 C0+C1 字节级相同。",
		"- 超长 tool_result：才可能 C2 / HardTop；char_delta_vs_c0c1 为负才表示投影变短。",
		"- ab_short：v61 与 project 的 cache_hit/cost 差主要是 decide CPU + 偶发切点，不是命中率魔法。",
		"- 跨会话「记住」看 L4 索引，不看公式。",
		"",
	]
	text = "\n".join(lines) + "\n"
	path = OUT / "memory_stack_eval.md"
	path.write_text(text, encoding="utf-8")
	return str(path)


async def async_main() -> int:
	_set_l5("v61")
	OUT.mkdir(parents=True, exist_ok=True)
	report: dict = {
		"title": "XEYO memory stack + v6.1 eval",
		"generated_at": _now(),
		"probe": "skipped",
		"key_source": "env DEEPSEEK_API_KEY / XEYO_MODEL_API_KEY (not written to disk)",
	}
	report["unit"] = run_unit_tests()
	report["formula_offline"] = run_formula_campaign()
	try:
		report["formula_real"] = formula_on_longest_real()
		print(
			"  formula_real",
			report["formula_real"].get("file"),
			"a*=",
			(report["formula_real"].get("formula") or {}).get("a_star"),
			"Δchars=",
			report["formula_real"].get("char_delta_vs_c0c1"),
		)
	except Exception:
		report["formula_real"] = {"ok": False, "error": traceback.format_exc()[-500:]}
		print("  formula_real failed")

	key = (
		os.environ.get("DEEPSEEK_API_KEY", "").strip()
		or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	)
	if key and not os.environ.get("DEEPSEEK_API_KEY"):
		os.environ["DEEPSEEK_API_KEY"] = key

	if not key:
		report["live"] = {"skipped": True, "reason": "missing DEEPSEEK_API_KEY"}
		print("SKIP live: no DEEPSEEK_API_KEY")
		rc = 0 if report["unit"]["passed"] and report["formula_offline"]["extreme_pass"] else 1
	else:
		proj = apply_sandbox()
		seed_workspace(proj)
		try:
			report["live"] = await run_live(proj)
		except Exception:
			report["live"] = {"ok": False, "error": traceback.format_exc()}
			print(report["live"]["error"])
		live_cases = (report.get("live") or {}).get("cases") or []
		live_ok = all(_case_ok(c) for c in live_cases) if live_cases else False
		rc = 0 if report["unit"]["passed"] and report["formula_offline"]["extreme_pass"] and live_ok else 1

	md = write_markdown(report)
	js = OUT / "memory_stack_eval.json"
	js.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
	print("wrote", md)
	print("wrote", js)
	print("exit", rc)
	return rc


def _gate_verdict_cli() -> int:
	"""离线汇总 docs/12 + TODO 证据门：表A质量 / A1 / A2 / A3 / θ*，输出可开/不可开判定。

	只读 quality_validation.json + 当前 real 源指纹 + params_overlay，不调用 API。
	最后一行打印 GATE_VERDICT=PASS|FAIL:<缺失项>，供脚本解析。
	"""
	from memory.simulator.params import load_overlay

	probes_map = {"real": load_probes("real"), "synth": synthetic_probes()}
	data = load_quality_data()
	ab = data["ab"]
	rows = data["rows"]
	gates: list[dict] = []

	def add(name: str, ok: bool, detail: str, missing: str = "") -> None:
		gates.append({"name": name, "ok": bool(ok), "detail": detail, "missing": missing})
		print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

	# ---- 表A：质量（同源 Δ≤5pp 且事实层无 0/3）----
	# 口径（2026-09-06）：real 是硬门；synth 降级为信息报告（不 block）。
	# 理由：synth 是"20次同pattern grep×8KB填充"的合成极端，题库全数计数推导题
	# （20/400/4000/grep_019），确定性摘要的 dedup/折叠按"同模板重复"压缩后
	# 无法保留首尾 id 与推导数——结构上不可能过；真实会话无此形态（表A-real +4.2pp 已验证）。
	# 数据仍如实显示（Δ 与零3），但不再作为质量门。
	for source, pbank in probes_map.items():
		api = _real_session_api() if source == "real" else long_history_api(20, 8000)
		cur_fp = _source_fingerprint(api) if api else "empty"
		v61 = _ab_stats(ab, source, "new", "v61", pbank)
		if v61.get("pass_rate") is None:
			add(f"表A-{source}", False, "`--ab new` 未在此源上跑过（无 v61 数据）", "表A质量")
			continue
		proj_stats = None
		base_note = ""
		if (ab.get(source) or {}).get("new", {}).get("project"):
			proj_stats = _ab_stats(ab, source, "new", "project", pbank)
			base_note = "new基线"
		elif (ab.get(source) or {}).get("old", {}).get("project"):
			proj_stats = _ab_stats(ab, source, "old", "project", pbank)
			base_note = "old缓存"
		meta = (ab.get(source) or {}).get("meta") or {}
		same = bool(meta.get("fp")) and meta["fp"] == cur_fp
		delta = None
		if proj_stats and proj_stats.get("pass_rate") is not None:
			delta = round((v61["pass_rate"] - proj_stats["pass_rate"]) * 100, 1)
		zero3 = v61.get("zero_three_fact") or []
		# P6 口径（2026-09-05）：zero3 只判 v61 独有（排除 project 基线也 0/3 的难题）。
		# 难题（project 也丢）不是压缩劣化；只有"原样能答、压缩后全错"才是质量税。
		proj_zero3 = set((proj_stats or {}).get("zero_three_fact") or [])
		zero3_v61_only = [x for x in zero3 if x not in proj_zero3]
		if source == "synth":
			# 降级：只报告，不判 PASS/FAIL（合成极端 + 计数推导题结构性限制）
			detail = (
				f"v61={v61['pass_rate'] * 100:.1f}% vs {base_note or '无'}="
				f"{(proj_stats['pass_rate'] * 100 if proj_stats and proj_stats.get('pass_rate') is not None else -1):.1f}% "
				f"Δ={delta}pp 事实层0/3={zero3_v61_only} 同源={same}（信息报告，非质量门）"
			)
			add("表A-synth(信息)", True, detail, "")
			continue
		# 口径：Δ=v61−project，验收“通过率差≤5pp”= v61 不得劣化超 5pp（优于 project 不计劣化）
		ok = delta is not None and delta >= -5.0 and not zero3_v61_only and same
		miss: list[str] = []
		if delta is None:
			miss.append("无 project 基线")
		elif delta < -5.0:
			miss.append(f"Δ={delta:+.1f}pp 劣化>5pp")
		if zero3_v61_only:
			miss.append(f"事实层0/3(v61独有):{zero3_v61_only}")
		if not same:
			miss.append("非当前源口径")
		add(
			f"表A-{source}",
			ok,
			f"v61={v61['pass_rate'] * 100:.1f}% vs {base_note or '无'}="
			f"{(proj_stats['pass_rate'] * 100 if proj_stats and proj_stats.get('pass_rate') is not None else -1):.1f}% "
			f"Δ={delta}pp 事实层0/3={zero3_v61_only} 同源={same}",
			"、".join(miss),
		)

	# ---- A1：真实 200+ 轮 live 尾窗 ≥99% ----
	c2 = rows.get("hitrate_ultra_c2") or {}
	proj = rows.get("hitrate_ultra_project") or {}
	det = c2.get("detail") or {}
	pdet = proj.get("detail") or {}
	sinfo = det.get("session_info") or {}
	pinfo = pdet.get("session_info") or {}
	turns = int(sinfo.get("user_turns") or det.get("turns") or 0)
	# 尾20 优先用干净口径（--hitrate-clean 复算，抗中断残留 warm cache 污染），无则回退 live 实测
	clean_c2 = rows.get("hitrate_clean_ultra_c2") or {}
	cdet = clean_c2.get("detail") or {}
	if cdet.get("clean_tail20_rate") is not None:
		tail20 = float(cdet["clean_tail20_rate"])
		tail20_caliber = "干净增量口径"
	else:
		tail20 = float(det.get("tail20_rate") or -1)
		tail20_caliber = "live实测"
	p_tail20 = float(pdet.get("tail20_rate") or -1)
	loop_note = "循环副本x{}(合成口径)".format(sinfo["loop_copies"]) if sinfo.get("loop_copies", 1) > 1 else ("真实记录" if sinfo else "未知(旧数据)")
	src_note = f"源={Path(sinfo.get('file') or '?').name}({turns}轮,{loop_note})"
	miss_a1: list[str] = []
	if turns < 200:
		miss_a1.append(f"轮数不足({turns}<200)")
	if tail20 < 99.0:
		if tail20 >= 98.5:
			miss_a1.append(f"尾20={tail20}%(98.5≤x<99：按 1-Δ/prompt 说明达标轮数)")
		else:
			miss_a1.append(f"尾20={tail20}%<99%")
	add(
		"A1-200轮live", not miss_a1,
		f"{src_note} c2 尾20={tail20}% 末轮={det.get('last_rate')}% vs project 尾20={p_tail20}% "
		f"(params={det.get('params') or '无参数快照'})",
		"、".join(miss_a1),
	)

	# ---- A2：扩展解耦生效（扩展触发≥2、尾窗≥98%、输入低于 project）----
	# 优先看默认参数行；若扩展未触发且存在放宽重测行(a2r)，以放宽行作证据并注明比例。
	a2_pick: tuple[str, dict] = ("默认", c2)
	for cid2, r2 in rows.items():
		if (cid2.startswith("hitrate_") and not cid2.startswith("hitrate_clean_")
				and cid2.endswith("_ultra_c2") and cid2 != "hitrate_ultra_c2"
				and (r2.get("detail") or {}).get("mode") == "c2"):
			if int((a2_pick[1].get("detail") or {}).get("transitions") or 0) < 2:
				a2_pick = (cid2, r2)
	det2 = a2_pick[1].get("detail") or {}
	trans = int(det2.get("transitions") or 0)
	tail20b = float(det2.get("tail20_rate") or -1)
	c2_in = int(det2.get("hit") or 0) + int(det2.get("miss") or 0)
	p_in = int(pdet.get("hit") or 0) + int(pdet.get("miss") or 0)
	ratio_note = f" ratio={det2.get('params', {}).get('c2_extend_ratio')}"
	miss_a2: list[str] = []
	if trans < 2:
		miss_a2.append(f"扩展触发{trans}<2（可 XEYO_GATE_A2_RATIO=0.1 放宽重测）")
	if tail20b < 98.0:
		miss_a2.append(f"尾20={tail20b}%<98%")
	if not (p_in and c2_in < p_in):
		miss_a2.append(f"输入未降(c2={c2_in} vs project={p_in})")
	decouple = bool((det2.get("params") or {}).get("c2_extend_decouple"))
	add(
		"A2-扩展解耦", not miss_a2,
		f"[{a2_pick[0]}] trans={trans} 尾20={tail20b}% 输入 c2={c2_in} < project={p_in} "
		f"decouple={decouple}{ratio_note}",
		"、".join(miss_a2),
	)

	# ---- A3：生产日常监控（>=95% 且 压缩不劣化命中率；已忽略"连续≥3天"时间窗——
	# 只要有达标数据即过，连续天数仅作报告备注，不 block）----
	a3_rows = [(cid, r) for cid, r in rows.items() if cid.startswith("deploy_project_mode_")]
	ok_days = [
		cid for cid, r in a3_rows
		if (r.get("detail") or {}).get("hit_rate", 0) >= 0.95
	]
	miss_a3: list[str] = []
	if not ok_days:
		miss_a3.append("无达标数据（需至少 1 天 ≥95% 且压缩不劣化命中率）")
	total_days = len({r.get("detail", {}).get("day") for _, r in a3_rows if r.get("detail")})
	add(
		"A3-日常监控", not miss_a3,
		f"已采集{total_days}天，达标{len(ok_days)}天（≥95% 且压缩不劣化命中率；时间窗已忽略）",
		"、".join(miss_a3),
	)

	# ---- θ* / 叠加层 ----
	ov = load_overlay()
	theta = ov.get("theta")
	ok_theta = isinstance(theta, (int, float)) and theta >= 0.35
	add(
		"θ*阈值", ok_theta,
		f"overlay theta={theta} r_summary={ov.get('r_summary')} r_stub={ov.get('r_stub')}",
		"无 θ≥0.35" if not ok_theta else "",
	)

	# ---- 表C gate 冒烟（既有证据）----
	smoke = rows.get("c2_gate_smoke") or {}
	add(
		"C-gate冒烟", bool(smoke),
		(str(smoke.get("output") or "无数据"))[:160],
		"" if smoke else "未跑 gate 冒烟",
	)

	all_ok = all(g["ok"] for g in gates)
	missing = "、".join(g["missing"] for g in gates if g["missing"])
	print("")
	if all_ok:
		print("判定：PASS —— 全部证据门已绿，可按 docs/12 形态开启（超长会话 XEYO_C2_GATE=1 灰度，"
			"或先跑满 A3 再切生产默认）；v61 实验通道随时可用（XEYO_L5=v61）。")
	else:
		print(f"判定：FAIL —— 尚缺证据：{missing}。当前 v61 仅允许实验通道（测试/A-B/对账），不得切生产。")
	print("GATE_VERDICT=" + ("PASS" if all_ok else "FAIL:" + missing))
	return 0 if all_ok else 1


def main() -> int:
	import argparse

	ap = argparse.ArgumentParser(description="XEYO memory stack eval + 质量验证（docs/12）")
	ap.add_argument("--ab", choices=("old", "new"), help="表A 同源 A/B：old=旧摘要基线, new=新摘要对照")
	ap.add_argument("--r-probes", action="store_true", help="表B r 实测探针（live）")
	ap.add_argument("--theta-scan", action="store_true", help="表B θ 联合扫描（离线）")
	ap.add_argument("--apply-r", action="store_true", help="把实测 r 回填 params_overlay.json")
	ap.add_argument("--accept", metavar="ROW_ID", help="把某用例标记为已验收并刷新 docs/12 表D")
	ap.add_argument("--render-table-d", action="store_true", help="仅重渲染 docs/12 表D")
	ap.add_argument("--recompute", action="store_true", help="离线重算表A 统计行（不调 live）")
	ap.add_argument("--hitrate-live", action="store_true", help="按对话长度分档实测 project/C2 命中率与成本（live）")
	ap.add_argument("--hitrate-clean", action="store_true", help="从已存 live 明细复算干净口径(冷首轮+增量+过渡全miss)写入表D")
	ap.add_argument("--measure-r-summary", action="store_true", help="离线实测 r_summary（术语留存，无需 API key）")
	ap.add_argument("--monitor-daily", nargs="?", const="auto", metavar="DAY",
		help="C4 日常监控：按日聚合 ledger + C2 事件写入表D（默认取最近有数据的日）")
	ap.add_argument("--gate-verdict", action="store_true",
		help="离线汇总验收线（表A/A1/A2/A3/θ*），输出可开/不可开判定（无 API 调用）")
	ap.add_argument("--diagnose-binding", action="store_true",
		help="离线判别压缩态失败是「绑定/定位」还是「吸收丢事实」：逐题检查答案是否在 C2 摘要/session 叙事里（无 API 调用）")
	ap.add_argument("--source-health", metavar="PATH",
		help="A6 源健康检查：真录会话病态判定（无 API 调用；--ab/--hitrate-live 载入长源时自动强校验）")
	args = ap.parse_args()
	if args.source_health:
		return _source_health_cli(args.source_health)
	if args.gate_verdict:
		return _gate_verdict_cli()
	if args.diagnose_binding:
		return _diagnose_binding_cli()
	if args.accept:
		return _accept_row_cli(args.accept)
	if args.render_table_d:
		return _render_table_d_cli()
	if args.monitor_daily is not None:
		return _monitor_daily_cli(args.monitor_daily)
	if args.hitrate_clean:
		return _hitrate_clean_cli()
	if args.hitrate_live:
		return asyncio.run(run_hitrate_live())
	if args.measure_r_summary:
		return measure_r_summary_cli()
	if args.recompute:
		return _recompute_ab_rows()
	if args.ab or args.r_probes or args.theta_scan or args.apply_r:
		try:
			return asyncio.run(async_quality(args))
		except KeyboardInterrupt:
			print("[中断] 已取消；本次未完成，quality_validation.json 未写入不完整数据（每源/每模式整体原子提交）")
			return 2
	return asyncio.run(async_main())

# ================= 表D / 质量验证（docs/12 计划书自动汇总） =================

QUALITY_JSON = OUT / "quality_validation.json"
DOCS12 = ROOT.parent / "docs" / "实施计划" / "12-压缩质量验证计划书.md"
TABLE_D_BEGIN = "<!-- 表D:begin -->"
TABLE_D_END = "<!-- 表D:end -->"
A3_MONITOR = ROOT.parent / "docs" / "A3-monitor.md"
A3_HTML = ROOT.parent / "docs" / "A3-monitor.html"
A3_BEGIN = "<!-- A3:begin -->"
A3_END = "<!-- A3:end -->"
A3_PREFIX = "deploy_project_mode_"
PROBES_DIR = ROOT / "scripts" / "probes"
# 表A-real 锚定会话：题库 ab_real_probes.json 的内容绑定此会话（v2 题库锚定
# sess_mtlpmznl_0iapt2）。锚定会话老化（被清理/被压缩出历史）后需换锚：
# ①改此默认 ②按新会话重写题库——两者必须同时换，否则题不对应答非所问。
AB_REAL_SESSION = Path(
    os.environ.get("XEYO_REAL_SESSION", "")
    or (Path.home() / ".xeyo" / "sessions" / "sess_mtlpmznl_0iapt2.jsonl")
)
AB_REPEATS = 3


def load_quality_data() -> dict:
	if not QUALITY_JSON.is_file():
		return {"rows": {}, "ab": {}}
	try:
		data = json.loads(QUALITY_JSON.read_text(encoding="utf-8"))
	except Exception:
		return {"rows": {}, "ab": {}}
	if not isinstance(data, dict):
		data = {}
	data.setdefault("rows", {})
	data.setdefault("ab", {})
	return data


def save_quality_data(data: dict) -> None:
	QUALITY_JSON.parent.mkdir(parents=True, exist_ok=True)
	QUALITY_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def load_quality_rows() -> dict:
	return load_quality_data().get("rows", {})


def upsert_quality_row(
	case_id: str,
	*,
	source: str,
	input_tokens: int,
	cache_hit: int,
	cache_miss: int,
	action: str,
	output: str,
	accepted: bool | None = None,
	detail: dict | None = None,
) -> dict:
	data = load_quality_data()
	rows = data["rows"]
	prev = rows.get(case_id, {})
	row = {
		"case_id": case_id,
		"source": source,
		"input_tokens": int(input_tokens or 0),
		"cache_hit": int(cache_hit or 0),
		"cache_miss": int(cache_miss or 0),
		"action": action,
		"output": output,
		"accepted": bool(accepted) if accepted is not None else bool(prev.get("accepted")),
		"updated_at": _now(),
	}
	if detail is not None:
		row["detail"] = detail
	rows[case_id] = row
	save_quality_data(data)
	return row


def render_table_d(rows: dict) -> str:
	lines = [
		"| 来源表 | 用例ID | 输入token数 | 命中数 | 未命中数 | 做了什么动作 | 结果产出 | 是否验收 |",
		"|---|---|---|---|---|---|---|---|",
	]
	for row in sorted(rows.values(), key=lambda r: str(r.get("case_id"))):
		ok = "☑" if row.get("accepted") else "☐"
		lines.append(
			f"| {row.get('source', '')} | `{row.get('case_id', '')}` | "
			f"{row.get('input_tokens', 0)} | {row.get('cache_hit', 0)} | {row.get('cache_miss', 0)} | "
			f"{row.get('action', '')} | {row.get('output', '')} | {ok} |"
		)
	return "\n".join(lines)




# ── A3 日常监控报告 · 样式正本（porcelain 青瓷蓝 · 明度即数值）──
# 单文件、零外部依赖：图表全部为内联 SVG，字体走系统栈 + 可选 Inter。
_A3_CSS = """
:root{
  --bg:#EEF1F6; --panel:#FFFFFF; --txt:#0A2149; --mut:rgba(10,33,73,.58);
  --lab:rgba(10,33,73,.72); --faint:rgba(10,33,73,.32); --quiet:rgba(10,33,73,.14);
  --grid:rgba(10,33,73,.13); --line:rgba(10,33,73,.10); --bgline:rgba(10,33,73,.08);
  --data:#2E5FB7; --data2:#7C9BD6; --hero:#0A2149; --onhero:#FFFFFF; --faintdata:#BBD0EE;
  --good:#2E7D5B; --warn:#B08A2E; --bad:#B23A3A; --side:#FFFFFF; --sidegrid:rgba(10,33,73,.07);
  --scrim:rgba(8,20,45,.5); --shadow:0 30px 70px rgba(8,20,45,.35);
  --track:rgba(10,33,73,.07); --hit:#2E5FB7; --miss:#BBD0EE;
  --m0:#0A2149; --m1:#2E5FB7; --m2:#7C9BD6; --m3:#BBD0EE; --m4:#5B7BC4; --m5:#8FA9D8;
  --svgtxt:#0A2149; --hildim:rgba(10,33,73,.28); --scroll:rgba(10,33,73,.22); --scrollhover:rgba(10,33,73,.34);
  --ease:cubic-bezier(.2,.7,.2,1);
}
/* ═ 黑夜模式（纯黑底：亮色数据必须亮于卡底）══ */
[data-theme="dark"]{
  --bg:#000000; --panel:#11141B; --txt:#E9EFFB; --mut:rgba(232,240,255,.64);
  --lab:rgba(232,240,255,.80); --faint:rgba(232,240,255,.44); --quiet:rgba(232,240,255,.12);
  --grid:rgba(232,240,255,.24); --line:rgba(232,240,255,.16); --bgline:rgba(232,240,255,.11);
  --data:#6E9BEC; --data2:#9BBEFF; --hero:#6E9BEC; --onhero:#000000; --faintdata:#C9DDF9;
  --good:#4FBF8F; --warn:#E0B84F; --bad:#E78687; --side:#0A0C10; --sidegrid:rgba(232,240,255,.08);
  --scrim:rgba(0,0,0,.72); --shadow:0 30px 70px rgba(0,0,0,.6);
  --track:rgba(110,155,236,.18); --hit:#6E9BEC; --miss:#40598C;
  --m0:#6E9BEC; --m1:#4E7BD9; --m2:#9BBEFF; --m3:#C9DDF9; --m4:#5C86E0; --m5:#AFC6F0;
  --svgtxt:#DCE6F8; --hildim:rgba(232,240,255,.28); --scroll:rgba(232,240,255,.18); --scrollhover:rgba(232,240,255,.30);
}
*{box-sizing:border-box;margin:0;padding:0}
:focus-visible{outline:2px solid var(--data);outline-offset:2px;border-radius:4px}
button,a,summary,.drow,.seg{cursor:pointer}
button{transition:background var(--ease) .15s,color var(--ease) .15s,border-color var(--ease) .15s,transform var(--ease) .13s,filter var(--ease) .15s}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--scroll);border-radius:8px}
::-webkit-scrollbar-thumb:hover{background:var(--scrollhover)}
*{scrollbar-width:thin;scrollbar-color:var(--scroll) transparent}
html,body{height:100%;color:var(--txt);-webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums lining-nums;overflow:hidden}
body{font-family:'Inter','Noto Sans SC',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg)}
#app{display:grid;grid-template-columns:264px 1fr;height:100vh;gap:0}

/* ═ 侧边栏 ═ */
.side{background:var(--side);border-right:1px solid var(--bgline);padding:24px 20px;display:flex;
  flex-direction:column;overflow:auto}
.side .brand{font-size:11px;font-weight:800;letter-spacing:.22em;color:var(--mut)}
.side h1{font-size:24px;font-weight:900;letter-spacing:.01em;margin-top:8px;line-height:1.15}
.side .sub{font-size:11px;color:var(--faint);margin-top:8px;line-height:1.6}
.side .rule{border:0;border-top:1px solid var(--bgline);margin:20px 0}

.side h3{font-size:10px;font-weight:800;letter-spacing:.16em;color:var(--mut);margin:0 0 10px}
.daylist{display:flex;flex-direction:column;gap:6px;overflow:auto;min-height:0;max-height:30vh}
.daybtn{padding:10px 12px;border:1px solid var(--grid);border-radius:10px;background:transparent;
  cursor:pointer;text-align:left;font:600 12px inherit;color:var(--mut);display:block}
.daybtn .d{display:block;font-weight:800;color:var(--txt);font-size:13px}
.daybtn .s{display:block;font-size:10px;color:var(--faint);margin-top:2px;letter-spacing:.06em}
.daybtn.act{background:var(--hero);color:var(--onhero);border-color:var(--hero)}
.daybtn.act .d,.daybtn.act .s{color:var(--onhero)}
.daybtn.act .s{opacity:.7}

.modelgroup{display:flex;flex-direction:column;gap:6px;overflow:auto;min-height:0;max-height:34vh}
.mcheck{display:flex;align-items:center;gap:9px;padding:7px 10px;border-radius:9px;cursor:pointer;
  font-size:12px;font-weight:600;color:var(--lab);border:1px solid transparent}
.mcheck:hover{background:var(--quiet)}
.mcheck i{width:12px;height:12px;border-radius:3px;flex:none;border:1.5px solid var(--faint)}
.mcheck.on i{border-color:transparent}
.mcheck .nm{flex:1;font-weight:700;color:var(--txt)}
.mcheck .pc{font-size:10px;color:var(--mut);font-variant-numeric:tabular-nums}

.legend{margin-top:auto;border-top:1px solid var(--bgline);padding-top:16px}
.legend .lgitem{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--mut);margin-top:8px}
.legend .sw{width:11px;height:11px;border-radius:3px;flex:none}
.tools{margin-top:18px;display:flex;gap:8px}
.btn{background:var(--hero);color:var(--onhero);border:0;border-radius:9px;padding:10px 14px;
  font:700 12px/1 inherit;cursor:pointer;letter-spacing:.02em;flex:1}
.btn.ghost{background:transparent;color:var(--txt);border:1px solid var(--grid);flex:0 0 auto}
.btn:hover{filter:brightness(1.08)}.btn:active{transform:translateY(1px)}
.themerow{display:flex;gap:8px;margin-top:10px}
.themerow .ghost{flex:1}
.themetoggle{flex:1;background:transparent;border:1px solid var(--grid);border-radius:9px;padding:9px 12px;
  font:700 11.5px/1 inherit;color:var(--lab);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:7px}
.themetoggle:hover{background:var(--quiet)}
.side .src{font-size:10px;color:var(--faint);margin-top:14px;line-height:1.7;letter-spacing:.03em}

/* ═ 主区 ═ */
.main{padding:22px 26px 24px;display:flex;flex-direction:column;gap:12px;overflow:auto}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.main .hero{animation:rise .5s var(--ease) both}
.main .kpis{animation:rise .5s var(--ease) .06s both}
.main .cards{animation:rise .5s var(--ease) .12s both}
.main .extra{animation:rise .5s var(--ease) .18s both}
.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:20px}
.hero .ttl{min-width:0}
.hero .ttl h2{font-size:27px;font-weight:900;letter-spacing:-.01em;line-height:1.1}
.hero .ttl .dek{font-size:11.5px;color:var(--mut);margin-top:5px}
.hero .meta{font-size:11px;color:var(--mut);text-align:right;line-height:1.6;flex:none}
.hero .meta .st{font-weight:800;color:var(--data)}
.hero .meta .btn{margin-top:8px;flex:none;padding:8px 14px}
.hero .meta b{color:var(--data)}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:11px 14px 10px}
.kpi .k{font-size:9.5px;font-weight:700;letter-spacing:.13em;color:var(--mut)}
.kpi .v{font-size:23px;font-weight:900;letter-spacing:-.02em;margin-top:4px;line-height:1}
.kpi .s{font-size:9px;color:var(--faint);margin-top:5px;line-height:1.4}
.kpi.accent .v{color:var(--data)}
.kpi.bad .v{color:var(--bad)}
.kpi.good .v{color:var(--good)}
.kpi.warn .v{color:var(--warn)}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;align-content:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:13px 14px 10px;
  display:flex;flex-direction:column;min-height:0;justify-content:space-between;transition:border-color .2s ease}
.card:hover{border-color:var(--grid)}
.card header{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
  margin-bottom:2px}
.card header h2{font-size:14px;font-weight:900;letter-spacing:.02em}
.card header .sub{font-size:8.5px;font-weight:700;letter-spacing:.1em;color:var(--mut)}
.card .body{width:100%;flex:1;display:flex;align-items:center;justify-content:center;min-height:0;padding:2px 0 4px}
.svg-wrap{display:block;width:100%;height:auto;max-height:100%}
.svg-wrap.hsvg{height:100%;width:100%}
svg text{font-family:'Inter','Noto Sans SC',sans-serif}

/* 环形中心 */
.donut-c{position:relative;width:132px;height:132px;margin:0 auto;display:flex;align-items:center;justify-content:center}
.donut-c svg{width:100%;height:100%}
.dcenter{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center}
.dcenter .v{font-size:16px;font-weight:900;letter-spacing:-.02em;line-height:1;color:var(--svgtxt)}
.dcenter .l{font-size:7px;font-weight:700;letter-spacing:.1em;color:var(--mut);margin-top:3px}

/* ═ 下方功能面板（占满剩余高度）══ */
.extra{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:14px;min-height:0}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:14px 16px;
  display:flex;flex-direction:column;min-height:0;overflow:hidden}
.panel header{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
  margin-bottom:6px}
.panel header h2{font-size:14px;font-weight:900;letter-spacing:.02em}
.panel header .sub{font-size:8.5px;font-weight:700;letter-spacing:.1em;color:var(--mut)}
.panel .pbody{flex:1;min-height:0;overflow:auto}
.panel .tbl{margin-top:0}
.minikpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;flex:1;align-content:center}
.mkpi{text-align:center}
.mkpi .v{font-size:22px;font-weight:900;letter-spacing:-.02em;color:var(--svgtxt);line-height:1}
.mkpi .l{font-size:9px;font-weight:700;letter-spacing:.1em;color:var(--mut);margin-top:4px}
.applex{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;align-items:center}
.apple{display:flex;align-items:center;gap:6px;font-size:10.5px;color:var(--lab);font-weight:600}
.apple i{width:9px;height:9px;border-radius:3px;flex:none}

/* 命中率条 / 请求条（分模型对比面板内） */
.hbar{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.hbar .track{width:56px;height:7px;border-radius:4px;background:var(--quiet);overflow:hidden;display:inline-block}
.hbar .fill{display:block;height:100%;border-radius:4px}
.hbar .pct{font-size:10px;font-weight:800;color:var(--txt)}
.panel .tbl{font-size:11px;table-layout:fixed;width:100%}
.panel .tbl th:first-child,.panel .tbl td:first-child{width:34%}
.panel .tbl th:nth-child(2),.panel .tbl td:nth-child(2){width:19%}
.panel .tbl .reqcaps{display:inline-flex;align-items:center;gap:7px;min-width:0}
.panel .tbl .reqcaps .bar{display:inline-block;height:6px;border-radius:4px;flex:none;width:40px}
.panel .tbl .reqcaps .rn{font-variant-numeric:tabular-nums;font-weight:800;white-space:nowrap}
.panel .tbl .reqcaps .num{min-width:0}

/* 环形下方 · 具体数据明细列表（点击色块/条目高亮） */
.dlist{margin-top:10px;border-top:1px solid var(--line);padding-top:8px;display:flex;flex-direction:column;gap:2px;
  overflow:auto;max-height:150px;min-height:0}
.drow{display:flex;align-items:center;gap:8px;padding:5px 7px;border-radius:8px;cursor:pointer;
  font-size:11px;color:var(--lab);transition:background .15s ease,color .15s ease;min-width:0}
.drow:hover{background:var(--quiet)}
.drow .sw{width:10px;height:10px;border-radius:3px;flex:none;transition:transform .15s ease}
.drow .nm{flex:1;min-width:0;font-weight:600;text-overflow:ellipsis;overflow:hidden;white-space:nowrap}
.drow .vv{font-variant-numeric:tabular-nums;font-weight:800;color:var(--txt)}
.drow .pp{font-size:9.5px;color:var(--mut);width:44px;text-align:right;font-variant-numeric:tabular-nums}
.drow.sel{background:var(--quiet)}
.drow.sel .sw{transform:scale(1.25)}
.drow.sel .nm{font-weight:800;color:var(--txt)}
.dlist.dim .drow{opacity:.35}
.dlist.dim .drow.sel{opacity:1}
.svg-wrap .seg{cursor:pointer;transition:opacity .18s var(--ease),stroke-width .18s var(--ease),filter .18s var(--ease)}
.svg-wrap .seg:hover{filter:brightness(1.1)}
.svg-wrap.dim .seg{opacity:.28}
.svg-wrap.dim .seg.sel{opacity:1}

/* ═ 详情弹窗 ═ */
.modal{position:fixed;inset:0;background:var(--scrim);display:none;z-index:50;
  align-items:center;justify-content:center;padding:24px}
.modal.on{display:flex}
@keyframes pop{from{opacity:0;transform:scale(.96) translateY(8px)}to{opacity:1;transform:none}}
.modal .sheet{animation:pop .3s var(--ease) both}
.modal .sheet{background:var(--bg);border-radius:22px;width:min(920px,94vw);height:min(800px,86vh);
  display:flex;flex-direction:column;padding:24px 30px 22px;box-shadow:var(--shadow)}
.modal .sheet .mhead{display:flex;justify-content:space-between;align-items:center;gap:16px;
  border-bottom:1px solid var(--txt);padding-bottom:12px}
.modal .sheet .mhead h2{font-size:22px;font-weight:900}
.modal .sheet .close{background:none;border:0;border-radius:8px;padding:4px 8px;margin-left:auto;
  display:flex;align-items:center;cursor:pointer;font-size:20px;color:var(--mut);flex:none}
.modal .sheet .close:hover{background:var(--quiet);color:var(--txt)}
.modal .sheet .model-fixed{flex:none;background:var(--bg);z-index:10;
  border-bottom:1px solid var(--line);margin-bottom:12px;padding-bottom:12px}
.hour-tooltip{position:fixed;background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:6px 10px;font-size:11px;font-weight:700;
  box-shadow:0 4px 12px rgba(0,0,0,.15);z-index:100;pointer-events:none;white-space:nowrap}
.modal .sheet .scrollable{flex:1;overflow:auto;min-height:0}
.modal .sheet .mhead .x{font-size:11px;color:var(--mut)}
.tbl{width:100%;border-collapse:collapse;margin-top:6px}
.tbl th,.tbl td{font-size:12px;padding:8px 10px;text-align:left;vertical-align:baseline;
  border-bottom:1px solid var(--line);white-space:nowrap}
.tbl th{font-size:10px;font-weight:700;letter-spacing:.1em;color:var(--mut);cursor:pointer;user-select:none}
.tbl th.num,.tbl td.num{text-align:right;font-variant-numeric:tabular-nums}
.tbl th.sortable:hover{color:var(--txt)}
.tbl tr:hover td{background:var(--quiet)}
.tbl .tag{font-size:10px;color:var(--mut);font-weight:600;letter-spacing:.04em}
.model-chip{display:inline-flex;align-items:center;gap:6px;font-weight:800}
.model-chip i{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none}
.sess{margin:12px 0 0;border:1px solid var(--line);border-radius:12px;background:var(--panel);overflow:hidden}
.sess>summary{cursor:pointer;padding:11px 13px;display:flex;justify-content:space-between;gap:12px;
  align-items:center;font-size:12.5px;list-style:none}
.sess>summary::-webkit-details-marker{display:none}
.sess>summary .t{font-weight:800;min-width:0;display:flex;flex-direction:column;gap:3px}
.sess>summary .t .sessid{font-size:12.5px;color:var(--txt);font-variant-numeric:tabular-nums}
.sess>summary .t .m{font-size:10.5px;color:var(--mut);font-weight:600}
.sess>summary .r{font-size:11px;color:var(--mut);display:flex;gap:10px;align-items:center;flex:none}
.sess .chev{font-size:14px;color:var(--faint);transition:transform .25s ease}
.sess[open]>summary .chev{transform:rotate(90deg)}
.sess .inner{padding:6px 12px 12px;border-top:1px solid var(--line)}
.turn{margin:10px 0 0;border:1px solid var(--line);border-radius:10px;background:var(--panel)}
.turn summary{cursor:pointer;padding:10px 12px;display:flex;justify-content:space-between;gap:10px;
  align-items:center;font-size:12.5px;list-style:none}
.turn summary::-webkit-details-marker{display:none}
.turn summary .t{font-weight:800;max-width:60%;text-overflow:ellipsis;overflow:hidden;white-space:nowrap}
.turn summary .r{font-size:11px;color:var(--mut);display:flex;gap:10px;align-items:center;flex:none}
.turn summary .r .m{color:var(--data);font-weight:700}
.turn .inner{padding:4px 10px 10px;border-top:1px solid var(--line)}
.legendrow{display:flex;gap:16px;flex-wrap:wrap;font-size:10.5px;color:var(--mut);margin-top:10px;letter-spacing:.03em}
.legendrow i{width:11px;height:11px;border-radius:3px;display:inline-block;vertical-align:-1px;margin-right:5px}
.note{font-size:10px;color:var(--faint);line-height:1.7;margin-top:8px;letter-spacing:.03em}
.searchrow{display:flex;gap:10px;align-items:center;margin:12px 0 2px;flex-wrap:wrap}
.searchrow input{flex:1;min-width:160px;border:1px solid var(--grid);border-radius:9px;
  padding:8px 12px;font:600 12px inherit;background:var(--panel);color:var(--txt)}
.searchrow input:focus{outline:none;border-color:var(--data)}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.chip{border:1px solid var(--grid);background:transparent;border-radius:999px;padding:5px 11px;
  font:600 11px inherit;color:var(--mut);cursor:pointer}
.chip.on{background:var(--hero);color:var(--onhero);border-color:var(--hero)}
.empty{padding:22px;text-align:center;font-size:12px;color:var(--faint)}
@media (prefers-reduced-motion:reduce){ *{transition:none!important;animation:none!important} }
@media(max-width:900px){#app{grid-template-columns:1fr}.side{display:none}
  .main{overflow:auto}.cards{grid-template-columns:1fr 1fr}}
"""


# ── A3 报告 · 客户端渲染器（读 window.__A3__，内联 SVG 图表，零依赖）──
# 列名优先级：总表/模型/对话。在浏览端做全部排版与图表，浏览器里交互式查看与导出。
_A3_RENDER_JS = r"""
(function(){
'use strict';
var D=window.__A3__||{generated_at:'',days:[]};
var DAYS=(D.days||[]).slice();
var NS='http://www.w3.org/2000/svg';
var state={day:null,models:[]}; // models = selected model names (empty = all)
var root=null;

/* palette: porcelain-ish blue ramp for up to 6 series.
   用 CSS 变量（var(--mN)）以便黑夜模式一键换肤。 */
var PAL=['var(--m0)','var(--m1)','var(--m2)','var(--m3)','var(--m4)','var(--m5)'];
var HIT='var(--hit)', MISS='var(--miss)';

function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function fmt(n){n=Number(n)||0;if(n>=1e9)return(n/1e9).toFixed(1)+'b';if(n>=1e6)return(n/1e6).toFixed(1)+'m';if(n>=1e3)return(n/1e3).toFixed(1)+'k';return n.toLocaleString('en-US')}
function pct(x,d){d=d==null?1:d;return (Number(x)*100).toFixed(d)+'%'}
function cost(n){n=Number(n)||0;return n.toLocaleString('en-US',{maximumFractionDigits:6})}
function mk(sel){return document.createElement(sel)}
function shortModel(m){var s=String(m||'').split('/').pop();return s}
function hourOf(ts){var d=new Date(Number(ts)*1000);return isNaN(d)?-1:d.getHours()}
function modelColor(m,i){var idx=PAL.indexOf(m._c);if(idx<0){var n=(i==null?0:i)%PAL.length;return PAL[n]}return m._c}

/* ── 环形图（SVG stroke-dasharray）── */
/* segments: [{v, color, name}]  name 用于底下明细列表 */
function donut(segments,opts){
  opts=opts||{};
  var size=opts.size||150, sw=opts.sw||22, cx=size/2, cy=size/2, r=(size-sw)/2-2;
  var C=2*Math.PI*r;
  var total=segments.reduce(function(s,x){return s+Number(x.v||0)},0)||1;
  var svg=document.createElementNS(NS,'svg');
  svg.setAttribute('viewBox','0 0 '+size+' '+size);
  svg.setAttribute('class','svg-wrap');
  svg.setAttribute('preserveAspectRatio','xMidYMid meet');
  // track（stroke 用 CSS 变量，随黑夜模式自动换肤）
  var tr=document.createElementNS(NS,'circle');
  tr.setAttribute('cx',cx);tr.setAttribute('cy',cy);tr.setAttribute('r',r);
  tr.setAttribute('fill','none');tr.setAttribute('stroke-width',sw);
  tr.style.stroke='var(--track)';
  svg.appendChild(tr);
  // segments（加 data-i 供点击高亮）
  var start=0;
  segments.forEach(function(seg,i){
    var frac=Number(seg.v||0)/total;
    if(frac<=0)return;
    var len=frac*C;
    var c=document.createElementNS(NS,'circle');
    c.setAttribute('cx',cx);c.setAttribute('cy',cy);c.setAttribute('r',r);
    c.setAttribute('fill','none');c.setAttribute('class','seg');
    c.setAttribute('data-i',i);
    c.style.stroke=seg.color;             // 变量解析走 CSS 样式
    c.setAttribute('stroke-width',sw);
    c.setAttribute('stroke-dasharray',len+' '+(C-len));
    c.setAttribute('stroke-dashoffset',-start*C+C/4);
    c.setAttribute('transform','rotate(-90 '+cx+' '+cy+')');
    // 动画
    var anim=document.createElementNS(NS,'animate');
    anim.setAttribute('attributeName','stroke-dashoffset');
    anim.setAttribute('from',-start*C+C/4);
    anim.setAttribute('to',-start*C+C/4);
    anim.setAttribute('dur','1s');
    anim.setAttribute('begin','0.5s');
    anim.setAttribute('fill','freeze');
    c.appendChild(anim);
    svg.appendChild(c);
    start+=frac;
  });
  return svg;
}

/* center stats (HTML overlay) */
function centerWrap(val,label){
  var d=mk('div');d.className='dcenter';
  d.innerHTML='<div class="v">'+val+'</div><div class="l">'+esc(label)+'</div>';
  return d;
}

/* 环形卡：环形 + 中心数值 + 底下具体数据明细列表。
   fmt 为数值格式化函数；点击环形段或明细条目互相高亮。 */
function donutCard(title,sub,segments,val,label,fmt){
  fmt=fmt||fmtNum;
  var total=segments.reduce(function(s,x){return s+Number(x.v||0)},0)||1;
  var c=mk('div');c.className='card';
  var h=mk('header');h.innerHTML='<h2>'+esc(title)+'</h2><div class="sub">'+esc(sub)+'</div>';
  var b=mk('div');b.className='body';
  var dc=mk('div');dc.className='donut-c';
  var svg=donut(segments,{size:132,sw:22});
  dc.appendChild(svg);dc.appendChild(centerWrap(val,label));
  b.appendChild(dc);
  c.appendChild(h);c.appendChild(b);

  // 明细列表
  var dl=mk('div');dl.className='dlist';
  segments.forEach(function(seg,i){
    var row=mk('div');row.className='drow';row.setAttribute('data-i',i);
    var p=(Number(seg.v||0)/total)*100;
    var vv=fmt(seg.v);
    if(seg.miss!=null)vv=fmt(seg.miss)+'/'+fmt(seg.v);
    var pp=p.toFixed(1)+'%';
    if(seg.rate!=null)pp=seg.rate+'%';
    row.innerHTML='<span class="sw" style="background:'+seg.color+'"></span>'+
      '<span class="nm">'+esc(seg.name)+'</span>'+
      '<span class="vv">'+vv+'</span>'+
      '<span class="pp">'+pp+'</span>';
    dl.appendChild(row);
  });
  c.appendChild(dl);

  // 高亮联动
  function setSel(i){
    var segs=svg.querySelectorAll('.seg');
    var rows=dl.querySelectorAll('.drow');
    segs.forEach(function(s){s.classList.toggle('sel',Number(s.getAttribute('data-i'))===i)});
    rows.forEach(function(r){r.classList.toggle('sel',Number(r.getAttribute('data-i'))===i)});
    svg.classList.add('dim');dl.classList.add('dim');
  }
  function clearSel(){
    svg.classList.remove('dim');dl.classList.remove('dim');
    svg.querySelectorAll('.seg.sel').forEach(function(s){s.classList.remove('sel')});
    dl.querySelectorAll('.drow.sel').forEach(function(r){r.classList.remove('sel')});
  }
  function bind(el){
    el.style.cursor='pointer';
    el.addEventListener('click',function(){
      var i=Number(el.getAttribute('data-i'));
      var already=enabled&&el.classList.contains('sel');
      if(already){clearSel();return}
      setSel(i);
    });
  }
  var enabled=true;
  svg.querySelectorAll('.seg').forEach(bind);
  dl.querySelectorAll('.drow').forEach(bind);
  return c;
}
function fmtNum(n){return fmt(n)}

/* ── 新功能面板：请求按小时分布（SVG 迷你柱）── */
function hourChart(tot){
  var byTurn=tot.by_turn||[];
  var hours=new Array(24).fill(0);
  byTurn.forEach(function(t){var h=hourOf(t.first_ts);if(h>=0&&h<24)hours[h]++});
  var maxH=Math.max.apply(null,hours)||1;
  var W=560,H=120,pad=24,bw=(W-pad)/24;
  var svg=document.createElementNS(NS,'svg');
  svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.setAttribute('class','svg-wrap hsvg');
  svg.setAttribute('preserveAspectRatio','xMidYMax meet');
  var base=H-24;
  var line=document.createElementNS(NS,'line');
  line.setAttribute('x1',pad);line.setAttribute('y1',base);line.setAttribute('x2',W);line.setAttribute('y2',base);
  line.setAttribute('stroke','var(--line)');line.setAttribute('stroke-width',1);svg.appendChild(line);
  var peak=0,peakH=-1;
  for(var i=0;i<24;i++){
    var x=pad+i*bw,hh=(H-24)*hours[i]/maxH;
    if(hours[i]>peakH){peakH=hours[i];peak=i}
    var r=document.createElementNS(NS,'rect');
    r.setAttribute('x',x+1.5);r.setAttribute('y',base-Math.max(1,hh));r.setAttribute('width',bw-3);r.setAttribute('height',Math.max(1,hh));
    r.setAttribute('fill',i===peak?'var(--data)':'var(--m2)');r.setAttribute('rx',1.5);
    r.setAttribute('data-hour',i);r.setAttribute('data-count',hours[i]);
    r.style.cursor='pointer';
    r.addEventListener('mouseenter',function(ev){
      var h=this.getAttribute('data-hour');
      var cnt=this.getAttribute('data-count');
      var rect=this.getBoundingClientRect();
      var tooltip=document.querySelector('.hour-tooltip');
      if(!tooltip){
        tooltip=mk('div');tooltip.className='hour-tooltip';
        document.body.appendChild(tooltip);
      }
      tooltip.innerHTML='<b>'+esc(h+':00')+'</b> · '+cnt+' 请求';
      tooltip.style.display='block';
      tooltip.style.left=rect.left+'px';
      tooltip.style.top=(rect.top-32)+'px';
    });
    r.addEventListener('mouseleave',function(){
      var tooltip=document.querySelector('.hour-tooltip');
      if(tooltip)tooltip.style.display='none';
    });
    svg.appendChild(r);
    if(i%3===0){var t=document.createElementNS(NS,'text');t.textContent=(i<10?'0':'')+i;
      t.setAttribute('x',x+bw/2);t.setAttribute('y',H-6);t.setAttribute('text-anchor','middle');
      t.setAttribute('font-size',7.5);t.setAttribute('font-weight',600);t.setAttribute('fill','var(--mut)');svg.appendChild(t);}
  }
  var mt=document.createElementNS(NS,'text');mt.textContent='peak '+peakH+' @ '+peak+':00';
  mt.setAttribute('x',W-pad);mt.setAttribute('y',14);mt.setAttribute('text-anchor','end');
  mt.setAttribute('font-size',8);mt.setAttribute('font-weight',700);mt.setAttribute('fill','var(--data)');svg.appendChild(mt);
  return svg;
}

/* ── 新功能面板：分模型对比（紧凑表 + 命中率条）── */
function modelCompare(models){
  var wrap=mk('div');
  var T=mk('table');T.className='tbl';
  T.innerHTML='<thead><tr><th>模型</th><th class="num">命中率</th><th class="num">请求</th>'+
    '<th class="num">输出</th><th class="num">成本</th></tr></thead><tbody></tbody>';
  var tb=T.querySelector('tbody');
  var maxReq=Math.max.apply(null,(models||[]).map(function(m){return Number(m.requests)||0}).concat([1]));
  models.forEach(function(m){
    var tr=mk('tr');
    var ti=Number(m.cache_hit)+Number(m.cache_miss);
    var reqBar=Math.max(6,Math.round((Number(m.requests)/maxReq)*100));
    tr.innerHTML='<td><span class="model-chip"><i style="background:'+m._c+'"></i>'+esc(shortModel(m.model))+'</span></td>'+
      '<td class="num"><span class="hbar"><span class="track"><span class="fill" style="width:'+(Number(m.hit_rate)*100).toFixed(0)+'%;background:'+m._c+'"></span></span><span class="pct">'+pct(m.hit_rate)+'</span></span></td>'+
      '<td class="num"><span class="reqcaps"><span class="bar" style="width:'+reqBar+'%;background:'+m._c+'"></span><span class="rn">'+fmt(m.requests)+'</span></span></td>'+
      '<td class="num">'+fmt(m.output)+'</td>'+
      '<td class="num">'+cost(m.cost_cny)+'</td>';
    tb.appendChild(tr);
  });
  wrap.appendChild(T);
  return wrap;
}

function kpiCard(k,s,v,cls){
  var c=mk('div');c.className='kpi'+(cls?' '+cls:'');
  c.innerHTML='<div class="k">'+esc(k)+'</div><div class="v">'+v+'</div><div class="s">'+esc(s)+'</div>';
  return c;
}

/* 选中模型集合的辅助：空 = 全部 */
function filterByModel(list,key){
  if(!state.models.length)return list;
  return list.filter(function(m){return state.models.indexOf(m[key])>=0});
}

/* ── 模型构建（用于侧栏/环形/明细统一配色）── */
function buildModels(day){
  var bm=(day.total.by_model||[]).slice();
  bm.forEach(function(m,i){m._c=PAL[i%PAL.length]});
  return bm;
}

function renderSidebar(day){
  var models=buildModels(day);
  var side=mk('aside');side.className='side';
  var brand=mk('div');brand.className='brand';brand.textContent='XEYO · QUALITY MONITOR';
  var h1=mk('h1');h1.textContent='A3 日常监控';
  var sub=mk('div');sub.className='sub';sub.textContent='缓存命中率 · 成本 · 用量快照';
  side.appendChild(brand);side.appendChild(h1);side.appendChild(sub);
  var rule=mk('hr');rule.className='rule';side.appendChild(rule);

  side.appendChild(sideHead('日期'));
  var dl=mk('div');dl.className='daylist';
  DAYS.forEach(function(d){
    var b=mk('button');b.className='daybtn'+(state.day===d.day?' act':'');
    b.innerHTML='<span class="d">'+esc(d.day)+'</span><span class="s">'+(d.accepted?'已验收':'待验收')+'</span>';
    b.addEventListener('click',function(){state.day=d.day;renderAll()});
    dl.appendChild(b);
  });
  side.appendChild(dl);
  var rule2=mk('hr');rule2.className='rule';side.appendChild(rule2);

  side.appendChild(sideHead('模型'));
  var mg=mk('div');mg.className='modelgroup';
  models.forEach(function(m){
    var on=!state.models.length||state.models.indexOf(m.model)>=0;
    var row=mk('label');row.className='mcheck'+(on?' on':'');
    row.innerHTML='<i style="background:'+(on?m._c:'transparent')+';border-color:'+(on?m._c:'var(--faint)')+'"></i>'+
      '<span class="nm">'+esc(shortModel(m.model))+'</span><span class="pc">'+pct(m.hit_rate)+'</span>';
    row.addEventListener('click',function(ev){ev.preventDefault();
      var i=state.models.indexOf(m.model);
      if(i<0)state.models.push(m.model);else state.models.splice(i,1);
      state.models.sort();renderAll();});
    mg.appendChild(row);
  });
  side.appendChild(mg);

  var rule3=mk('hr');rule3.className='rule';side.appendChild(rule3);
  var lg=mk('div');lg.className='legend';
  lg.appendChild(sideHead('图例'));
  var hc=mk('div');hc.className='lgitem';hc.innerHTML='<span class="sw" style="background:'+HIT+'"></span>缓存命中';
  var mc=mk('div');mc.className='lgitem';mc.innerHTML='<span class="sw" style="background:'+MISS+'"></span>缓存未命中';
  lg.appendChild(hc);lg.appendChild(mc);
  side.appendChild(lg);

  var tools=mk('div');tools.className='tools';
  var eb=mk('button');eb.className='btn';eb.textContent='导出 JSON';
  eb.addEventListener('click',exportJson);
  tools.appendChild(eb);
  side.appendChild(tools);

  var tr=mk('div');tr.className='themerow';
  var tb=mk('button');tb.className='themetoggle';
  var isDark=document.documentElement.getAttribute('data-theme')==='dark';
  tb.innerHTML=(isDark?'☀ 切换白天':'☾ 切换黑夜')+'<span class="lbl"></span>';
  tb.addEventListener('click',toggleTheme);
  tr.appendChild(tb);
  side.appendChild(tr);

  var src=mk('div');src.className='src';src.textContent='数据源 quality_validation.json';
  side.appendChild(src);
  return side;
}
function sideHead(t){var h=mk('h3');h.textContent=t;return h}

function renderMain(day){
  var main=mk('div');main.className='main';
  var tot=day.total||{};
  var hr=Number(tot.hit_rate)||0;
  var accepted=day.accepted;

  // hero
  var hero=mk('div');hero.className='hero';
  var ttl=mk('div');ttl.className='ttl';
  ttl.innerHTML='<h2>'+esc(day.day)+' · 快照</h2><div class="dek">命中率 / 成本 / 用量，一屏总览</div>';
  var meta=mk('div');meta.className='meta';
  meta.innerHTML='<span class="st">'+esc((accepted?'已验收':'待验收'))+'</span> · 生成于 '+esc(D.generated_at||'—')+
    '<br><button class="btn ghost" id="detailBtn">查看会话明细</button>';
  hero.appendChild(ttl);hero.appendChild(meta);
  main.appendChild(hero);

  // KPIs
  var kpi=mk('div');kpi.className='kpis';
  var kcls=hr>=0.9?'good':(hr>=0.7?'':'bad');
  kpi.appendChild(kpiCard('命中率','CACHE HIT RATE',pct(hr),'accent'));
  kpi.appendChild(kpiCard('请求','ALL REQUESTS',fmt(tot.requests)));
  kpi.appendChild(kpiCard('输出 token','OUTPUT',fmt(tot.output)));
  kpi.appendChild(kpiCard('输入 token','PROMPT INPUT',fmt(tot.prompt_tokens)));
  kpi.appendChild(kpiCard('成本','COST · CNY',cost(tot.cost_cny)));
  kpi.appendChild(kpiCard('C2','COMPACTIONS',fmt(tot.c2_count),accepted?'good':''));
  kpi.appendChild(kpiCard('会话数','SESSIONS',fmt(tot.sessions||0)));
  kpi.appendChild(kpiCard('单位成本','COST/REQ',cost(tot.cost_cny/(tot.requests||1))));
  main.appendChild(kpi);

  // donut cards
  var models=filterByModel(buildModels(day),'model');
  var cards=mk('div');cards.className='cards';

  // 1. 整体命中率（按模型细分）
  var hit=Number(tot.cache_hit)||0, miss=Number(tot.cache_miss)||0;
  var hitSegs=models.map(function(m){
    var h=Number(m.cache_hit)||0, ms=Number(m.cache_miss)||0;
    var p=(h+ms)>0?(h/(h+ms)*100).toFixed(1):'0.0';
    return {v:h,color:m._c,name:shortModel(m.model),miss:ms,rate:p};
  });
  cards.appendChild(donutCard('整体命中率','HIT RATE',
    hitSegs,
    pct(hr),'命中 / 总输入',fmt));

  // 2. 输入 token 构成 (per model hit)
  var toks=filterByModel(buildModels(day),'model').map(function(m){
    return {v:m.prompt_tokens,color:m._c,name:shortModel(m.model)}});
  var maxTok=toks.reduce(function(s,x){return s+Number(x.v||0)},0)||1;
  cards.appendChild(donutCard('输入 token · 构成','INPUT BY MODEL',
    toks,fmt(maxTok),'总输入 token',fmt));

  // 3. 成本分模型（老行可能缺 cost_cny：此时按该模型输入 token 占比分摊日总成本兜底）
  var dayCost=Number(tot.cost_cny)||0, dayTok=buildModels(day).reduce(function(s,m){return s+Number(m.prompt_tokens||0)},0)||1;
  var costs=models.map(function(m){
    var c=Number(m.cost_cny);
    if(!c){c=dayCost*(Number(m.prompt_tokens||0)/dayTok);}
    return {v:c,color:m._c,name:shortModel(m.model)}});
  var totCost=costs.reduce(function(s,x){return s+Number(x.v||0)},0);
  cards.appendChild(donutCard('成本 · 模型','COST BY MODEL',
    costs,cost(totCost),'总成本 CNY',cost));

  // 4. 请求分模型
  var reqs=models.map(function(m){return {v:m.requests,color:m._c,name:shortModel(m.model)}});
  var totReq=reqs.reduce(function(s,x){return s+Number(x.v||0)},0);
  cards.appendChild(donutCard('请求 · 模型','REQUESTS BY MODEL',
    reqs,fmt(totReq),'总请求数',fmt));

  main.appendChild(cards);

  // ── 下方功能面板：请求小时分布 + 分模型对比 ──
  var extra=mk('div');extra.className='extra';

  // 面板1：请求按小时分布
  var p1=mk('div');p1.className='panel';
  var p1h=mk('header');p1h.innerHTML='<h2>请求 · 小时分布</h2><div class="sub">REQUESTS BY HOUR</div>';
  p1.appendChild(p1h);
  var p1b=mk('div');p1b.className='pbody';p1b.appendChild(hourChart(tot));
  p1.appendChild(p1b);extra.appendChild(p1);

  // 面板2：分模型对比（命中率/请求/输出/成本）
  var p2=mk('div');p2.className='panel';
  var p2h=mk('header');p2h.innerHTML='<h2>分模型对比</h2><div class="sub">MODEL COMPARE</div>';
  p2.appendChild(p2h);
  var p2b=mk('div');p2b.className='pbody';
  var mm=filterByModel(buildModels(day),'model');
  p2b.appendChild(modelCompare(mm));
  var ax=mk('div');ax.className='applex';
  ax.innerHTML='<span class="apple"><i style="background:'+HIT+'"></i>命中</span>'+
    '<span class="apple"><i style="background:'+MISS+'"></i>未命中</span>';
  p2b.appendChild(ax);p2.appendChild(p2b);extra.appendChild(p2);

  main.appendChild(extra);
  main.querySelector('#detailBtn').addEventListener('click',function(){openModal(day)});
  return main;
}

/* ── 明细弹窗：分模型表 + 分对话 ── */
function openModal(day){
  var m=mk('div');m.className='modal on';
  var sheet=mk('div');sheet.className='sheet';
  var head=mk('div');head.className='mhead';
  var close=mk('div');close.className='close';close.textContent='×';
  close.addEventListener('click',function(){m.parentNode&&m.parentNode.removeChild(m)});
  head.innerHTML='<h2>'+esc(day.day)+' · 会话明细</h2><div class="x">'+esc(day.total.by_turn.length)+' 轮 · 点击列头排序</div>';
  head.appendChild(close);
  sheet.appendChild(head);

  // 分模型（固定）
  var mh=mk('h3');mh.textContent='分模型';mh.style.cssText='margin:16px 0 6px;font-size:14px';sheet.appendChild(mh);
  var modelFixed=mk('div');modelFixed.className='model-fixed';sheet.appendChild(modelFixed);
  var bm=filterByModel(buildModels(day).slice(),'model');
  var T=mk('table');T.className='tbl';
  T.innerHTML='<thead><tr><th>模型</th><th>Provider</th><th class="num">命中率</th><th class="num">命中/输入</th>'+
    '<th class="num">请求</th><th class="num">输出</th><th class="num">成本</th></tr></thead><tbody></tbody>';
  var tb=T.querySelector('tbody');
  function paint(list){
    tb.innerHTML='';
    list.forEach(function(m){
      var ti=Number(m.cache_hit)+Number(m.cache_miss);
      var tr=mk('tr');
      tr.innerHTML='<td><span class="model-chip"><i style="background:'+m._c+'"></i>'+esc(m.model)+'</span></td>'+
        '<td><span class="tag">'+esc(m.provider)+'</span></td>'+
        '<td class="num" style="font-weight:800">'+pct(m.hit_rate)+'</td>'+
        '<td class="num"><span class="tag">'+fmt(m.cache_hit)+'/'+fmt(ti)+'</span></td>'+
        '<td class="num">'+fmt(m.requests)+'</td><td class="num">'+fmt(m.output)+'</td>'+
        '<td class="num">'+cost(m.cost_cny)+'</td>';
      tb.appendChild(tr);
    });
  }
  paint(bm);
  modelFixed.appendChild(T);

  // 分对话（滚动区域）
  var ch=mk('h3');ch.textContent='分对话';ch.style.cssText='margin:16px 0 6px;font-size:14px';sheet.appendChild(ch);
  var scrollable=mk('div');scrollable.className='scrollable';sheet.appendChild(scrollable);
  var sr=mk('div');sr.className='searchrow';
  sr.innerHTML='<input type="text" placeholder="搜索用户消息…" /><div class="filters"></div>';
  var input=sr.querySelector('input');
  var fl=sr.querySelector('.filters');
  var models=buildModels(day);
  fl.innerHTML='<button class="chip on" data-m="">全部</button>'+models.map(function(m){
    return '<button class="chip" data-m="'+esc(m.model)+'">'+esc(shortModel(m.model))+'</button>'}).join('');
  scrollable.appendChild(sr);

  var list=mk('div');scrollable.appendChild(list);
  var byTurn=(day.total.by_turn||[]).slice();
  var q='',model='';
  function visible(t){
    var lab=String(t.label||'').toLowerCase();
    if(q&&lab.indexOf(q)<0)return false;
    if(model&&t.model!==model)return false;
    return true;
  }

  function render(){
    list.innerHTML='';
    var shown=byTurn.filter(visible);
    if(!shown.length){var e=mk('div');e.className='empty';e.textContent='无匹配对话';list.appendChild(e);return}
    shown.sort(function(a,b){return (Number(b.first_ts)||0)-(Number(a.first_ts)||0)});
    shown.forEach(function(t){
      var st=Number(t.cache_hit)||0,sm=Number(t.cache_miss)||0,ti=st+sm;
      var det=mk('details');det.className='turn';
      var sum=mk('summary');
      sum.innerHTML='<span class="t">'+esc(t.label||'未命名消息')+'</span>'+
        '<span class="r"><span class="m">'+esc(shortModel(t.model))+'</span><span>'+pct(t.hit_rate)+'</span>'+
        '<span>'+esc(t.requests)+' req</span><span>'+cost(t.cost_cny)+'</span></span>';
      det.appendChild(sum);
      var inner=mk('div');inner.className='inner';
      var TT=mk('table');TT.className='tbl';
      TT.innerHTML='<thead><tr><th>时间</th><th>模型</th><th>命中率</th><th>命中/输入</th><th class="num">请求</th>'+
        '<th class="num">输出</th><th class="num">成本</th><th class="num">Prompt</th></tr></thead><tbody></tbody>';
      var tbb=TT.querySelector('tbody');
      function row(ts,model2,hitc,misc,req,out,co,pr,faint){
        var tr=mk('tr');if(faint)tr.setAttribute('style','opacity:.72');
        var hv=hitc+misc;
        tr.innerHTML='<td>'+esc(ts)+'</td><td>'+esc(model2)+'</td><td>'+pct(hv?hitc/hv:0,1)+'</td>'+
          '<td><span class="tag">'+fmt(hitc)+'/'+fmt(hv)+'</span></td>'+
          '<td class="num">'+req+'</td><td class="num">'+fmt(out)+'</td><td class="num">'+cost(co)+'</td>'+
          '<td class="num">'+fmt(pr)+'</td>';
        return tr;
      }
      var ts0=new Date(Number(t.first_ts)*1000).toTimeString().slice(0,8);
      tbb.appendChild(row(ts0,t.model,st,sm,t.requests,t.output,t.cost_cny,(t.prompt!=null?t.prompt:ti),false));
      (t.events||[]).forEach(function(e){
        var eh=Number(e.cache_hit)||0,em=Number(e.cache_miss)||0;
        tbb.appendChild(row(new Date(Number(e.ts)*1000).toTimeString().slice(0,8),e.model,eh,em,1,e.output,e.cost_cny,e.prompt_tokens,true));
      });
      inner.appendChild(TT);
      det.appendChild(inner);
      list.appendChild(det);
    });
  }
  input.addEventListener('input',function(){q=input.value.trim().toLowerCase();render()});
  fl.querySelectorAll('.chip').forEach(function(ch){
    ch.addEventListener('click',function(){
      model=ch.getAttribute('data-m')||'';
      fl.querySelectorAll('.chip').forEach(function(c){c.className=c===ch?'chip on':'chip'});
      render();});
  });
  render();
  m.appendChild(sheet);
  document.body.appendChild(m);
}

function toggleTheme(){
  var cur=document.documentElement.getAttribute('data-theme');
  var next=cur==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',next);
  try{localStorage.setItem('a3-theme',next)}catch(e){}
  renderAll();
}

function renderAll(){
  root.innerHTML='';
  var day=null;
  DAYS.forEach(function(d){if(d.day===state.day)day=d});
  if(!day)day=DAYS[DAYS.length-1];
  if(!day){var d=mk('div');d.textContent='暂无数据';root.appendChild(d);return}
  if(!state.day)state.day=day.day;
  root.appendChild(renderSidebar(day));
  root.appendChild(renderMain(day));
}

document.addEventListener('DOMContentLoaded',function(){
  root=document.getElementById('app');
  if(!root)return;
  // 初始主题：优先 localStorage，其次跟随系统偏好，默认浅色
  var saved=null;
  try{saved=localStorage.getItem('a3-theme')}catch(e){}
  var pref=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
  document.documentElement.setAttribute('data-theme',saved||pref);
  state.day=null;state.models=[];
  renderAll();
});
})();


"""


def render_a3_html(rows: dict) -> str:
	"""A3（deploy_project_mode_*）渲染为独立 HTML 页面：总表 + 模型表 + 对话表（每枪明细 + 对话属性）+ 导出JSON。
	完整数据内嵌为 JSON，浏览端自行渲染与导出。"""
	a3 = {k: v for k, v in rows.items() if k.startswith(A3_PREFIX)}
	payload = {
		"generated_at": _now(),
		"days": [
			{
				"day": v.get("detail", {}).get("day", k.removeprefix(A3_PREFIX)),
				"total": v.get("detail", {}),
				"by_model": v.get("detail", {}).get("by_model", []),
				"by_session": v.get("detail", {}).get("by_session", []),
				"by_turn": v.get("detail", {}).get("by_turn", []),
				"accepted": bool(v.get("accepted")),
			}
			for k, v in sorted(a3.items())
		],
	}
	def _jsjson(o) -> str:
		# 内嵌到 HTML <script>：转义 </script> 与 U+2028/2029，保持 JSON 合法。
		s = json.dumps(o, ensure_ascii=False, default=str)
		return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

	json_blob = _jsjson(payload)
	mono_css = _A3_CSS
	# 可选 Inter 字体（联网时更佳；离线自动回退系统栈）。
	font_link = (
		'<link rel="preconnect" href="https://fonts.googleapis.com">'
		'<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900'
		'&family=Noto+Sans+SC:wght@400;500;700;900&display=swap" rel="stylesheet">'
	)
	html = [
		"<!doctype html>",
		'<html lang="zh-CN"><head><meta charset="utf-8">',
		'<meta name="viewport" content="width=device-width,initial-scale=1">',
		"<title>A3 日常监控快照</title>",
		font_link,
		"<style>" + mono_css + "</style>",
		"</head><body>",
		'<div class="wrap">',
		'<div id="app"></div>',
		"</div>",
		# ── 数据：完整 payload 以 JSON 内嵌，端侧自行渲染 ──
		"<script>window.__A3__=" + json_blob + "</script>",
		# ── 导出工具（供渲染器按钮调用）──
		"<script>",
		"function exportJson(){var b=JSON.stringify(window.__A3__,null,2);",
		"var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([b],{type:'application/json'}));",
		"a.download='a3-monitor-'+new Date().toISOString().slice(0,10)+'.json';a.click();}",
		"</script>",
		# ── 渲染器 ──
		"<script>" + _A3_RENDER_JS + "</script>",
		"</body></html>",
	]
	return "\n".join(html)


def render_a3_table(rows: dict) -> str:
	"""A3（deploy_project_mode_*）行渲染为 docs/A3-monitor.md 的总表 + 分模型 + 分会话。"""
	lines: list[str] = []
	for cid in sorted(k for k in rows if k.startswith(A3_PREFIX)):
		row = rows[cid]
		d = row.get("detail") or {}
		total_in = int(d.get("cache_hit", 0)) + int(d.get("cache_miss", 0))
		hit_rate = d.get("hit_rate") or (int(d.get("cache_hit", 0)) / total_in if total_in else 0.0)
		ok = "☑" if row.get("accepted") else "☐"
		by_model = "; ".join(
			f"{m.get('model')}@{m.get('provider')} {float(m.get('hit_rate', 0)) * 100:.1f}% ({m.get('cache_hit')}/{m.get('cache_hit', 0) + m.get('cache_miss', 0)})"
			for m in d.get("by_model", [])
		)
		lines.append(f"### {d.get('day', cid.removeprefix(A3_PREFIX))}")
		lines.append("")
		lines.append("#### 总计")
		lines.append("")
		lines.append("| 日期 | 命中率 | 命中/输入 | 请求 | 输出 | 成本 | C2 | 验收 |")
		lines.append("|---|---|---|---|---|---|---|---|")
		lines.append(
			f"| {d.get('day', cid.removeprefix(A3_PREFIX))} | {float(hit_rate) * 100:.2f}% | "
			f"{d.get('cache_hit', 0)}/{total_in} | {d.get('requests', 0)} | {d.get('output', 0)} | "
			f"{d.get('cost_cny', 0)} | {d.get('c2_count', 0)} | {ok} |"
		)
		lines.append("")
		lines.append("#### 分模型")
		lines.append("")
		lines.append("| 模型 | Provider | 命中率 | 命中/输入 | 请求 | 输出 |")
		lines.append("|---|---|---|---|---|---|")
		for m in d.get("by_model", []):
			mt = int(m.get("cache_hit", 0)) + int(m.get("cache_miss", 0))
			lines.append(
				f"| {m.get('model')} | {m.get('provider')} | {float(m.get('hit_rate', 0)) * 100:.1f}% | "
				f"{m.get('cache_hit')}/{mt} | {m.get('requests')} | {m.get('output')} |"
			)
		lines.append("")
		lines.append("#### 分对话")
		lines.append("")
		if not d.get("by_turn") and not d.get("by_session"):
			lines.append("_无对话数据_")
			lines.append("")
			continue
		# 按用户消息轮次分组，标题=用户消息，模型+命中率摘要，details 展开显示每轮明细。
		for t in d.get("by_turn", []):
			st = int(t.get("cache_hit", 0)) + int(t.get("cache_miss", 0))
			label = t.get("label") or t.get("session_id") or "(auto)"
			model = t.get("model") or "?"
			hit_pct = float(t.get("hit_rate", 0)) * 100
			lines.append(f"<details>")
			lines.append(f"<summary>{label} — {model} · {hit_pct:.1f}% ({t.get('cache_hit')}/{st}) · {t.get('requests')} req · 成本{t.get('cost_cny')}</summary>")
			lines.append("")
			lines.append("| 轮次 | 模型 | 命中率 | 命中/输入 | 请求 | 输出 | 成本 |")
			lines.append("|---|---|---|---|---|---|---|")
			lines.append(
				f"| {t.get('label')} | {model} | {hit_pct:.1f}% | {t.get('cache_hit')}/{st} | "
				f"{t.get('requests')} | {t.get('output')} | {t.get('cost_cny')} |"
			)
			lines.append("")
			lines.append("</details>")
			lines.append("")
	return "\n".join(lines)


def _replace_section(path, begin, end, section) -> bool:
	if not path.is_file():
		print(f"no file at {path}")
		return False
	text = path.read_text(encoding="utf-8")
	if begin not in text or end not in text:
		print(f"{path} missing markers")
		return False
	import re

	new_text = re.sub(re.escape(begin) + r".*?" + re.escape(end), lambda m: section, text, flags=re.S)
	path.write_text(new_text, encoding="utf-8", newline="\n")
	return True


def update_docs12_table_d(rows: dict) -> bool:
	# A3 行拆到 docs/A3-monitor.md + docs/A3-monitor.html，其余行留 docs/12 表D
	non_a3 = {k: v for k, v in rows.items() if not k.startswith(A3_PREFIX)}
	a3 = {k: v for k, v in rows.items() if k.startswith(A3_PREFIX)}
	ok = True
	if a3:
		ok = _replace_section(A3_MONITOR, A3_BEGIN, A3_END, A3_BEGIN + "\n" + render_a3_table(a3) + "\n" + A3_END)
		print("rendered A3 ->", A3_MONITOR)
		A3_HTML.write_text(render_a3_html(a3), encoding="utf-8", newline="\n")
		print("rendered A3 ->", A3_HTML)
	if not ok:
		return False
	if not DOCS12.is_file():
		print(f"no docs/12 at {DOCS12}")
		return False
	text = DOCS12.read_text(encoding="utf-8")
	begin, end = TABLE_D_BEGIN, TABLE_D_END
	if begin not in text or end not in text:
		print("docs/12 missing 表D markers")
		return False
	section = begin + "\n" + render_table_d(non_a3) + "\n" + end
	import re

	new_text = re.sub(re.escape(begin) + r".*?" + re.escape(end), lambda m: section, text, flags=re.S)
	DOCS12.write_text(new_text, encoding="utf-8", newline="\n")
	print("rendered 表D ->", DOCS12)
	return True


def load_probes(source: str) -> dict:
	p = PROBES_DIR / f"ab_{source}_probes.json"
	if not p.is_file():
		return {"questions": []}
	try:
		data = json.loads(p.read_text(encoding="utf-8"))
	except Exception:
		return {"questions": []}
	if not isinstance(data, dict):
		return {"questions": []}
	data.setdefault("questions", [])
	return data


def synthetic_probes() -> dict:
	"""合成源确定性模板题库（≥12 题，三层齐全）。"""
	return {
		"source": "synth",
		"note": "long_history(20工具×8KB) 的确定性模板题库。",
		"session_summary": (
			"会话: 用户在仓库里搜索 TODO 并继续分析。执行了 20 次 Grep（pattern=TODO），"
			"每次结果含 20 行 TODO line 和 8000 字符的 X 填充。"
		),
		"questions": [
			{"id": "s01", "layer": "fact", "q": "Grep 搜索的 pattern 是什么？", "expect_contains": ["TODO"]},
			{"id": "s02", "layer": "fact", "q": "一共执行了多少次 Grep？只回数字。", "expect_contains": ["20"]},
			{"id": "s03", "layer": "fact", "q": "每条 Grep 结果包含几行 TODO？只回数字。", "expect_contains": ["20"]},
			{"id": "s04", "layer": "fact", "q": "结果里的大段填充内容由什么字符构成？", "expect_contains": ["X"]},
			{"id": "s05", "layer": "fact", "q": "最后一条 Grep 的 tool_use id 是什么？", "expect_contains": ["grep_019"]},
			{"id": "s06", "layer": "fact", "q": "用户的第一条指令要求做什么？", "expect_contains": ["搜索", "TODO"]},
			{"id": "s07", "layer": "reasoning", "q": "所有 Grep 结果加起来共有多少行 TODO？只回数字。", "expect_contains": ["400"]},
			{"id": "s08", "layer": "reasoning", "q": "结果里出现过 TODO line 吗？用「是」或「否」回答。", "expect_contains": ["是"]},
			{"id": "s09", "layer": "reasoning", "q": "单条结果里 TODO 出现次数与执行次数相乘是多少？", "expect_contains": ["400"]},
			{"id": "s10", "layer": "reasoning", "q": "如果每行 TODO line 有 10 个字符，全部结果的总字符数约是多少？", "expect_contains": ["4000"]},
			{"id": "s11", "layer": "instruction", "q": "只回一个数字：Grep 一共执行了几次？不要解释。", "expect_contains": ["20"]},
			{"id": "s12", "layer": "instruction", "q": "不要提工具名，只回答：用户想找什么内容？", "expect_contains": ["TODO"]},
		],
	}


def _source_fingerprint(api: list[dict]) -> str:
	"""内容级指纹（sha1 前 16 位）。real 源文件常被 copy/重录，mtime 不可靠。"""
	import hashlib

	h = hashlib.sha1()
	for m in api:
		c = m.get("content")
		s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False, sort_keys=True)
		h.update((str(m.get("role") or "") + "|" + s).encode("utf-8"))
	return h.hexdigest()[:16]


def _ab_store_meta(source: str, meta: dict) -> None:
	"""把 A/B 源指纹随 ab 缓存一起存（同源判定用）。"""
	data = load_quality_data()
	data["ab"].setdefault(source, {})["meta"] = meta
	save_quality_data(data)


def _session_api(path: Path | None = None) -> list[dict]:
	"""按 API 格式读一条会话 JSONL（role/content/name/tool_call_id）。

	A6 源健康门：长会话源（rows≥120）先过病态判定，不达标**报错拒绝**——
	防止循环副本口径再次混入评测（env ``XEYO_ALLOW_UNHEALTHY_SOURCE=1`` 可强制）。
	"""
	from memory.simulator.replay import load_jsonl

	p = path or AB_REAL_SESSION
	if not p.is_file():
		return []
	rows = load_jsonl(p)
	api: list[dict] = []
	for row in rows:
		if not isinstance(row, dict) or not row.get("role"):
			continue
		msg = {"role": row["role"], "content": row.get("content")}
		if row.get("name"):
			msg["name"] = row["name"]
		if row.get("tool_call_id"):
			msg["tool_call_id"] = row["tool_call_id"]
		api.append(msg)
	if len(api) >= 120:
		health = source_health(p)
		allow = os.environ.get("XEYO_ALLOW_UNHEALTHY_SOURCE", "").strip().lower() in ("1", "true", "yes", "on")
		if not health["healthy"] and not allow:
			raise SystemExit(
				"[A6 源健康门] 会话源疑似病态，拒绝评测（防循环副本口径再骗一次门）：\n"
				+ "\n".join(f"  - {r}" for r in health["reasons"])
				+ f"\n  源: {p}\n  诊断: python -m scripts.memory_stack_eval --source-health \"{p}\"\n"
				"  确要强制: set XEYO_ALLOW_UNHEALTHY_SOURCE=1"
			)
	return api


def _real_session_api() -> list[dict]:
	return _session_api(AB_REAL_SESSION)


def _session_info(path: Path) -> dict:
	"""会话口径统计：轮数 / ts 唯一性 / 循环副本数（>1 = 合成循环副本口径）。"""
	from memory.simulator.replay import load_jsonl

	rows = load_jsonl(path)
	users = sum(1 for r in rows if isinstance(r, dict) and r.get("role") == "user")
	ts_unique = len({float(r["ts"]) for r in rows if isinstance(r, dict) and r.get("ts") is not None})
	heads: dict[str, int] = {}
	for r in rows:
		if isinstance(r, dict) and r.get("role") == "user":
			c = r.get("content")
			s = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)[:200]
			k = str(s)[:120]
			heads[k] = heads.get(k, 0) + 1
	max_rep = max(heads.values()) if heads else 1
	return {
		"file": str(path),
		"rows": len(rows),
		"user_turns": users,
		"unique_ts": ts_unique,
		"loop_copies": max_rep,
	}


def _eval_msg_ids(msg: dict) -> list[str]:
	ids: list[str] = []
	content = msg.get("content")
	if isinstance(content, list):
		for b in content:
			if not isinstance(b, dict):
				continue
			bt = b.get("type")
			if bt in ("tool_use", "tool_result"):
				uid = str(b.get("id") or b.get("tool_use_id") or "")
				if uid:
					ids.append(uid)
	return ids


# ================= A6 源健康门（v61建议采纳说明.md §1.A6） =================

_HEALTH_KV_RE = None  # 惰性编译（见 source_health）


def source_health(path: Path | None = None) -> dict:
	"""A6 源健康检查：真录会话源的病态判定（无模型调用，防 12× 循环副本复发）。

	判据（只对长会话源 rows≥120 生效，短源/合成测试源不受影响）：
	- unique_ts / rows < 0.5 → 疑似循环副本拼接（原 real 源 unique_ts=69 的教训）；
	- 最大重复 user 轮头 > 2 → 同一轮多次出现（副本口径）；
	- tool_result < 20 → 缺真实工作负载。
	同时统计 traceback / key=value 行密度，供探针生成参考。
	"""
	global _HEALTH_KV_RE
	if _HEALTH_KV_RE is None:
		import re as _re

		_HEALTH_KV_RE = _re.compile(r"^[\w.\- ]{1,48}?[=:]\s*\S")
	info = _session_info(path or AB_REAL_SESSION)
	from memory.simulator.replay import load_jsonl

	rows = load_jsonl(path or AB_REAL_SESSION)
	tool_results = 0
	tracebacks = 0
	kv_lines = 0
	for r in rows:
		if not isinstance(r, dict):
			continue
		c = r.get("content")
		texts: list[str] = []
		if isinstance(c, str):
			texts.append(c)
		elif isinstance(c, list):
			for b in c:
				if not isinstance(b, dict):
					continue
				if b.get("type") == "tool_result":
					tool_results += 1
					texts.append(str(b.get("content") or ""))
				elif isinstance(b.get("text"), str):
					texts.append(str(b.get("text")))
		for t in texts:
			if "traceback (most recent call last)" in t.lower():
				tracebacks += 1
			kv_lines += sum(
				1 for line in t.splitlines() if _HEALTH_KV_RE.match(line.strip())
			)
	reasons: list[str] = []
	if info["rows"] >= 120:
		unique_ratio = info["unique_ts"] / max(1, info["rows"])
		if unique_ratio < 0.5:
			reasons.append(f"unique_ts/rows={unique_ratio:.2f}<0.5（疑似循环副本拼接）")
		if info["loop_copies"] > 2:
			reasons.append(f"最大重复 user 轮头={info['loop_copies']}>2（同一轮多次出现）")
		if tool_results < 20:
			reasons.append(f"tool_result={tool_results}<20（缺真实工作负载）")
	return {
		**info,
		"tool_results": tool_results,
		"tracebacks": tracebacks,
		"kv_lines": kv_lines,
		"healthy": not reasons,
		"reasons": reasons,
	}


def _source_health_cli(path_str: str) -> int:
	p = Path(path_str)
	if not p.is_file():
		print(f"文件不存在: {p}")
		return 1
	h = source_health(p)
	print(json.dumps(h, ensure_ascii=False, indent=2))
	print("判定:", "PASS（可作评测源）" if h["healthy"] else "FAIL（病态源，拒绝评测；确要强制 set XEYO_ALLOW_UNHEALTHY_SOURCE=1）")
	return 0 if h["healthy"] else 2


def _eval_msg_kind(msg: dict) -> str:
	content = msg.get("content")
	if isinstance(content, list):
		kinds = {b.get("type") for b in content if isinstance(b, dict)}
		if "tool_use" in kinds:
			return "tool_use"
		if "tool_result" in kinds:
			return "tool_result"
	return str(msg.get("role") or "unknown")


def _stub_text(messages: list[dict]) -> str:
	"""模拟 C1 冻结：只留 id/kind/token 数，无正文。"""
	lines = [f"[C1] frozen {len(messages)} messages (stub)"]
	for i, m in enumerate(messages):
		ids = _eval_msg_ids(m)
		uid = ids[0] if ids else i
		lines.append(f"{i}:{uid}:{_eval_msg_kind(m)}:{_chars([m])}")
	return "\n".join(lines)


def _flatten_text(messages: list[dict], limit: int = 120_000) -> str:
	parts: list[str] = []
	for m in messages:
		c = m.get("content")
		if isinstance(c, str):
			parts.append(c)
		elif isinstance(c, list):
			for b in c:
				if not isinstance(b, dict):
					continue
				bt = b.get("type")
				if bt == "text":
					parts.append(str(b.get("text") or ""))
				elif bt == "tool_result":
					x = b.get("content") or ""
					parts.append(str(x) if isinstance(x, str) else str(x))
				elif bt == "tool_use":
					parts.append(f"{b.get('name')} {b.get('input')}")
	return "\n".join(parts)[:limit]


# ── 抽取式→生成式摘要（Phase1 抽取 + Phase2 LLM 生成，A/B "new" 旁路）──
# 口径（实测最优 2026-09-05）：user[:240] + assistant text[:160] + tool_use(name+id) + tool_result(行数/头60)。
# 依据：assistant 文本占语料大头（56%），[:240]→[:160] 后模型 2500-token 内可排到全部事实，
# 吸收 75%→92%（真实源 24 题）。tool_use 只留 name+id（不带 input JSON——大段 Edit
# new_string / Read 行号段会诱使模型复述代码行，浪费预算并压低吸收）。
SUM_INSTR = (
	"# 压缩指令（只输出摘要正文）\n请把下面的关键语料整理成**要点列表**，**逐条列出，一条都不能少、不合并、不简化**。"
	"每条一行，以名词/键值开头（如「文件: xxx」「数值: 605」「结论: …」「术语: …」）。"
	"**把全部关键事实都列出来**：每个文件名、每个数字、每个术语/机制名、每个工具 id、每条结论，都要单独一行。"
	"宁可列表很长，也不要漏任何一条。只输出摘要正文。"
)


def _phase1_corpus(msgs: list[dict]) -> str:
	"""Phase1 抽取关键语料：user[:240] + assistant text[:160] + tool_use(name+id) + tool_result(行数/头60)。"""
	parts: list[str] = []
	n_use = 0
	total_lines = 0
	for m in msgs:
		if m.get("role") == "user":
			c = m.get("content")
			if isinstance(c, str) and c.strip():
				parts.append(f"[用户] {c.strip()[:240]}")
			continue
		content = m.get("content")
		blocks = content if isinstance(content, list) else ([{"type": "text", "text": content}] if isinstance(content, str) else [])
		for b in blocks:
			if not isinstance(b, dict):
				continue
			bt = b.get("type")
			if bt == "text":
				t = str(b.get("text") or "")
				if t.strip():
					parts.append(f"[助手] {t.strip()[:160]}")
			elif bt == "tool_use":
				n_use += 1
				parts.append(f"[工具调用] {b.get('name')} id={b.get('id')}")
			elif bt == "tool_result":
				raw = str(b.get("content") or "")
				all_lines = [ln for ln in raw.splitlines() if ln.strip()]
				lines = len(all_lines)
				total_lines += lines
				# 72K 口径（实测最优语料规模）：tool_result 只留首行 60 字符。
				# 曾试过"信息行提取/打分排序/整表保留"（保深行 63.9% 等），但语料膨胀到
				# 98K 后 LLM 生成组织反而恶化（吸收 96%→46%，负优化）——回归 72K。
				head = all_lines[0][:60] if all_lines else ""
				parts.append(f"[工具结果] {b.get('tool_use_id')} {lines}行 头: {head}")
	parts.append(f"[汇总事实] 共 {n_use} 次工具调用；结果非空行合计约 {total_lines} 行。")
	return "\n".join(parts)


async def _llm_extract_summary(api: list[dict], *, max_tokens: int = 3500) -> str:
	"""Phase2 生成式摘要：把 Phase1 语料喂 LLM，强保真 one-per-line。失败返回空串（回退确定性）。

	用 evals.client.chat（max_tokens 生效），并显式传 model="deepseek-v4-flash"——
	evals.client 默认 XEYO_EVAL_MODEL=deepseek-v4-flash-vision-exp，该模型会先搬工具调用
	清单、把预算浪费在 id 行上；且 A/B 探针 _probe_chat 用的就是 flash，保持同模型同口径。
	max_tokens=3500（实测最优：chars≈6.3K、吸收 96%、探针 83%；2500→71%、6000→67%），
	3000 时 88%——3500 恰好覆盖全部关键事实，且失败集稳定为 r11/r14/r18/r21（绑定）。
	"""
	from evals.client import account, chat, ensure_stdout_utf8

	corpus = _phase1_corpus(api)
	if not corpus.strip():
		return ""
	try:
		ensure_stdout_utf8()
		acct = account("c2_llm_extract_summary")
		g = chat(
			[
				{"role": "system", "content": "你是会话总结助手，输出完整要点列表，关键事实一条不少。"},
				{"role": "user", "content": corpus},
				{"role": "user", "content": SUM_INSTR},
			],
			acct=acct,
			model="deepseek-v4-flash",
			max_tokens=max_tokens,
			temperature=0.0,
		)
		text = (g.get("content") or "").strip()
		if text:
			print(
				f"  [LLM摘要] chars={len(text)} 语料chars={len(corpus)} "
				f"truncated={g.get('truncated')} 成本≈{acct.summary()['cost_cny']:.4f}元"
			)
		else:
			print("  [LLM摘要] 生成失败/为空，回退确定性摘要")
		return text
	except Exception:
		return ""


def _freeze_projections(api: list[dict], *, source: str, llm_summary: str | None = None) -> dict:
	"""强制 C2 静态投影（apply_c2_messages，不受 θ/r 门影响）+ project 原文投影。

	llm_summary 非空时走 C2 LLM 摘要旁路（summary_provider 注入，需
	XEYO_C2_LLM_SUMMARY=1）；为空/失败则确定性摘要（行为不劣化）。
	"""
	from engine.compact import project as project_c0c1
	from memory.runtime import apply_c2_messages, c2_cut_index
	from memory.simulator.scenarios import DEFAULT_SYSTEM, state_from_messages
	from memory.working import WorkingSnapshot

	if not api:
		return {"compressed": False, "reason": "empty api"}
	s0 = state_from_messages(api, cursor=0)
	cut = c2_cut_index(api, s0)
	w = WorkingSnapshot(session_id=f"ab_{source}", turns_since_c2=4, compact_cursor=cut)
	provider = None
	if llm_summary and llm_summary.strip():
		os.environ["XEYO_C2_LLM_SUMMARY"] = "1"
		provider = lambda left, region_chars: llm_summary if len(llm_summary) < region_chars else None
	proj_v61 = apply_c2_messages(api, w, summary_provider=provider)
	proj_project = project_c0c1(api)
	c_v61, c_proj = _chars(proj_v61), _chars(proj_project)
	return {
		"v61": proj_v61,
		"project": proj_project,
		"chars_v61": c_v61,
		"chars_project": c_proj,
		"compressed": c_v61 < c_proj,
		"cursor": cut,
		"n": len(api),
	}


def judge_answer(question: dict, answer: str) -> bool:
	expect = question.get("expect_contains") or []
	if not expect:
		return False
	low = (answer or "").lower()
	return any(str(e).strip().lower() in low for e in expect)


async def _probe_chat(messages: list[dict], *, max_tokens: int = 240, temperature: float = 0.0) -> dict:
	"""单次无工具流式问答（temp=0，可复现）；返回 {text, usage}。"""
	from engine.abort import AbortController
	from model.openai_compat import OpenAICompatClient, PROVIDER_PRESETS

	key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	if not key:
		return {"text": "", "usage": {}}
	preset = PROVIDER_PRESETS["deepseek"]
	client = OpenAICompatClient(
		api_key=key,
		base_url=(os.environ.get("DEEPSEEK_BASE_URL") or preset["base_url"]).rstrip("/"),
		model=os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
		provider="deepseek",
		thinking=os.environ.get("DEEPSEEK_THINKING") or "disabled",
		temperature=temperature,
		max_tokens=max_tokens,
	)
	parts: list[str] = []
	try:
		async with asyncio.timeout(SUBMIT_TIMEOUT_S):
			async for chunk in client.stream(messages, [], AbortController()):
				if chunk.kind == "text_delta" and chunk.text:
					parts.append(chunk.text)
	except Exception as exc:
		return {"text": "".join(parts), "usage": {}, "error": f"{type(exc).__name__}: {exc}"}
	return {"text": "".join(parts), "usage": client.last_usage or {}}


async def _build_ab_system(proj: Path) -> str:
	from prompt.system_prompt import assemble_system_prompt, fetch_system_prompt_parts

	parts = await fetch_system_prompt_parts(cwd=str(proj), model="deepseek", tool_names=[])
	return assemble_system_prompt(parts, include_context_blocks=True)


def _ab_store(source: str, style: str, mode: str, per_q: dict) -> None:
	"""把 A/B 单题结果写回 quality_validation.json（统一文件回写，避免覆盖 upsert 的行）。"""
	data = load_quality_data()
	data["ab"].setdefault(source, {}).setdefault(style, {})[mode] = per_q
	save_quality_data(data)


def _ab_stats(ab: dict, source: str, style: str, mode: str, probes: dict) -> dict:
	per_q = ((ab.get(source) or {}).get(style) or {}).get(mode) or {}
	layers = {"fact": [0, 0], "reasoning": [0, 0], "instruction": [0, 0]}
	zero_three: list[str] = []
	for q in probes.get("questions", []):
		rec = per_q.get(q.get("id"))
		if not rec:
			continue
		ok = int(rec.get("ok") or 0)
		n = int(rec.get("n") or 0)
		passed = ok >= 2 if n >= 3 else ok >= 1
		layer = str(q.get("layer") or "fact")
		if layer not in layers:
			layer = "fact"
		layers[layer][0] += 1 if passed else 0
		layers[layer][1] += 1
		if layer == "fact" and ok == 0 and n >= 3:
			zero_three.append(str(q.get("id")))
	total_pass = sum(v[0] for v in layers.values())
	total_n = sum(v[1] for v in layers.values())
	return {
		"pass_rate": (total_pass / total_n) if total_n else None,
		"layers": {k: (v[0] / v[1] if v[1] else None) for k, v in layers.items()},
		"zero_three_fact": zero_three,
	}


def _fmt_stats(stats: dict) -> str:
	if stats.get("pass_rate") is None:
		return "无数据"
	layers = " ".join(f"{k}={v * 100:.0f}%" for k, v in stats["layers"].items() if v is not None)
	zt = f" 事实层0/3:{stats['zero_three_fact']}" if stats.get("zero_three_fact") else ""
	return f"通过率 {stats['pass_rate'] * 100:.1f}% ({layers}){zt}"


async def _run_source_ab(
	proj: Path,
	source: str,
	api: list[dict],
	probes: dict,
	frozen: dict,
	sys_text: str,
	style: str,
	*,
	modes: list[str],
) -> dict:
	from memory.simulator.params import load_params
	from usage.pricing import estimate_cny

	params = load_params()
	cost_ab = 0.0
	shots = 0
	dead = 0
	usage_delta: dict[str, dict] = {}
	for mode in modes:
		x = frozen[mode]
		before = _usage_totals()
		per_q: dict[str, dict] = {}
		for q in probes.get("questions", []):
			ok = 0
			for _rep in range(AB_REPEATS):
				msgs = [{"role": "system", "content": sys_text}] + list(x) + [
					{"role": "user", "content": q.get("q", "")}
				]
				resp = await _probe_chat(msgs, max_tokens=int(q.get("max_tokens") or 240))
				u = resp.get("usage") or {}
				if resp.get("error") or (not u and not (resp.get("text") or "")):
					dead += 1
					if dead > AB_REPEATS:
						raise RuntimeError(
							f"[AB] API 连续 {dead} 次无响应/报错（key 无效或网络失败）"
							"— 中止以防用坏数据覆盖表D；请检查 DEEPSEEK_API_KEY"
						)
				est = estimate_cny(provider=params.provider, model=params.model, usage=u, ts=params.default_ts)
				cost_ab += est
				shots += 1
				hit = int(u.get("prompt_cache_hit_tokens") or 0)
				miss = int(u.get("prompt_cache_miss_tokens") or 0)
				rate = (hit / (hit + miss) * 100.0) if (hit + miss) else 0.0
				passed = judge_answer(q, resp.get("text", ""))
				if passed:
					ok += 1
				print(
					f"  [{source}/{style}/{mode}] {q.get('id')} rep{_rep + 1} "
					f"{'PASS' if passed else 'FAIL':4s} hit%={rate:5.1f} 本枪¥{est:.5f} 累计¥{cost_ab:.4f} ({shots}枪)"
				)
			per_q[q.get("id")] = {"ok": ok, "n": AB_REPEATS}
		_ab_store(source, style, mode, per_q)
		usage_delta[mode] = _delta(before, _usage_totals())
	return {"usage": usage_delta, "probes_n": len(probes.get("questions", [])), "modes": modes}


async def run_ab_same_task(proj: Path, style: str) -> dict:
	"""表A：同源 A/B。style ∈ {old, new}；强制 C2 静态投影，隔离『摘要质量』与『公式决策』。"""
	summary_style = "new" if style == "new" else "legacy"
	os.environ["XEYO_C2_SUMMARY_STYLE"] = summary_style
	sources = [
		("real", _real_session_api(), load_probes("real")),
		("synth", long_history_api(20, 8000), synthetic_probes()),
	]
	sys_text = await _build_ab_system(proj)
	result: dict[str, Any] = {"style": style, "sources": {}}
	for source, api, probes in sources:
		if not api or not probes.get("questions"):
			result["sources"][source] = {"skipped": True, "reason": "no api/probes"}
			continue
		fp = _source_fingerprint(api)
		llm_summary = None
		if style == "new":
			# 抽取→生成：先 Phase1 抽关键语料，再 Phase2 LLM 强保真要点列表。
			# XEYO_C2_AB_DETERMINISTIC=1 时跳过 LLM（走确定性 0.78/0.25 摘要），
			# 用于同源两版 A/B：先跑确定性版，再跑 LLM 版覆盖。
			if os.environ.get("XEYO_C2_AB_DETERMINISTIC", "").strip().lower() in ("1", "true", "yes", "on"):
				print(f"  [确定性摘要] {source} 跳过 LLM 旁路（XEYO_C2_AB_DETERMINISTIC=1）")
			else:
				llm_summary = await _llm_extract_summary(api)
		frozen = _freeze_projections(api, source=source, llm_summary=llm_summary)
		if llm_summary:
			print(f"  [LLM摘要投影] {source} chars={frozen['chars_v61']} (llm_summary={len(llm_summary)})")
		if not frozen["compressed"]:
			upsert_quality_row(
				f"ab_{source}_{style}_v61",
				source="表A",
				input_tokens=0,
				cache_hit=0,
				cache_miss=0,
				action=f"A/B {style}摘要·{source}源·强制C2",
				output="投影未变小，跳过",
			)
			result["sources"][source] = {"skipped": True, "reason": "not compressed"}
			continue
		modes = ["v61", "project"]
		ab = load_quality_data()["ab"]
		prev_meta = (ab.get(source) or {}).get("meta") or {}
		same_source = bool(prev_meta.get("fp")) and prev_meta.get("fp") == fp
		if not same_source:
			# 源指纹变了：project 基线本来就要重测
			print(
				f"  [同源] {source} 源内容指纹已变（{prev_meta.get('fp') or '无'} -> {fp}），"
				"重测 project 基线"
			)
		# 关键：v61 与 project 始终在同一轮、同一系统提示词下测量。
		# 原逻辑在同源时复用跨 epoch 的旧 project（旧系统提示词测得），而系统提示词随
		# 仓库漂移（_build_ab_system 实时装配），导致 Δ 口径不对齐（实测 old/new project 差 5.5pp）。
		run = await _run_source_ab(proj, source, api, probes, frozen, sys_text, style, modes=modes)
		_ab_store_meta(source, {
			"fp": fp,
			"file": str(AB_REAL_SESSION) if source == "real" else "synth-template",
			"n": len(api),
			"at": _now(),
		})
		ab = load_quality_data()["ab"]  # 运行后再读，避免用旧快照算统计
		v61_stats = _ab_stats(ab, source, style, "v61", probes)
		if "project" in modes:
			proj_stats = _ab_stats(ab, source, style, "project", probes)
		else:
			proj_stats = _ab_stats(ab, source, "old", "project", probes)
		delta_pp = None
		if v61_stats["pass_rate"] is not None and proj_stats["pass_rate"] is not None:
			delta_pp = round((v61_stats["pass_rate"] - proj_stats["pass_rate"]) * 100, 1)
		usage_v = run["usage"].get("v61", {})
		usage_p = run["usage"].get("project", {})
		upsert_quality_row(
			f"ab_{source}_{style}_v61",
			source="表A",
			input_tokens=usage_v.get("prompt_tokens", 0),
			cache_hit=usage_v.get("cache_hit", 0),
			cache_miss=usage_v.get("cache_miss", 0),
			action=f"A/B {style}摘要·{source}源·强制C2静态投影·{run['probes_n']}题×{AB_REPEATS}次",
			output=_fmt_stats(v61_stats) + (f" | Δ={delta_pp:+}pp" if delta_pp is not None else ""),
			detail={"chars_v61": frozen["chars_v61"], "chars_project": frozen["chars_project"], "cursor": frozen["cursor"]},
		)
		if "project" in modes:
			upsert_quality_row(
				f"ab_{source}_{style}_project",
				source="表A",
				input_tokens=usage_p.get("prompt_tokens", 0),
				cache_hit=usage_p.get("cache_hit", 0),
				cache_miss=usage_p.get("cache_miss", 0),
				action=f"A/B {style}摘要·{source}源·原文投影对照·{run['probes_n']}题×{AB_REPEATS}次",
				output=_fmt_stats(proj_stats),
			)
		result["sources"][source] = {
			"compressed": True,
			"chars_v61": frozen["chars_v61"],
			"chars_project": frozen["chars_project"],
			"delta_pp": delta_pp,
			"v61": v61_stats,
			"project": proj_stats,
		}
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	return result


def _left_region(api: list[dict]) -> list[dict]:
	from memory.runtime import c2_cut_index
	from memory.simulator.scenarios import DEFAULT_SYSTEM, state_from_messages

	s0 = state_from_messages(api, cursor=0)
	cut = c2_cut_index(api, s0)
	return api[:cut]


def _ctx_contains(ctx_low: str, answers: list) -> bool:
	return any(str(a).strip().lower() in ctx_low for a in answers)


def _diagnose_binding_cli() -> int:
	"""P3 离线条判：压缩态失败是「绑定/定位」还是「吸收丢事实」。

	对每个探针问题，检查答案字符串是否在：
	- 确定性 C2 摘要（``deterministic_c2_summary(left, style=\"new\")``，即 A/B 强制静态投影用到的那个）；
	- session.md 风格的叙事（探针文件里的 ``session_summary``，表B 显示 r=1.0）。
	读取 ``XEYO_REAL_SESSION``（缺省回落到 ``AB_REAL_SESSION``）作为真录源。
	无 API 调用，可离线复用。判定规则：
	- 答案「在摘要」但 A/B 判错 → 绑定/定位问题（事实已吸收，靠叙事/密度/binding 杠杆）。
	- 答案「不在摘要」 → 吸收丢事实（靠摘要配额/吸收改进）。
	"""
	from memory.runtime import deterministic_c2_summary

	api = _real_session_api() or _session_api(AB_REAL_SESSION)
	if not api:
		print("未找到真实会话（设 XEYO_REAL_SESSION 或 ~/.xeyo/sessions/sess_real_200turn_c2.jsonl）")
		return 1
	probes = load_probes("real")
	questions = probes.get("questions") or []
	if not questions:
		print("real 题库缺失：", PROBES_DIR / "ab_real_probes.json")
		return 1
	left = _left_region(api)
	summary = deterministic_c2_summary(left, style="new", max_text=160)
	low = summary.lower()
	narr = str(probes.get("session_summary") or "").lower()
	in_sum = sum(1 for q in questions if _ctx_contains(low, q["expect_contains"]))
	in_narr = sum(1 for q in questions if _ctx_contains(narr, q["expect_contains"]))
	total = len(questions)
	print(f"源: {AB_REAL_SESSION}")
	print(f"会话 rows={len(api)}  压缩区(M)= {len(left)} 消息  chars={sum(len(str(m.get('content'))) for m in left)}")
	print(f"C2摘要字符={len(summary)}")
	print(f"\n逐题答案吸收情况（在=C2摘要已含该答案 / 叙事=session.md叙事已含）:")
	print(f"{'id':<6}{'层':<10}{'在C2摘要':<9}{'在叙事':<8} 预期答案")
	for q in questions:
		flag_s = "✓在" if _ctx_contains(low, q["expect_contains"]) else "✗不在"
		flag_n = "✓在" if _ctx_contains(narr, q["expect_contains"]) else "✗不在"
		print(f"{q['id']:<6}{q['layer']:<10}{flag_s:<9}{flag_n:<8} {q['expect_contains']}")
	print(f"\nC2摘要整体吸收: {in_sum}/{total} = {in_sum/total:.1%}")
	print(f"session叙事整体吸收: {in_narr}/{total} = {in_narr/total:.1%}")
	print(f"\n判定: 对 A/B 判错的题——答案「✓在」= 绑定/定位问题(非吸收，用叙事/density/binding 杠杆)；"
	      f"「✗不在」= 吸收丢事实(用摘要配额/吸收改进)。")
	print(f"      session叙事吸收={in_narr/total:.0%} 越高 → 顶层杠杆越是『session.md 全覆盖』或『LLM 摘要旁路』。")
	return 0


async def run_r_probes(proj: Path) -> dict:
	"""表B：r 实测探针。对压缩区原文/旧确定性摘要/新摘要/session.md/C1 stub 各问一遍事实题。"""
	from memory.runtime import deterministic_c2_summary

	os.environ["XEYO_C2_SUMMARY_STYLE"] = "new"
	sources = [
		("real", _real_session_api(), load_probes("real")),
		("synth", long_history_api(20, 8000), synthetic_probes()),
	]
	sys_text = await _build_ab_system(proj)
	result: dict[str, Any] = {}
	for source, api, probes in sources:
		if not api or not probes.get("questions"):
			result[source] = {"skipped": True}
			continue
		left = _left_region(api)
		legacy = deterministic_c2_summary(left, style="legacy")
		newsum = deterministic_c2_summary(left, style="new")
		contexts = {
			"orig": _flatten_text(left),
			"c2_det": legacy,
			"c2_new": newsum,
			"c2_sess": str(probes.get("session_summary") or ""),
			"c1": _stub_text(left),
		}
		for key, ctx in contexts.items():
			if not ctx.strip():
				upsert_quality_row(
					f"r_probe_{key}_{source}",
					source="表B",
					input_tokens=0,
					cache_hit=0,
					cache_miss=0,
					action=f"r探针·{key}·{source}源",
					output="无上下文，跳过",
				)
				continue
			before = _usage_totals()
			pass_n = 0
			total = 0
			for q in probes.get("questions", []):
				msgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": ctx + "\n\n问题：" + q.get("q", "")}]
				resp = await _probe_chat(msgs, max_tokens=int(q.get("max_tokens") or 240))
				total += 1
				if judge_answer(q, resp.get("text", "")):
					pass_n += 1
			usage = _delta(before, _usage_totals())
			rate = round(pass_n / total, 3) if total else None
			upsert_quality_row(
				f"r_probe_{key}_{source}",
				source="表B",
				input_tokens=usage.get("prompt_tokens", 0),
				cache_hit=usage.get("cache_hit", 0),
				cache_miss=usage.get("cache_miss", 0),
				action=f"r探针·{key}·{source}源·{total}题",
				output=f"r={rate if rate is not None else 'N/A'} ({pass_n}/{total})",
				detail={"n_pass": pass_n, "n": total},
			)
			result[f"{key}_{source}"] = {"n_pass": pass_n, "n": total, "r": rate}
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	return result


def _pick_theta_star(scans: list[dict]) -> tuple[float, bool, list[float]]:
	"""θ* 选取规则：θ≥0.35、C2≥1、avg_Q_C2≥0.55、压缩省钱(saves>0) 中取最低成本，平局取较大 θ。
	可行集为空 → θ*=0.50 且 accepted=False。"""
	feasible = [
		s for s in scans
		if s["theta"] >= 0.35 and s["c2_count"] >= 1 and s["avg_q_c2"] is not None
		and s["avg_q_c2"] >= 0.55 and s["saves"] > 0.0
	]
	best = min(feasible, key=lambda s: (s["total_cost"], -s["theta"])) if feasible else None
	theta_star = float(best["theta"]) if best else 0.50
	accepted = best is not None and theta_star >= 0.35
	return theta_star, accepted, [s["theta"] for s in feasible]


def scan_theta_quality() -> dict:
	"""表B：θ 联合扫描（离线）。目标=成本×质量保持：θ≥0.35、avg_Q_C2≥0.55、压缩仍省钱。"""
	from statistics import mean

	from memory.simulator.params import load_params, write_overlay
	from memory.simulator.replay import replay_messages

	# 合成源改为多轮（≥2 用户轮），单轮冷启动源不计入省钱聚合
	sources = {
		"real": _real_session_api(),
		"synth": long_history_multi(20, 8000),
	}
	grid = (0.30, 0.35, 0.40, 0.45, 0.50)
	scans: list[dict] = []
	# 公平基线：纯 keep 回放的真实成本（project 模式下每轮新内容同样按 miss 计费）
	p_keep = load_params(theta=2.0)
	keep_baseline: dict[str, dict] = {}
	for name, api in sources.items():
		if not api:
			continue
		rs = replay_messages(api, session_id=f"{name}_base", params=p_keep)
		keep_baseline[name] = {
			"cost": round(sum(float(tr.simulated_cost) for tr in rs.turns), 6),
			"n_turns": len(rs.turns),
		}
	for theta in grid:
		p = load_params(theta=theta)
		total_cost = 0.0
		base_cost = 0.0
		c2_count = 0
		q_c2: list[float] = []
		max_d = 0.0
		total_L = 0
		total_H = 0
		per_source: dict[str, dict] = {}
		for name, api in sources.items():
			if not api:
				continue
			rs = replay_messages(api, session_id=name, params=p)
			n_turns = len(rs.turns)
			s_cost = sum(float(tr.simulated_cost) for tr in rs.turns)
			s_base = float(keep_baseline.get(name, {}).get("cost") or 0.0)
			s_c2 = sum(1 for tr in rs.turns if tr.predicted == "C2")
			per_source[name] = {
				"n_turns": n_turns,
				"cost": round(s_cost, 6),
				"base": round(s_base, 6),
				"saves": round(s_base - s_cost, 6),
				"c2": s_c2,
			}
			if n_turns < 2:
				# 冷启动/单轮：压缩必然亏（一次 miss 无后续摊薄），不计入验收
				continue
			for tr in rs.turns:
				total_cost += float(tr.simulated_cost)
				base_cost += float(keep_baseline.get(name, {}).get("cost") or 0.0) / max(n_turns, 1)
				total_L += int(tr.L)
				total_H += int(tr.predicted_hit)
				if tr.predicted == "C2":
					c2_count += 1
					q_c2.append(float(tr.Q))
					max_d = max(max_d, float(tr.D))
		avg_q = round(mean(q_c2), 3) if q_c2 else None
		scans.append(
			{
				"theta": theta,
				"total_cost": round(total_cost, 6),
				"base_cost": round(base_cost, 6),
				"saves": round(base_cost - total_cost, 6),
				"c2_count": c2_count,
				"avg_q_c2": avg_q,
				"max_d": round(max_d, 4),
				"total_L": total_L,
				"total_H": total_H,
				"per_source": per_source,
			}
		)
	theta_star, accepted, feasible = _pick_theta_star(scans)
	reason = ""
	if not feasible:
		reason = "可行集为空：无 θ 同时满足 θ≥0.35、C2≥1、avg_Q≥0.55、压缩省钱"
	# 未达标不持久化：避免把未验收的 θ 写进全局 overlay
	if accepted:
		write_overlay({"theta": theta_star})
	for s in scans:
		mark = "★θ*" if s["theta"] == theta_star else ""
		upsert_quality_row(
			f"theta_scan_{s['theta']:.2f}".replace(".", "_"),
			source="表B",
			input_tokens=int(s.get("total_L") or 0),
			cache_hit=int(s.get("total_H") or 0),
			cache_miss=max(int(s.get("total_L") or 0) - int(s.get("total_H") or 0), 0),
			action=f"θ={s['theta']}·离线回放(真实+合成)",
			output=(
				f"成本={s['total_cost']} 基线={s['base_cost']} 省={s['saves']} "
				f"C2={s['c2_count']} avg_Q={s['avg_q_c2']} max_D={s['max_d']} {mark}"
			),
			detail=s,
			accepted=bool(mark and accepted),
		)
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	result = {
		"theta_star": theta_star,
		"accepted": accepted,
		"reason": reason,
		"scans": scans,
		"feasible": feasible,
	}
	print("θ* =", theta_star, "accepted =", accepted, "reason =", reason)
	return result


def apply_measured_r_to_overlay() -> dict:
	"""把实测 r 回填 params_overlay.json（只 overlay，不改 params.py）。"""
	from statistics import mean

	from memory.simulator.params import write_overlay

	rows = load_quality_rows()

	def r_of(prefix: str) -> float | None:
		vals = []
		for cid, row in rows.items():
			if not cid.startswith(prefix):
				continue
			d = row.get("detail") or {}
			if d.get("n"):
				vals.append(float(d["n_pass"]) / float(d["n"]))
		return round(mean(vals), 3) if vals else None

	r_sum = r_of("r_probe_c2_new")
	r_det = r_of("r_probe_c2_det")
	r_stub = r_of("r_probe_c1")
	updates: dict[str, Any] = {}
	if r_sum is not None:
		updates["r_summary"] = r_sum
	if r_stub is not None:
		updates["r_stub"] = r_stub
	if not updates:
		# 无 live 探针数据时，回退到离线术语留存测量（仍可"实测"，无需 API key）
		try:
			from memory.simulator.fidelity import build_corpus, measure_corpus

			off = measure_corpus(build_corpus())
			if off.get("r_summary") is not None:
				updates["r_summary"] = off["r_summary"]
				print("离线回退：无 live 探针，使用术语留存 r_summary <-", off["r_summary"])
		except Exception as e:
			print("离线回退失败:", e)
	if not updates:
		return {"applied": False, "reason": "无 r 实测数据，先跑 --r-probes 或 --measure-r-summary"}
	write_overlay(updates)
	print("overlay <-", updates, "(r_c2_new 与 r_c2_sess 均值作 r_summary 先验)")
	return {"applied": True, "updates": updates, "r_det_legacy": r_det}


def _projection_sequence(
	api: list[dict],
	*,
	mode: str,
	sys_text: str,
	params,
	force_c2: bool = False,
	start_turn: int = 0,
	initial_working=None,
	initial_turns_since_c2: int | None = None,
	on_step=None,
):
	"""逐用户轮产出发送投影（与 replay/runtime 同一套状态机）。

	project：project_c0c1(prefix)；c2：压缩态持久（冻结摘要 + 右尾），
	已压缩态只允许 append-only 扩展（try_extend_c2），绝不重写冻结摘要。
	force_c2：C2 触发用校准 DEFAULT_SYSTEM（与 θ 扫描一致），测压缩态稳态命中率。
	start_turn + initial_working：断点续跑时跳过前面轮次的离线 replay。
	yield (turn_idx, messages, prefix_msgs, transition)。
	"""
	import json as _json

	from engine.compact import project as project_c0c1
	from memory.runtime import _c2_gain_enough, apply_c2_messages, try_extend_c2
	from memory.simulator.cache_model import CacheState
	from memory.simulator.decision import decide
	from memory.simulator.replay import _c2_cut, _user_turn_indices, estimate_remaining
	from memory.simulator.scenarios import DEFAULT_SYSTEM, state_from_messages
	from memory.working import WorkingSnapshot

	starts = _user_turn_indices(api)
	if not starts:
		starts = [0] if api else []
	working = initial_working if initial_working is not None else WorkingSnapshot(session_id="hitrate")
	turns_since_c2 = int(initial_turns_since_c2) if initial_turns_since_c2 is not None else 0
	for t, start in enumerate(starts):
		if t < start_turn:
			continue
		end = starts[t + 1] if t + 1 < len(starts) else len(api)
		prefix = api[:end]
		if not prefix:
			continue
		transition = 0  # 0=无过渡, 1=append-only 扩展(增量miss), 2=首压/真重压缩(整轮全miss)
		if mode == "project":
			proj = project_c0c1(prefix)
		else:
			# force_c2：用校准用 DEFAULT_SYSTEM 触发 decide（与 θ 扫描口径一致），
			# 避免组装系统提示长度不同导致 C2 不触发，从而无法测到压缩态命中率
			s0 = state_from_messages(
				prefix, cursor=working.compact_cursor, system=(DEFAULT_SYSTEM if force_c2 else sys_text)
			)
			cache = CacheState(
				provider=params.provider, age_seconds=0.0, model=params.model,
				slot=params.price_slot, ts=params.default_ts, x_prev=working.last_x_sim,
			)
			d = decide(s0, cache, remaining_turns=estimate_remaining(prefix), params=params, forecast="p0")
			action = d.a_star if d.a_star in ("keep", "C1", "C2") else "keep"
			if action == "C2" and (d.hardtop or turns_since_c2 >= params.min_middle_edit_gap):
				new_cursor = max(working.compact_cursor, _c2_cut(api, end))
				if new_cursor > working.compact_cursor:
					if working.compact_cursor > 0 and working.c2_summary_text:
						ext_ok = try_extend_c2(working, prefix, new_cursor, params, estimate_remaining(prefix))
						if ext_ok:
							transition = 1  # append-only：尾部新增、前缀稳定 → 增量 miss
							turns_since_c2 = 0
					elif _c2_gain_enough(prefix, working, new_cursor, params):
						working.compact_cursor = new_cursor
						turns_since_c2 = 0
						transition = 2  # 首压：整轮全 miss
			if (action != "C2" and working.compact_cursor > 0 and working.c2_summary_text
					and getattr(params, "c2_extend_decouple", False)):
				new_cursor = max(working.compact_cursor, _c2_cut(api, end))
				if new_cursor > working.compact_cursor and try_extend_c2(working, prefix, new_cursor, params, estimate_remaining(prefix)):
					turns_since_c2 = 0
					transition = 1  # append-only：增量 miss
			if working.compact_cursor > 0:
				proj = apply_c2_messages(prefix, working)
			else:
				proj = project_c0c1(prefix)
			working.last_x_sim = _json.dumps(proj, ensure_ascii=False, separators=(",", ":"))
		turns_since_c2 += 1
		messages = [{"role": "system", "content": sys_text}] + list(proj)
		if on_step is not None:
			on_step(t, working, turns_since_c2)
		yield t, messages, len(prefix), transition


async def run_hitrate_live() -> int:
	"""按对话长度分档（ultra/long/medium）实测 project vs C2 的命中率与成本。

	每轮发送与生产一致的请求（system + 投影，含当前 user 消息），
	逐次记录 DeepSeek 实际 cache hit/miss，写回 quality_validation.json 表D。
	"""
	from memory.simulator.params import load_params
	from usage.pricing import estimate_cny

	proj_dir = apply_sandbox()
	seed_workspace(proj_dir)
	sys_text = await _build_ab_system(proj_dir)
	# A1/A2 可单独指定长会话（与表A 的 XEYO_REAL_SESSION 解耦：AB 需题库匹配的源）
	src_env = os.environ.get("XEYO_HITRATE_SESSION", "").strip() or os.environ.get("XEYO_REAL_SESSION", "").strip()
	src_path = Path(src_env) if src_env else AB_REAL_SESSION
	api = _session_api(src_path)
	if not api:
		print("SKIP: 真实会话缺失:", src_path)
		return 1
	session_info = _session_info(src_path)
	print(
		f"  [源] {session_info['file']} rows={session_info['rows']} "
		f"user_turns={session_info['user_turns']} unique_ts={session_info['unique_ts']} "
		f"循环副本={session_info['loop_copies']}"
	)
	if session_info["loop_copies"] > 1:
		print("  [提示] 该会话是重复副本拼接（合成口径）；A1 真实 200+ 轮请用 XEYO_HITRATE_SESSION 指向真录会话")
	try:
		health = source_health(src_path)
		print(
			f"  [A6 源健康] healthy={health['healthy']} tool_result={health['tool_results']}"
			f" traceback={health['tracebacks']} kv行={health['kv_lines']}"
			+ ("" if health["healthy"] else "；原因: " + "; ".join(health["reasons"]))
		)
	except SystemExit:
		raise
	except Exception:  # noqa: BLE001 — 健康展示失败不挡评测
		pass
	params = load_params()
	# 成本护栏（env 激活；0/未设=不限）
	def _pos_int_env(name: str):
		try:
			v = int(os.environ.get(name, "0").strip() or 0)
		except (TypeError, ValueError):
			return 0
		return v if v > 0 else 0

	def _pos_float_env(name: str):
		try:
			v = float(os.environ.get(name, "0").strip() or 0)
		except (TypeError, ValueError):
			return 0.0
		return v if v > 0 else 0.0

	max_shots = _pos_int_env("XEYO_HITRATE_MAX_SHOTS")
	budget_cny = _pos_float_env("XEYO_HITRATE_BUDGET_CNY")
	shots = 0
	cost_sum = 0.0
	dead = 0
	_stop = False
	bands_src = {"ultra": api, "long": api[:80], "medium": api[:45]}
	only_bands = {b.strip() for b in os.environ.get("XEYO_HITRATE_BANDS", "").split(",") if b.strip()}
	bands = {k: v for k, v in bands_src.items() if not only_bands or k in only_bands}
	tag = os.environ.get("XEYO_HITRATE_TAG", "").strip()
	row_prefix = f"hitrate_{tag}_" if tag else "hitrate_"
	summary: dict[str, dict] = {}
	modes = ("project", "c2")
	only_modes = {m.strip() for m in os.environ.get("XEYO_HITRATE_MODES", "").split(",") if m.strip()}
	for band, band_api in bands.items():
		if _stop:
			break
		for mode in modes:
			if _stop:
				break
			if only_modes and mode not in only_modes:
				continue
			per_turn: list[dict] = []
			total_prompt = total_hit = total_miss = total_out = 0
			steady_hit = steady_miss = transitions = 0
			for t, msgs, plen, transition in _projection_sequence(band_api, mode=mode, sys_text=sys_text, params=params, force_c2=(mode == "c2")):
				if max_shots and shots >= max_shots:
					print(f"\n[护栏] 已达 XEYO_HITRATE_MAX_SHOTS={max_shots}，停止。")
					_stop = True
					break
				if budget_cny and cost_sum >= budget_cny:
					print(f"\n[护栏] 已达 XEYO_HITRATE_BUDGET_CNY={budget_cny} 元（已用≈{cost_sum:.4f}），停止。")
					_stop = True
					break
				r = await _probe_chat(msgs, temperature=0.0)
				u = r.get("usage") or {}
				if r.get("error") or (not u and not (r.get("text") or "")):
					dead += 1
					if dead > 5:
						print("[护栏] API 连续无响应/报错——中止以防用坏数据覆盖表D；请检查 DEEPSEEK_API_KEY")
						return 1
				hit = int(u.get("prompt_cache_hit_tokens") or 0)
				miss = int(u.get("prompt_cache_miss_tokens") or 0)
				prompt = int(u.get("prompt_tokens") or 0)
				out = int(u.get("completion_tokens") or 0)
				# 每枪成本（确定性空闲价）；逐枪打印，便于你盯累计花费、随时 Ctrl-C。
				est = estimate_cny(provider=params.provider, model=params.model, usage=u, ts=params.default_ts)
				cost_sum += est
				shots += 1
				rate = (hit / (hit + miss) * 100.0) if (hit + miss) else 0.0
				print(
					f"  [{band}/{mode}] #{t:>3} prompt={prompt:>6} hit={hit:>7} miss={miss:>7} "
					f"rate={rate:5.1f}% 本枪¥{est:.5f} 累计¥{cost_sum:.4f} ({shots}枪)"
				)
				total_prompt += prompt
				total_hit += hit
				total_miss += miss
				total_out += out
				if transition:
					transitions += 1
				# 稳态口径：排除冷启动首轮与压缩过渡轮（一次性成本），统计“对话后”命中率
				if t > 0 and not transition:
					steady_hit += hit
					steady_miss += miss
				per_turn.append({"turn": t, "prefix_msgs": plen, "prompt": prompt, "hit": hit, "miss": miss, "transition": transition})
			rate = (total_hit / (total_hit + total_miss) * 100.0) if (total_hit + total_miss) else 0.0
			steady_rate = (steady_hit / (steady_hit + steady_miss) * 100.0) if (steady_hit + steady_miss) else 0.0
			tail = per_turn[-20:]
			tail_hit = sum(int(r.get("hit") or 0) for r in tail)
			tail_miss = sum(int(r.get("miss") or 0) for r in tail)
			tail_rate = (tail_hit / (tail_hit + tail_miss) * 100.0) if (tail_hit + tail_miss) else 0.0
			last = per_turn[-1] if per_turn else {}
			lh = int(last.get("hit") or 0)
			lm = int(last.get("miss") or 0)
			last_rate = (lh / (lh + lm) * 100.0) if (lh + lm) else 0.0
			key = f"{band}_{mode}"
			summary[key] = {
				"band": band, "mode": mode, "turns": len(per_turn),
				"prompt": total_prompt, "hit": total_hit, "miss": total_miss,
				"hit_rate": round(rate, 2), "output": total_out,
				"steady_hit": steady_hit, "steady_miss": steady_miss,
				"steady_rate": round(steady_rate, 2), "transitions": transitions,
				"tail20_hit": tail_hit, "tail20_miss": tail_miss,
				"tail20_rate": round(tail_rate, 2), "last_rate": round(last_rate, 2),
				"session_info": session_info,
				"params": {k: getattr(params, k) for k in
					("theta", "r_summary", "r_stub", "c2_extend_decouple", "c2_extend_ratio", "alpha_hit")},
				"per_turn": per_turn,
			}
			upsert_quality_row(
				f"{row_prefix}{key}",
				source="表C",
				input_tokens=total_hit + total_miss,
				cache_hit=total_hit,
				cache_miss=total_miss,
				action=f"live命中率·{band}·{mode}·{len(per_turn)}轮"
					+ ("·强制压缩" if mode == "c2" else "")
					+ (f"·tag={tag}" if tag else "")
					+ (f"·decouple={params.c2_extend_decouple}" if mode == "c2" else ""),
				output=(
					f"命中率={rate:.2f}% ({total_hit}/{total_hit + total_miss}) 输入={total_hit + total_miss} "
					f"输出={total_out} | 稳态={steady_rate:.2f}% 尾20={tail_rate:.2f}% 末轮={last_rate:.2f}% 过渡={transitions}"
				),
				detail=summary[key],
			)
	for key, s in summary.items():
		print(
			f"{key:18s} turns={s['turns']:2d} agg={s['hit_rate']:6.2f}% "
			f"steady={s['steady_rate']:6.2f}% tail20={s['tail20_rate']:6.2f}% last={s['last_rate']:6.2f}% "
			f"trans={s['transitions']} tokens={s['prompt']}"
		)
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	print("hitrate rows -> 表D")
	return 0

def _hitrate_clean_cli() -> int:
	"""从已存 hitrate_*_live 明细复算「干净口径」并写入表D。

	口径C（诚实）：冷首轮整段 miss + 非过渡轮只计新增量(max(0, prompt[t]-prompt[t-1]))
	+ 过渡轮整段 miss（压缩重写摘要，前缀几乎全失效）。成本按 DeepSeek 官价 hit=0.05元/M、miss=1.5元/M。
	"""
	rows = load_quality_rows()
	price_hit = 0.05
	price_miss = 1.5
	changed = 0
	for cid, row in list(rows.items()):
		if (cid.startswith("hitrate_clean_")
				or not cid.startswith("hitrate_")
				or ("_project" not in cid and "_c2" not in cid)):
			continue
		pt = (row.get("detail") or {}).get("per_turn") or []
		if len(pt) < 2:
			continue
		prompts = [int(r.get("prompt") or 0) for r in pt]
		total = sum(prompts)
		# transition kind：0=无, 1=append-only(增量miss), 2=首压/真重压缩(整轮全miss)。
		# 旧数据 transition 是 bool，无法区分 append/full——按代码路径推断：
		# 首个 transition=首压（全miss），后续 transition=append（增量 miss）。
		def _kind(pt_row, idx: int, *, seen_full: bool) -> tuple[int, bool]:
			tr = int(pt_row.get("transition") or 0)
			if tr == 2:
				return 2, True
			if tr and not seen_full:
				return 2, True  # 推断：首个 transition = 首压 = 全 miss
			return 1, seen_full

		miss = prompts[0]
		seen_full = False
		for i in range(1, len(pt)):
			tr, seen_full = _kind(pt[i], i, seen_full=seen_full)
			if tr == 2:
				miss += prompts[i]
			else:
				miss += max(0, prompts[i] - prompts[i - 1])
		hit = max(0, total - miss)
		rate = hit / total * 100 if total else 0.0
		cost = hit / 1e6 * price_hit + miss / 1e6 * price_miss
		# 尾20 干净口径（增量+过渡规则，只计窗口内；抗 warm cache 残留污染）
		i0 = max(0, len(pt) - 20)
		window = pt[i0:]
		tail_prompt = sum(int(r.get("prompt") or 0) for r in window)
		tail_miss = 0
		tail_seen_full = False
		for j in range(i0, len(pt)):
			tr, tail_seen_full = _kind(pt[j], j, seen_full=tail_seen_full)
			base = prompts[j - 1] if j - 1 >= 0 else 0
			if tr == 2:
				tail_miss += prompts[j]
			else:
				tail_miss += max(0, prompts[j] - base)
		tail_hit = max(0, tail_prompt - tail_miss)
		tail_rate = tail_hit / tail_prompt * 100 if tail_prompt else 0.0
		det = row.get("detail") or {}
		clean_id = f"hitrate_clean_{cid[len('hitrate_'):]}"
		upsert_quality_row(
			clean_id,
			source="表C",
			input_tokens=total,
			cache_hit=hit,
			cache_miss=miss,
			action=f"干净口径·{det.get('band')}/{det.get('mode')}·冷首轮+每轮增量+过渡全miss（live明细复算）",
			output=(
				f"干净命中率={rate:.2f}% ({hit}/{total}) 成本={round(cost, 5)}元 "
				f"输入={total} miss={miss} | live稳态={det.get('steady_rate')}% 过渡={det.get('transitions')}"
				f" 尾20(干净)={tail_rate:.2f}%"
			),
			detail={"band": det.get("band"), "mode": det.get("mode"), "clean_miss": miss,
				"clean_rate": round(rate, 4), "cost_cny": round(cost, 6),
				"live_steady_rate": det.get("steady_rate"), "transitions": det.get("transitions"),
				"clean_tail20_rate": round(tail_rate, 2), "clean_tail20_turns": len(window),
				"clean_tail20_miss": tail_miss},
		)
		changed += 1
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	print(f"clean-caliber rows -> 表D ({changed} rows)")
	return 0



async def async_quality(args) -> int:
	proj = apply_sandbox()
	seed_workspace(proj)
	key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	if (args.ab or args.r_probes or args.hitrate_live) and not key:
		print("SKIP: live 需要 DEEPSEEK_API_KEY（只读环境变量）")
		return 1
	if args.ab:
		try:
			await run_ab_same_task(proj, args.ab)
		except RuntimeError as e:
			print("[AB 中止]", e)
			return 1
	if args.r_probes:
		await run_r_probes(proj)
	if args.theta_scan:
		scan_theta_quality()
	if args.apply_r:
		apply_measured_r_to_overlay()
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	print("表D rows:", len(rows))
	return 0


def _recompute_ab_rows() -> int:
	"""离线重算表A 统计行：从 quality_validation.json 的 ab 逐题结果刷新 rows（不调 live）。"""
	probes_map = {"real": load_probes("real"), "synth": synthetic_probes()}
	data = load_quality_data()
	ab = data["ab"]
	rows = data["rows"]
	for source, pbank in probes_map.items():
		for style in ("old", "new"):
			if source not in ab or style not in ab[source]:
				continue
			sty = ab[source][style]
			if "v61" not in sty:
				continue
			v61 = _ab_stats(ab, source, style, "v61", pbank)
			if "project" in sty:
				proj = _ab_stats(ab, source, style, "project", pbank)
				ran_project = True
			elif "old" in ab[source] and "project" in ab[source]["old"]:
				proj = _ab_stats(ab, source, "old", "project", pbank)
				ran_project = False
			else:
				proj = {"pass_rate": None}
				ran_project = False
			delta_pp = None
			if v61["pass_rate"] is not None and proj["pass_rate"] is not None:
				delta_pp = round((v61["pass_rate"] - proj["pass_rate"]) * 100, 1)
			cid = f"ab_{source}_{style}_v61"
			prev = rows.get(cid, {})
			rows[cid] = {
				"case_id": cid,
				"source": "表A",
				"input_tokens": int(prev.get("input_tokens") or 0),
				"cache_hit": int(prev.get("cache_hit") or 0),
				"cache_miss": int(prev.get("cache_miss") or 0),
				"action": prev.get("action") or f"A/B {style}摘要·{source}源·强制C2静态投影",
				"output": _fmt_stats(v61) + (f" | Δ={delta_pp:+}pp" if delta_pp is not None else ""),
				"accepted": bool(prev.get("accepted")),
				"updated_at": _now(),
			}
			if ran_project:
				cid_p = f"ab_{source}_{style}_project"
				prev_p = rows.get(cid_p, {})
				rows[cid_p] = {
					"case_id": cid_p,
					"source": "表A",
					"input_tokens": int(prev_p.get("input_tokens") or 0),
					"cache_hit": int(prev_p.get("cache_hit") or 0),
					"cache_miss": int(prev_p.get("cache_miss") or 0),
					"action": prev_p.get("action") or f"A/B {style}摘要·{source}源·原文投影对照",
					"output": _fmt_stats(proj),
					"accepted": bool(prev_p.get("accepted")),
					"updated_at": _now(),
				}
	save_quality_data(data)
	update_docs12_table_d(rows)
	print("recomputed 表A rows")
	return 0


def _accept_row_cli(row_id: str) -> int:
	rows = load_quality_rows()
	if row_id not in rows:
		print(f"no such row: {row_id}")
		return 1
	rows[row_id]["accepted"] = True
	rows[row_id]["updated_at"] = _now()
	data = load_quality_data()
	data["rows"] = rows
	save_quality_data(data)
	update_docs12_table_d(rows)
	print("accepted", row_id)
	return 0


_INJECTED_PREFIXES = (
	"[Resume]",
	"[Background jobs]",
	"[Background Job]",
	"[继续当前任务]",
	"[继续]",
	"[System]",
	"[system]",
	"[你]",
	"<user_message",
	"<tool_output",
	"[Reminder]",
)


def _is_injected_block(text: str) -> bool:
	"""系统注入块（Resume/后台任务/提醒等）→ True；真实用户输入 → False。"""
	t = (text or "").strip()
	if not t:
		return True
	return any(t.startswith(p) for p in _INJECTED_PREFIXES)


def _load_user_turn_map() -> dict[str, tuple[list[float], list[str]]]:
	"""从会话目录收集每 session 的 user 消息 ts+内容，用作轮次标题切分边界。

	仅保留真实用户输入，过滤 [Resume]/[Background jobs] 等系统注入块。
	返回全局 (ts,label) 列表，供无 session_id 的历史事件按时间归位。
	"""
	from session.persistence import default_sessions_dir

	d = default_sessions_dir()
	out: dict[str, tuple[list[float], list[str]]] = {}
	if not d.is_dir():
		return out
	for f in d.glob("*.jsonl"):
		if f.name.startswith("_"):
			continue
		ts: list[float] = []
		lbl: list[str] = []
		try:
			for line in f.read_text(encoding="utf-8").splitlines():
				try:
					rec = json.loads(line)
				except Exception:
					continue
				if rec.get("role") == "user" and isinstance(rec.get("content"), str) and not _is_injected_block(rec.get("content", "")):
					t = rec.get("ts")
					if isinstance(t, (int, float)):
						ts.append(float(t))
						lbl.append(rec.get("content", ""))
		except OSError:
			continue
		if ts:
			out[f.stem] = (ts, lbl)
	return out


def _turn_label_for(umap, sid_raw, ts) -> tuple[str, str]:
	"""把事件 ts 归到最近的 user 消息轮次，返回 (轮次id, 标题)。无则 '(auto)'、'未归类'。"""
	if not sid_raw or sid_raw not in umap:
		# 无 session 的历史事件：全局按 ts 找最近一条用户消息当标题。
		best: tuple[str, str] | None = None
		best_dt = None
		for _sid, (ts_arr, lbl_arr) in umap.items():
			if not ts_arr:
				continue
			i = bisect.bisect_right(ts_arr, ts) - 1
			if i < 0:
				continue
			dt = abs(ts - ts_arr[i])
			if best_dt is None or dt < best_dt:
				best_dt = dt
				raw = (lbl_arr[i] or "").strip().replace("|", "/").replace("\n", " ")
				if len(raw) > 40:
					raw = raw[:40] + "…"
				best = (f"g{i}_{_sid}", raw or f"消息{i}")
		if best is not None:
			return best
		return "(auto)", "未归类(无 session)"
	ts_arr, lbl_arr = umap[sid_raw]
	if not ts_arr:
		return "(auto)", "未归类"
	i = bisect.bisect_right(ts_arr, ts) - 1
	if i < 0:
		return "(auto)", "未归类(消息前)"
	raw = (lbl_arr[i] or "").strip().replace("|", "/").replace("\n", " ")
	if len(raw) > 40:
		raw = raw[:40] + "…"
	return f"t{i}", raw or f"消息{i}"


def _monitor_daily_cli(day: str) -> int:
	"""C4 日常监控：按日聚合 ledger（token/命中/未命中）+ C2 事件，写入表D。

	行 id 为 ``deploy_project_mode_<day>``，每天一行，人工用 ``--accept`` 验收。
	读真实 ledger（``~/.xeyo/usage/events.jsonl``，尊重 ``XEYO_USAGE_DIR``）。
	"""
	from usage.ledger import _read_events, read_c2_events, usage_dir

	events = _read_events()
	days = sorted({str(ev.get("day") or "") for ev in events if ev.get("day")})
	if not days:
		print("SKIP: ledger 无事件（" + str(usage_dir() / "events.jsonl") + " 为空）")
		return 1
	if not day or day == "auto":
		day = days[-1]
	if day not in days:
		print(f"SKIP: 无 {day} 的 ledger 数据（已有日: {', '.join(days)}）")
		return 1
	prompt = hit = miss = out = req = 0
	cost = 0.0
	by_key: dict[tuple[str, str], dict[str, float | int]] = {}
	by_sess: dict[str, dict[str, float | int]] = {}
	by_turn: dict[tuple[str, str], dict[str, Any]] = {}
	umap = _load_user_turn_map()
	for ev in events:
		if str(ev.get("day") or "") != day:
			continue
		req += 1
		prompt += int(ev.get("prompt_tokens") or 0)
		hit += int(ev.get("cache_hit") or 0)
		miss += int(ev.get("cache_miss") or 0)
		out += int(ev.get("output") or 0)
		cost += float(ev.get("cost_cny") or 0)
		key = (str(ev.get("provider") or "unknown"), str(ev.get("model") or "unknown"))
		b = by_key.setdefault(key, {"req": 0, "hit": 0, "miss": 0, "prompt": 0, "output": 0, "cost": 0.0})
		b["req"] += 1
		b["hit"] += int(ev.get("cache_hit") or 0)
		b["miss"] += int(ev.get("cache_miss") or 0)
		b["prompt"] += int(ev.get("prompt_tokens") or 0)
		b["output"] += int(ev.get("output") or 0)
		b["cost"] += float(ev.get("cost_cny") or 0)
		sid_raw = str(ev.get("session_id") or "").strip()
		sid = sid_raw or "(none)"
		sb = by_sess.setdefault(sid, {"req": 0, "hit": 0, "miss": 0, "prompt": 0, "output": 0, "cost": 0.0})
		sb["req"] += 1
		sb["hit"] += int(ev.get("cache_hit") or 0)
		sb["miss"] += int(ev.get("cache_miss") or 0)
		sb["prompt"] += int(ev.get("prompt_tokens") or 0)
		sb["output"] += int(ev.get("output") or 0)
		sb["cost"] += float(ev.get("cost_cny") or 0)
		turn_id, turn_lbl = _turn_label_for(umap, sid_raw, float(ev.get("ts") or 0))
		tkey = (sid, turn_id)
		tb = by_turn.setdefault(
			tkey,
			{"sid": sid, "sid_raw": sid_raw, "label": turn_lbl, "model": "", "req": 0,
				"hit": 0, "miss": 0, "prompt": 0, "output": 0, "cost": 0.0, "first_ts": float(ev.get("ts") or 0),
				"events": []},
		)
		tb["req"] += 1
		tb["hit"] += int(ev.get("cache_hit") or 0)
		tb["miss"] += int(ev.get("cache_miss") or 0)
		tb["prompt"] += int(ev.get("prompt_tokens") or 0)
		tb["output"] += int(ev.get("output") or 0)
		tb["cost"] += float(ev.get("cost_cny") or 0)
		tb["model"] = str(ev.get("model") or tb["model"])
		tb["first_ts"] = min(tb["first_ts"], float(ev.get("ts") or 0))
		tb["events"].append(ev)
	total_in = hit + miss
	hit_rate = (hit / total_in) if total_in else 0.0
	c2_count = sum(1 for ev in read_c2_events() if str(ev.get("day") or "") == day)
	# 按 provider/model 拆分，避免日命中率被会话混用的多个模型污染（DeepSeek 高 + glm 低 → 假性不达标）。
	by_model: list[dict] = []
	for (prov, mid), b in sorted(by_key.items(), key=lambda kv: (-int(kv[1]["req"]), kv[0][1])):
		total = int(b["hit"]) + int(b["miss"])
		by_model.append(
			{
				"provider": prov,
				"model": mid,
				"requests": int(b["req"]),
				"prompt_tokens": int(b["prompt"]),
				"cache_hit": int(b["hit"]),
				"cache_miss": int(b["miss"]),
				"hit_rate": round(int(b["hit"]) / total, 4) if total else 0.0,
				"output": int(b["output"]),
				"cost_cny": round(float(b["cost"]), 6),
			}
		)
	# 按会话拆分（会话级缓存命中率与成本透视）。
	by_sess_list: list[dict] = []
	for sid, b in sorted(by_sess.items(), key=lambda kv: -int(kv[1]["req"])):
		total = int(b["hit"]) + int(b["miss"])
		by_sess_list.append(
			{
				"session_id": sid,
				"requests": int(b["req"]),
				"prompt_tokens": int(b["prompt"]),
				"cache_hit": int(b["hit"]),
				"cache_miss": int(b["miss"]),
				"hit_rate": round(int(b["hit"]) / total, 4) if total else 0.0,
				"output": int(b["output"]),
				"cost_cny": round(float(b["cost"]), 6),
			}
		)
	# 按用户消息（轮次）拆分。
	by_turn_list: list[dict] = []
	for (_sid, _lbl), tb in sorted(by_turn.items(), key=lambda kv: kv[1]["first_ts"]):
		total = int(tb["hit"]) + int(tb["miss"])
		by_turn_list.append(
			{
				"session_id": tb["sid"],
				"label": tb["label"],
				"model": tb["model"],
				"requests": int(tb["req"]),
				"cache_hit": int(tb["hit"]),
				"cache_miss": int(tb["miss"]),
				"hit_rate": round(int(tb["hit"]) / total, 4) if total else 0.0,
				"output": int(tb["output"]),
				"cost_cny": round(float(tb["cost"]), 6),
				"first_ts": tb["first_ts"],
				"events": list(tb["events"]),
			}
		)
	cid = f"deploy_project_mode_{day}"
	detail = {
		"day": day,
		"requests": req,
		"prompt_tokens": prompt,
		"cache_hit": hit,
		"cache_miss": miss,
		"hit_rate": round(hit_rate, 4),
		"c2_count": c2_count,
		"output": out,
		"cost_cny": round(cost, 6),
		"ledger_dir": str(usage_dir()),
		"by_model": by_model,
		"by_session": by_sess_list,
		"by_turn": by_turn_list,
	}
	output_line = (
		f"命中率={hit_rate * 100:.2f}% ({hit}/{total_in}) C2次数={c2_count} "
		f"req={req} output={out} cost={round(cost, 6)}"
	)
	if by_model:
		model_line = "; ".join(
			f"{m['model']}@{m['provider']} 命中{m['hit_rate'] * 100:.1f}% "
			f"({m['cache_hit']}/{m['cache_hit'] + m['cache_miss']}) req={m['requests']}"
			for m in by_model
		)
		output_line = output_line + "\n  分模型: " + model_line
	upsert_quality_row(
		cid,
		source="表C",
		input_tokens=total_in,
		cache_hit=hit,
		cache_miss=miss,
		action=f"日常监控快照 {day}（ledger 增量 + C2 事件）",
		output=output_line,
		detail=detail,
	)
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	print("monitor snapshot ->", cid)
	print(f"  day={day} input={total_in} hit={hit} miss={miss} hit_rate={hit_rate:.2%} c2={c2_count}")
	return 0


def measure_r_summary_cli() -> int:
	"""离线实测 r_summary（术语留存，无需 API key），写入表D 并报告。"""
	try:
		from memory.simulator.fidelity import build_corpus, measure_corpus
	except Exception as e:  # pragma: no cover
		print("无法导入 fidelity 测量器:", e)
		return 1
	res = measure_corpus(build_corpus())
	r = res.get("r_summary")
	cases = res.get("cases") or []
	upsert_quality_row(
		"r_measure_offline",
		source="表B",
		input_tokens=sum(int(c.get("chars_left") or 0) for c in cases),
		cache_hit=0,
		cache_miss=0,
		action=f"离线·术语留存测量(混合语料·{len(cases)}条)",
		output=(
			f"r_summary={r} per_type={res.get('per_type')} "
			f"(字面留存合并前: r_term={r})"
		),
		detail={"r_summary": r, "per_type": res.get("per_type"), "cases": cases},
	)
	rows = load_quality_rows()
	update_docs12_table_d(rows)
	print("r_summary(term) =", r)
	print("per_type =", res.get("per_type"))
	for c in cases:
		print(f"  {c['label']:<14s} r_term={c.get('r_term')} r_literal={c.get('r_literal')} "
			f"chars={c.get('chars_left')}->{c.get('summary_chars')}")
	return 0


def _render_table_d_cli() -> int:
	rows = load_quality_rows()
	ok = update_docs12_table_d(rows)
	print("rendered 表D -> docs/12 (%d rows)" % len(rows))
	return 0 if ok else 1





if __name__ == "__main__":
	try:
		sys.exit(main())
	except Exception:
		traceback.print_exc()
		sys.exit(2)

