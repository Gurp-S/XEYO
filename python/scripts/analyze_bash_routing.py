"""Bash 专用工具路由 Phase 0 观测分析（docs/设计/43）。

两块数据源，产出同一套指标（T1/T2/T3 分布、目标工具、Top 命令、纠偏）：

A. 实时审计（Phase 0 采集钩子已上线）：读 ``XEYO_AUDIT_LOG`` 或
   ``<XEYO_DATA_DIR|XEYO_HOME|~/.xeyo>/audit/audit.jsonl``，聚合 ``tool.routed_observed``。
   注意：此时的历史 Bash 调用发生在钩子上线前（``tool.started`` 不记命令），
   只能从钩子上线后开始累积——因此历史误用率走 B。

B. 历史 transcript 重放：读 ``~/.xeyo/sessions/*.jsonl``（可 ``XEYO_SESSIONS_DIR`` 覆盖），
   从 assistant 的 tool_use 块取出每条 Bash 实际命令，喂给 ``plan_bash_route`` 判定，
   得到**采集前的真实误用基线**（当时只有软描述、无 L2 重定向）——正好拿来做
   Phase 1 的 before/after 对照。

指标：
- Bash 调用总数、误用命中数、命中率（%）
- 分级分布 T1 / T2 / T3（T1=cat/type/Get-Content/gc, T2=rg/grep/findstr, T3=ls/find）
- 目标工具分布 Read / Grep / Glob；Top 误用命令
- **纠偏**（B：同会话下一次 tool_use；A：同会话下一次 tool.started）：
  - ``correct``：即该为 routed_to（Read/Grep/Glob）
  - ``bash_again``：仍是 Bash（连用 Bash 的重灾区）
  - ``other`` / ``none``：换成别的工具 / 不再有工具调用
  说明：简化口径取"紧邻的下一次工具调用"，不区分并行分区调用。

用法：
  py -3.11 scripts/analyze_bash_routing.py                 # 审计 + transcript 报告
  py -3.11 scripts/analyze_bash_routing.py --json          # JSON
  py -3.11 scripts/analyze_bash_routing.py --no-transcript --since-hours 24
  py -3.11 scripts/analyze_bash_routing.py --sessions-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any
from datetime import datetime
from pathlib import Path


def _audit_path() -> str:
	from audit.log import default_audit_log

	return str(default_audit_log().path)


def _load_rows() -> list[dict[str, Any]]:
	from audit.log import AuditLog

	path = _audit_path()
	if not os.path.isfile(path):
		return []
	return AuditLog(path).read_all()


def _ts(row: dict[str, Any]) -> float:
	try:
		return float(row.get("ts") or 0)
	except (TypeError, ValueError):
		return 0.0


def _fmt(ts: float) -> str:
	try:
		return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
	except Exception:  # noqa: BLE001
		return "-"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
	bash_started = [r for r in rows if r.get("kind") == "tool.started" and r.get("tool_name") == "Bash"]
	observed = [r for r in rows if r.get("kind") == "tool.routed_observed"]

	by_tier = Counter(str(r.get("tier") or "?") for r in observed)
	by_tool = Counter(str(r.get("routed_to") or "?") for r in observed)
	by_cmd = Counter(str(r.get("command") or "").strip() for r in observed if str(r.get("command") or "").strip())
	sessions = {str(r.get("session_id") or "") for r in observed}

	# L2 纠偏有效率：命中后同会话下一次 tool.started
	by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for r in rows:
		sid = str(r.get("session_id") or "")
		if not sid:
			continue
		by_session[sid].append(r)
	for sid in by_session:
		by_session[sid].sort(key=_ts)

	corr: Counter[str] = Counter()
	miss_window_s = 120.0
	for r in observed:
		sid = str(r.get("session_id") or "")
		seq = by_session.get(sid) or []
		ts = _ts(r)
		want = str(r.get("routed_to") or "")
		nxt = None
		for cand in seq:
			if _ts(cand) > ts and cand.get("kind") == "tool.started":
				nxt = cand
				break
		if nxt is None:
			corr["none"] += 1
		elif _ts(nxt) - ts > miss_window_s:
			corr["none"] += 1
		else:
			got = str(nxt.get("tool_name") or "")
			if got == want:
				corr["correct"] += 1
			elif got == "Bash":
				corr["bash_again"] += 1
			else:
				corr["other"] += 1

	base = {
		"audit_path": _audit_path(),
		"range": (
			{"from": _fmt(_ts(rows[0])), "to": _fmt(_ts(rows[-1]))}
			if rows
			else None
		),
		"bash_calls": len(bash_started),
		"observed_hits": len(observed),
		"hit_rate_pct": round(100.0 * len(observed) / len(bash_started), 2) if bash_started else 0.0,
		"obs_sessions": len(sessions),
		"by_tier": {k: by_tier[k] for k in sorted(by_tier)},
		"by_routed_to": {k: by_tool[k] for k in sorted(by_tool)},
		"top_commands": by_cmd.most_common(10),
		"l2_correction": {k: corr.get(k, 0) for k in ("correct", "bash_again", "other", "none")},
		"l2_correct_pct": round(100.0 * corr.get("correct", 0) / len(observed), 1) if observed else 0.0,
		"observed_samples": [
			{"ts": _fmt(_ts(r)), "session": str(r.get("session_id") or "")[:8], "tier": r.get("tier"), "routed_to": r.get("routed_to"), "command": str(r.get("command") or "")[:60]}
			for r in observed[:20]
		],
	}
	return base


def replay_transcripts(sessions_dir: Path | None = None) -> dict[str, Any]:
	"""重放历史 transcript，挖出采集前的真实误用基线（当时仅软描述、无 L2）。"""
	from session.hydrate import messages_from_transcript
	from tools.bash_tool.dup_redirect import plan_bash_route

	if sessions_dir is None:
		from session.persistence import default_sessions_dir

		sessions_dir = default_sessions_dir()
	files = sorted(
		p for p in sessions_dir.glob("*.jsonl") if p.name != "_workspace_index.jsonl"
	)
	if not files:
		return {"sessions_dir": str(sessions_dir), "files": 0, "bash_calls": 0, "observed_hits": 0, "hit_rate_pct": 0.0, "sessions_hit": 0, "by_tier": {}, "by_routed_to": {}, "top_commands": [], "l2_correction": {"correct": 0, "bash_again": 0, "other": 0, "none": 0}, "l2_correct_pct": 0.0, "observed_samples": []}

	bash_calls = 0
	observed = 0
	by_tier: Counter[str] = Counter()
	by_tool: Counter[str] = Counter()
	by_cmd: Counter[str] = Counter()
	corr: Counter[str] = Counter()
	sessions_hit: set[str] = set()
	samples: list[dict[str, Any]] = []

	for fp in files:
		try:
			msgs = messages_from_transcript(fp)
		except Exception:  # noqa: BLE001 — 单文件坏不挡整体
			continue
		sid = fp.stem  # 会话键：sess_<id>_<suffix> 等
		events: list[dict[str, Any]] = []
		for m in msgs:
			if m.role != "assistant" or not isinstance(m.content, list):
				continue
			for b in m.content:
				if isinstance(b, dict) and b.get("type") == "tool_use":
					inp = b.get("input")
					command = str(inp.get("command") or "") if isinstance(inp, dict) else ""
					events.append({"name": str(b.get("name") or ""), "command": command})
		for idx, ev in enumerate(events):
			if ev["name"] != "Bash":
				continue
			bash_calls += 1
			plan = plan_bash_route(ev["command"])
			if plan is None:
				continue
			observed += 1
			by_tier[plan.tier] += 1
			by_tool[plan.tool_name] += 1
			sessions_hit.add(sid)
			cmd = ev["command"].strip()
			if cmd:
				by_cmd[cmd] += 1
			nxt = events[idx + 1] if idx + 1 < len(events) else None
			if nxt is None:
				corr["none"] += 1
			elif nxt["name"] == plan.tool_name:
				corr["correct"] += 1
			elif nxt["name"] == "Bash":
				corr["bash_again"] += 1
			else:
				corr["other"] += 1
			if len(samples) < 20:
				samples.append(
					{
						"session": sid[:24],
						"tier": plan.tier,
						"routed_to": plan.tool_name,
						"command": cmd[:60],
					}
				)

	return {
		"sessions_dir": str(sessions_dir),
		"files": len(files),
		"bash_calls": bash_calls,
		"observed_hits": observed,
		"hit_rate_pct": round(100.0 * observed / bash_calls, 2) if bash_calls else 0.0,
		"sessions_hit": len(sessions_hit),
		"by_tier": {k: by_tier[k] for k in sorted(by_tier)},
		"by_routed_to": {k: by_tool[k] for k in sorted(by_tool)},
		"top_commands": by_cmd.most_common(10),
		"l2_correction": {k: corr.get(k, 0) for k in ("correct", "bash_again", "other", "none")},
		"l2_correct_pct": round(100.0 * corr.get("correct", 0) / observed, 1) if observed else 0.0,
		"observed_samples": samples,
	}


def main(argv: list[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description="Phase 0 Bash 路由观测分析")
	ap.add_argument("--json", action="store_true", help="输出 JSON")
	ap.add_argument("--since-hours", type=float, default=None, help="仅统计最近 N 小时（审计）")
	ap.add_argument("--no-transcript", action="store_true", help="跳过历史 transcript 重放")
	ap.add_argument("--sessions-dir", default=None, help="transcript 目录覆盖（默认 ~/.xeyo/sessions）")
	args = ap.parse_args(argv)

	rows = _load_rows()
	if args.since_hours is not None:
		cutoff = datetime.now().timestamp() - args.since_hours * 3600
		rows = [r for r in rows if _ts(r) >= cutoff]

	if not rows and args.no_transcript:
		print("审计文件为空或不存在。Phase 0 采集已上线，真实会话使用 XEYO 时自动写入 tool.routed_observed。")
		return 0

	out: dict[str, Any] = {}
	if rows:
		out["audit"] = summarize(rows)
	else:
		out["audit"] = {"note": "审计文件为空或不存在——钩子上线后的实时数据在此累积"}

	if not args.no_transcript:
		out["transcript"] = replay_transcripts(
			Path(args.sessions_dir) if args.sessions_dir else None
		)

	if args.json:
		print(json.dumps(out, ensure_ascii=False, indent=2))
	else:
		print("== 实时审计（Phase 0 采集钩子上线后） ==")
		print(render_audit(out["audit"]))
		if "transcript" in out:
			print("\n== 历史 transcript 重放（采集前基线：仅软描述、无 L2） ==")
			print(render_transcript(out["transcript"]))
	return 0


def render_transcript(s: dict[str, Any]) -> str:
	lines: list[str] = []
	lines.append(f"transcript 目录: {s['sessions_dir']}（{s['files']} 个会话文件）")
	lines.append(
		f"Bash 调用 {s['bash_calls']} | 误用命中 {s['observed_hits']} "
		f"(命中率 {s['hit_rate_pct']}%) | 命中会话 {s['sessions_hit']}"
	)
	lines.append(f"分级分布: {s['by_tier']}")
	lines.append(f"目标工具: {s['by_routed_to']}")
	if s["top_commands"]:
		lines.append("Top 命令:")
		for cmd, n in s["top_commands"]:
			lines.append(f"  {n:>3}  {cmd}")
	c = s["l2_correction"]
	lines.append(
		f"后续纠偏: 正确工具={c['correct']}({s['l2_correct_pct']}%), "
		f"仍Bash={c['bash_again']}, 其他工具={c['other']}, 无后续={c['none']}"
	)
	if s["observed_samples"]:
		lines.append("命中采样:")
		for x in s["observed_samples"]:
			lines.append(f"  [{x['tier']}→{x['routed_to']}] {x['session']}  {x['command']}")
	return "\n".join(lines)


def render_audit(s: dict[str, Any]) -> str:
	if s.get("note"):
		return s["note"]
	lines: list[str] = []
	lines.append(f"审计文件: {s['audit_path']}")
	rg = s.get("range")
	if rg:
		lines.append(f"时间范围: {rg['from']} → {rg['to']}")
	lines.append(
		f"Bash 调用 {s['bash_calls']} | 误用命中 {s['observed_hits']} "
		f"(命中率 {s['hit_rate_pct']}%) | 命中会话 {s['obs_sessions']}"
	)
	lines.append(f"分级分布: {s['by_tier']}")
	lines.append(f"目标工具: {s['by_routed_to']}")
	c = s["l2_correction"]
	lines.append(f"L2 纠偏有效率: {s['l2_correct_pct']}% (correct={c['correct']}, bash_again={c['bash_again']}, other={c['other']}, none={c['none']})")
	return "\n".join(lines)


if __name__ == "__main__":
	sys.exit(main())
