"""v6.1 vs compact.project 配对真实 API A/B。

协议：
  - 每个 (场景, 模式) 在 system 最前面加等长唯一盐，避免跨臂共享 KV 前缀。
  - 同一臂内盐不变，第二枪可测本臂命中。
  - 用量来自 DeepSeek stream usage → ledger（官方 hit/miss/output）。
  - 不跑 live probe。

用法（python/ 下）:
  python scripts/formula_live_ab.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

OUT = ROOT / "memory" / "simulator" / "out"
SANDBOX = OUT / "formula_ab_sandbox"
SUBMIT_TIMEOUT_S = 180.0
SALT_WIDTH = 48
REAL_JSONL = Path.home() / ".xeyo" / "sessions" / "sess_msy1p5ev_up68xw.jsonl"


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()


def apply_sandbox() -> Path:
	home = SANDBOX / "xeyo_home"
	os.environ["XEYO_HOME"] = str(home)
	os.environ["XEYO_SESSIONS_DIR"] = str(SANDBOX / "sessions")
	os.environ["XEYO_USAGE_DIR"] = str(SANDBOX / "usage")
	os.environ["XEYO_MEMORY_DIR"] = str(home / "memory")
	os.environ["XEYO_NO_SESSION_PERSISTENCE"] = "0"
	home.mkdir(parents=True, exist_ok=True)
	(SANDBOX / "sessions").mkdir(parents=True, exist_ok=True)
	(SANDBOX / "usage").mkdir(parents=True, exist_ok=True)
	proj = SANDBOX / "proj"
	proj.mkdir(parents=True, exist_ok=True)
	(proj / "README.md").write_text(
		"# eval fixture\nTODO: keep this marker for Grep.\n",
		encoding="utf-8",
	)
	(proj / "app.py").write_text("def main():\n    return 42\n", encoding="utf-8")
	(proj / "XEYO.md").write_text("永远用中文回复。\n", encoding="utf-8")
	return proj


def salt_for(scenario: str, mode: str) -> str:
	raw = f"{scenario}|{mode}|ab"
	if len(raw) > SALT_WIDTH:
		raw = raw[:SALT_WIDTH]
	return raw.ljust(SALT_WIDTH, ".")


def _chars(messages: list[dict]) -> int:
	n = 0
	for m in messages:
		c = m.get("content")
		if isinstance(c, str):
			n += len(c)
		elif isinstance(c, list):
			n += sum(len(json.dumps(b, ensure_ascii=False)) for b in c)
	return n


def _events() -> list[dict]:
	from usage.ledger import _read_events

	return list(_read_events())


def _sum_events(rows: list[dict]) -> dict:
	hit = miss = out = prompt = 0
	cost = 0.0
	sources: list[str] = []
	for ev in rows:
		hit += int(ev.get("cache_hit") or 0)
		miss += int(ev.get("cache_miss") or 0)
		out += int(ev.get("output") or 0)
		prompt += int(ev.get("prompt_tokens") or 0)
		cost += float(ev.get("cost_cny") or 0)
		sources.append(str(ev.get("cost_source") or ""))
	return {
		"requests": len(rows),
		"prompt_tokens": prompt,
		"cache_hit": hit,
		"cache_miss": miss,
		"output": out,
		"cost_cny": round(cost, 6),
		"hit_rate": round(hit / prompt, 6) if prompt else None,
		"cost_source": sources[0] if sources else None,
	}


def formula_snapshot(messages: list[dict], cursor: int = 0) -> dict:
	from memory.simulator.cache_model import CacheState
	from memory.simulator.decision import decide
	from memory.simulator.params import load_params
	from memory.simulator.scenarios import state_from_messages

	p = load_params()
	s0 = state_from_messages(messages, cursor=cursor)
	d = decide(
		s0,
		CacheState(age_seconds=0.0, x_prev=""),
		remaining_turns=8,
		params=p,
		forecast="p0",
	)
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


class SaltedAssembler:
	def __init__(self, salt: str) -> None:
		from prompt.assembler import PromptAssembler

		self._inner = PromptAssembler()
		self._salt = salt

	async def build_system(self, **kwargs):
		body = await self._inner.build_system(**kwargs)
		return f"[eval {self._salt}]\n\n" + body

	def build(self, system: str, history: list[dict]) -> list[dict]:
		return self._inner.build(system, history)


def build_eval_registry(cwd: str):
	from tools.echo import EchoTool
	from tools.fileio.read_state import ReadFileState
	from tools.file_read_tool.file_read_tool import FileReadTool
	from tools.get_time import GetTimeTool
	from tools.glob_tool.glob_tool import GlobTool
	from tools.grep_tool.grep_tool import GrepTool
	from tools.tool_registry import ToolRegistry

	work = os.path.abspath(os.path.expanduser(cwd))
	reg = ToolRegistry(cwd=work)
	read_state = ReadFileState()
	for tool in (
		EchoTool(),
		GetTimeTool(),
		GlobTool(cwd=work),
		GrepTool(cwd=work),
		FileReadTool(cwd=work),
	):
		setter = getattr(tool, "set_read_file_state", None)
		if callable(setter):
			setter(read_state)
		reg.register(tool)
	return reg


def make_engine(*, cwd: str, session_id: str, mode: str, salt: str, max_turns: int = 8, initial=None):
	from engine.query_engine import QueryEngine, QueryEngineConfig
	from model.openai_compat import OpenAICompatClient, PROVIDER_PRESETS

	from memory.memory_switches import save

	save({"XEYO_L5": mode})
	key = (
		os.environ.get("DEEPSEEK_API_KEY", "").strip()
		or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	)
	preset = PROVIDER_PRESETS["deepseek"]
	reg = build_eval_registry(cwd)
	names = ", ".join(reg._tools.keys())
	config: QueryEngineConfig = {
		"cwd": cwd,
		"tools": reg,
		"model_client": OpenAICompatClient(
			api_key=key,
			base_url=(os.environ.get("DEEPSEEK_BASE_URL") or preset["base_url"]).rstrip("/"),
			model=os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
			provider="deepseek",
			thinking=os.environ.get("DEEPSEEK_THINKING") or "disabled",
		),
		"prompt_assembler": SaltedAssembler(salt),  # type: ignore[typeddict-item]
		"append_system_prompt": (
			f"Available tools: {names}. Do not invent tools. Never call Bash or Screenshot."
		),
		"max_turns": max_turns,
		"session_id": session_id,
	}
	if initial:
		config["initial_messages"] = list(initial)
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

	n0 = len(_events())
	tools: list[str] = []
	final_text = ""
	stopped = None
	subtype = None
	num_turns = 0
	t0 = time.perf_counter()
	try:
		async with asyncio.timeout(SUBMIT_TIMEOUT_S):
			async for ev in eng.submit(prompt):
				if isinstance(ev, ToolCallEvent):
					tools.append(ev.name)
				elif isinstance(ev, ToolResultEvent) and ev.is_error:
					pass
				elif isinstance(ev, FinalEvent):
					final_text = (ev.text or "")[:500]
				elif isinstance(ev, StoppedEvent):
					stopped = ev.reason
				elif isinstance(ev, ResultEvent):
					subtype = ev.subtype
					num_turns = ev.num_turns
					if ev.is_error and not final_text:
						final_text = (ev.result or "")[:400]
	except TimeoutError:
		return {"ok": False, "error": "timeout", "tools": tools, "usage": _sum_events(_events()[n0:])}
	except Exception as exc:
		return {
			"ok": False,
			"error": f"{type(exc).__name__}: {exc}",
			"tools": tools,
			"usage": _sum_events(_events()[n0:]),
		}
	working = eng._session.working
	api = eng._session.messages.as_api_messages()
	try:
		snap = formula_snapshot(api, cursor=working.compact_cursor)
	except Exception as exc:
		snap = {"error": str(exc)}
	wcopy = WorkingSnapshot(
		session_id=working.session_id,
		compact_cursor=working.compact_cursor,
		turns_since_c2=working.turns_since_c2,
	)
	proj = project_for_model(api, wcopy)
	base = project_c0c1(api)
	ok = stopped is None and subtype in (None, "success")
	evs = _events()[n0:]
	return {
		"ok": ok,
		"final": final_text,
		"tools": tools,
		"stopped": stopped,
		"result_subtype": subtype,
		"num_turns": num_turns,
		"elapsed_s": round(time.perf_counter() - t0, 3),
		"compact_cursor": working.compact_cursor,
		"formula": snap,
		"proj_chars": _chars(proj),
		"c0c1_chars": _chars(base),
		"events": [
			{
				"prompt_tokens": int(e.get("prompt_tokens") or 0),
				"cache_hit": int(e.get("cache_hit") or 0),
				"cache_miss": int(e.get("cache_miss") or 0),
				"output": int(e.get("output") or 0),
				"cost_cny": float(e.get("cost_cny") or 0),
				"cost_source": e.get("cost_source"),
			}
			for e in evs
		],
		"usage": _sum_events(evs),
	}


def long_history(n_tools: int = 20, blob: int = 8000):
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


def jsonl_to_messages(path: Path):
	from msgtypes.message import Message

	msgs = []
	if not path.is_file():
		return msgs
	for line in path.read_text(encoding="utf-8").splitlines():
		if not line.strip():
			continue
		row = json.loads(line)
		if not isinstance(row, dict):
			continue
		role = row.get("role")
		if role not in ("user", "assistant", "tool"):
			continue
		msgs.append(
			Message(
				role=role,
				content=row.get("content") or "",
				tool_call_id=row.get("tool_call_id"),
				name=row.get("name"),
			)
		)
	return msgs


def _quality(scenario: str, shots: list[dict]) -> dict:
	texts = " ".join((s.get("final") or "") for s in shots)
	ok_run = all(s.get("ok") for s in shots)
	if scenario == "short_kv":
		hit = "17" in texts
	elif scenario == "everyday":
		hit = any(t in texts for t in ("README", "app.py", "TODO"))
	elif scenario == "long_synth":
		hit = "TODO" in texts or "有" in texts
	elif scenario == "long_real":
		low = texts.lower()
		hit = "b148fda" in low or "b148fda" in texts
	else:
		hit = ok_run
	return {"run_ok": ok_run, "answer_ok": bool(hit)}


async def run_arm(*, proj: Path, scenario: str, mode: str, prompts: list[str], initial, max_turns: int) -> dict:
	salt = salt_for(scenario, mode)
	sid = f"ab_{scenario}_{mode}"
	eng = make_engine(
		cwd=str(proj),
		session_id=sid,
		mode=mode,
		salt=salt,
		max_turns=max_turns,
		initial=initial,
	)
	if initial is not None:
		eng._session.working.turns_since_c2 = 4
	shots = []
	for i, prompt in enumerate(prompts, start=1):
		row = await run_submit(eng, prompt)
		row["shot"] = i
		shots.append(row)
		print(
			f"  {scenario}/{mode} shot{i} ok={row.get('ok')} a*={(row.get('formula') or {}).get('a_star')} "
			f"cursor={row.get('compact_cursor')} miss={(row.get('usage') or {}).get('cache_miss')} "
			f"hit={(row.get('usage') or {}).get('cache_hit')} cost={(row.get('usage') or {}).get('cost_cny')}"
		)
		if not row.get("ok"):
			print(f"    err={row.get('error') or row.get('stopped')} final={(row.get('final') or '')[:120]}")
	usage = _sum_events([e for s in shots for e in (s.get("events") or [])])
	return {
		"mode": mode,
		"salt": salt,
		"shots": shots,
		"usage": usage,
		"quality": _quality(scenario, shots),
		"final_cursor": (shots[-1].get("compact_cursor") if shots else 0),
		"final_a_star": ((shots[-1].get("formula") or {}).get("a_star") if shots else None),
		"proj_chars": shots[-1].get("proj_chars") if shots else None,
		"c0c1_chars": shots[-1].get("c0c1_chars") if shots else None,
	}


def _pair(v61: dict, project: dict) -> dict:
	c61 = float((v61.get("usage") or {}).get("cost_cny") or 0)
	c0 = float((project.get("usage") or {}).get("cost_cny") or 0)
	m61 = int((v61.get("usage") or {}).get("cache_miss") or 0)
	m0 = int((project.get("usage") or {}).get("cache_miss") or 0)
	h61 = int((v61.get("usage") or {}).get("cache_hit") or 0)
	h0 = int((project.get("usage") or {}).get("cache_hit") or 0)
	p61 = int((v61.get("usage") or {}).get("prompt_tokens") or 0)
	p0 = int((project.get("usage") or {}).get("prompt_tokens") or 0)
	return {
		"cost_v61": c61,
		"cost_project": c0,
		"cost_delta": round(c61 - c0, 6),
		"savings_frac": round((c0 - c61) / c0, 6) if c0 else None,
		"miss_v61": m61,
		"miss_project": m0,
		"miss_delta": m61 - m0,
		"hit_v61": h61,
		"hit_project": h0,
		"prompt_v61": p61,
		"prompt_project": p0,
		"quality_v61": v61.get("quality"),
		"quality_project": project.get("quality"),
		"a_star_v61": v61.get("final_a_star"),
		"a_star_project": project.get("final_a_star"),
		"cursor_v61": v61.get("final_cursor"),
		"cursor_project": project.get("final_cursor"),
	}


async def main_async() -> int:
	from usage.pricing import is_beijing_peak, unit_prices_cny_per_mtoken

	key = (
		os.environ.get("DEEPSEEK_API_KEY", "").strip()
		or os.environ.get("XEYO_MODEL_API_KEY", "").strip()
	)
	if not key:
		print("missing DEEPSEEK_API_KEY")
		return 2
	if not os.environ.get("DEEPSEEK_API_KEY"):
		os.environ["DEEPSEEK_API_KEY"] = key

	proj = apply_sandbox()
	ts = datetime.now().timestamp()
	peak = is_beijing_peak(ts)
	pr, pu, po, pw = unit_prices_cny_per_mtoken(provider="deepseek", model="deepseek-v4-flash", ts=ts)
	print(f"== formula live A/B peak={peak} prices hit={pr} miss={pu} out={po} W={pw} ==")

	hist_synth = long_history(20, 8000)
	hist_real = jsonl_to_messages(REAL_JSONL)
	print(f"  real jsonl messages={len(hist_real)} from {REAL_JSONL.name}")

	scenarios = [
		{
			"id": "short_kv",
			"max_turns": 3,
			"initial": None,
			"prompts": [
				"记住数字 17。只要回复「已记住」。不要用工具。",
				"我刚才让你记住的数字是几？一句话，不要用工具。",
			],
		},
		{
			"id": "everyday",
			"max_turns": 8,
			"initial": None,
			"prompts": [
				"先 Glob *.md，再 Read README.md。最后一句话总结。不要用别的工具。",
				"README 第一行是什么？不要用工具。",
			],
		},
		{
			"id": "long_synth",
			"max_turns": 6,
			"initial": hist_synth,
			"prompts": [
				"根据已有搜索结果，正文里有没有 TODO？一句话，尽量不用工具。",
				"上一问你的结论是什么？一个字，不要工具。",
			],
		},
		{
			"id": "long_real",
			"max_turns": 4,
			"initial": hist_real,
			"prompts": [
				"最近一次提交短哈希是什么？只回短哈希本身，不要调用任何工具。",
				"那个提交处理了哪个误跟踪文件？只回文件名，不要工具。",
			],
		},
	]

	report: dict = {
		"title": "v6.1 vs project live A/B",
		"generated_at": _now(),
		"probe": "skipped",
		"protocol": (
			"equal-length unique salt prepended to system; "
			"no cross-arm KV; official stream usage"
		),
		"beijing_peak": peak,
		"prices_cny_per_mtoken": {"hit": pr, "miss": pu, "output": po, "write": pw},
		"model": os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash",
		"scenarios": [],
	}

	for sc in scenarios:
		print(f"== {sc['id']} ==")
		arms = {}
		# 先 project 后 v61，即使有泄漏也会不利于 v61；
		# 无论顺序如何，盐值都应防泄漏。
		for mode in ("project", "v61"):
			arms[mode] = await run_arm(
				proj=proj,
				scenario=sc["id"],
				mode=mode,
				prompts=sc["prompts"],
				initial=sc["initial"],
				max_turns=sc["max_turns"],
			)
		pair = _pair(arms["v61"], arms["project"])
		row = {"id": sc["id"], "arms": arms, "pair": pair}
		report["scenarios"].append(row)
		print(
			f"  PAIR {sc['id']} savings={pair['savings_frac']} "
			f"Δcost={pair['cost_delta']} Δmiss={pair['miss_delta']} "
			f"a*={pair['a_star_v61']}/{pair['a_star_project']}"
		)

	totals = {"v61": 0.0, "project": 0.0, "miss_v61": 0, "miss_project": 0}
	for row in report["scenarios"]:
		totals["v61"] += row["pair"]["cost_v61"]
		totals["project"] += row["pair"]["cost_project"]
		totals["miss_v61"] += row["pair"]["miss_v61"]
		totals["miss_project"] += row["pair"]["miss_project"]
	tot_save = (totals["project"] - totals["v61"]) / totals["project"] if totals["project"] else None
	report["totals"] = {
		**{k: (round(v, 6) if isinstance(v, float) else v) for k, v in totals.items()},
		"savings_frac": round(tot_save, 6) if tot_save is not None else None,
	}

	keep_like = [r for r in report["scenarios"] if r["id"] in ("short_kv", "everyday")]
	c2_like = [r for r in report["scenarios"] if r["id"] in ("long_synth", "long_real")]
	def _sum_pair(rows, key):
		return round(sum(r["pair"][key] for r in rows), 6)
	report["by_class"] = {
		"keep_expected": {
			"ids": [r["id"] for r in keep_like],
			"cost_v61": _sum_pair(keep_like, "cost_v61"),
			"cost_project": _sum_pair(keep_like, "cost_project"),
			"miss_v61": sum(r["pair"]["miss_v61"] for r in keep_like),
			"miss_project": sum(r["pair"]["miss_project"] for r in keep_like),
			"savings_frac": round(
				(_sum_pair(keep_like, "cost_project") - _sum_pair(keep_like, "cost_v61"))
				/ max(_sum_pair(keep_like, "cost_project"), 1e-12),
				6,
			),
		},
		"c2_expected": {
			"ids": [r["id"] for r in c2_like],
			"cost_v61": _sum_pair(c2_like, "cost_v61"),
			"cost_project": _sum_pair(c2_like, "cost_project"),
			"miss_v61": sum(r["pair"]["miss_v61"] for r in c2_like),
			"miss_project": sum(r["pair"]["miss_project"] for r in c2_like),
			"savings_frac": round(
				(_sum_pair(c2_like, "cost_project") - _sum_pair(c2_like, "cost_v61"))
				/ max(_sum_pair(c2_like, "cost_project"), 1e-12),
				6,
			),
		},
	}

	OUT.mkdir(parents=True, exist_ok=True)
	path = OUT / "formula_live_ab.json"
	path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
	print("wrote", path)
	print("totals", report["totals"])
	print("by_class", json.dumps(report["by_class"], ensure_ascii=False))
	return 0


def main() -> int:
	return asyncio.run(main_async())


if __name__ == "__main__":
	try:
		sys.exit(main())
	except Exception:
		traceback.print_exc()
		sys.exit(2)
