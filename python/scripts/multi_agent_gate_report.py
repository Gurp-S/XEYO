#!/usr/bin/env python3
"""Multi-Agent P1 门控报告：读 metrics + journal + usage，产出 28 §7.3/§7.4 建议。

用法：
  python scripts/multi_agent_gate_report.py
  python scripts/multi_agent_gate_report.py --json
  python scripts/multi_agent_gate_report.py --workspace-id xenyon_code_xxx
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _read_jsonl(path: Path) -> list[dict]:
	if not path.is_file():
		return []
	out: list[dict] = []
	with path.open("r", encoding="utf-8", errors="ignore") as handle:
		for line in handle:
			line = line.strip()
			if not line:
				continue
			try:
				out.append(json.loads(line))
			except json.JSONDecodeError:
				continue
	return out


def _journal_path(workspace_id: str) -> Path:
	return Path.home() / ".xeyo" / "journal" / f"{workspace_id}.jsonl"


def _usage_events() -> list[dict]:
	from usage.ledger import _read_events

	return _read_events()


def build_report(*, workspace_id: str | None = None) -> dict:
	from usage.multi_agent_metrics import metrics_path, read_events as read_metrics

	metrics = read_metrics()
	batches = [e for e in metrics if e.get("kind") == "task_batch_end"]
	task_fin = [e for e in metrics if e.get("kind") == "task_finished"]
	write_stale = [e for e in metrics if e.get("kind") == "write_stale"]
	patch_retries = [e for e in metrics if e.get("kind") == "patch_retry"]
	usage_rows = [e for e in metrics if e.get("kind") == "subagent_usage"]
	agent_starts = [e for e in metrics if e.get("kind") == "agent_tool_start"]
	agent_ends = [e for e in metrics if e.get("kind") == "agent_tool_end"]

	conflict_tasks = {e.get("task_id") for e in task_fin if e.get("had_write_stale")}
	total_tasks = len(task_fin) or max(len(batches), 1)
	collision_rate = len(conflict_tasks) / total_tasks if total_tasks else 0.0

	agent_status = Counter(str(e.get("status") or "") for e in agent_ends)
	agent_done = int(agent_status.get("done", 0))
	agent_failed = int(agent_status.get("failed", 0)) + int(
		agent_status.get("cancelled", 0)
	)
	agent_total = len(agent_ends) or 1
	agent_fail_rate = agent_failed / agent_total if agent_ends else None
	durations = [int(e.get("duration_ms") or 0) for e in agent_ends if e.get("duration_ms")]
	avg_agent_ms = (sum(durations) / len(durations)) if durations else None
	agent_ro = sum(1 for e in agent_ends if e.get("read_only"))
	turns = [int(e.get("turns_used") or 0) for e in agent_ends if e.get("turns_used")]
	avg_turns = (sum(turns) / len(turns)) if turns else None

	cache_hit = sum(int(e.get("cache_hit") or 0) for e in usage_rows)
	cache_miss = sum(int(e.get("cache_miss") or 0) for e in usage_rows)
	cache_total = cache_hit + cache_miss
	hit_rate = (cache_hit / cache_total) if cache_total else None

	syntax_bad = 0
	syntax_total = 0
	if workspace_id:
		for row in _read_jsonl(_journal_path(workspace_id)):
			if row.get("action") in ("edit", "write", "stale_reject"):
				syntax_total += 1
				if not row.get("syntax_valid", True):
					syntax_bad += 1
	syntax_error_rate = (syntax_bad / syntax_total) if syntax_total else None

	path_hits: Counter[str] = Counter()
	if workspace_id:
		for row in _read_jsonl(_journal_path(workspace_id)):
			p = str(row.get("path") or "")
			if p:
				path_hits[p] += 1
	recursive_paths = sum(1 for _p, c in path_hits.items() if c >= 2)

	recommendations: list[str] = []
	if agent_fail_rate is not None and agent_fail_rate > 0.25 and len(agent_ends) >= 4:
		recommendations.append(
			f"Agent 工具失败率 {agent_fail_rate:.1%}（含取消）：检查任务描述/scope/并发"
		)
	if collision_rate > 0.15:
		recommendations.append(
			f"碰撞率 {collision_rate:.1%} > 15%：建议加强 write-through store / Patch 重试观测"
		)
	if hit_rate is not None and hit_rate < 0.30:
		recommendations.append(
			f"子 agent input 缓存命中率 {hit_rate:.1%} < 30%：检查 A3 前缀稳定性"
		)
	if syntax_error_rate is not None and syntax_error_rate > 0.20:
		recommendations.append(
			f"语法错误率 {syntax_error_rate:.1%} > 20%：不宜扩大并发，考虑加子 agent 上下文"
		)
	if recursive_paths >= 3 and collision_rate > 0.05:
		recommendations.append(
			f"递归文件率（≥2 次改动路径）={recursive_paths}：可考虑 P2 handoff 交接链"
		)
	if not recommendations:
		recommendations.append("暂无门控告警；继续采集 Agent 工具指标后再评估")

	return {
		"metrics_file": str(metrics_path()),
		"workspace_id": workspace_id,
		"agent_tool_starts": len(agent_starts),
		"agent_tool_ends": len(agent_ends),
		"agent_tool_done": agent_done,
		"agent_tool_failed": agent_failed,
		"agent_tool_fail_rate": (
			round(agent_fail_rate, 4) if agent_fail_rate is not None else None
		),
		"agent_tool_avg_duration_ms": (
			round(avg_agent_ms, 1) if avg_agent_ms is not None else None
		),
		"agent_tool_read_only_ends": agent_ro,
		"agent_tool_avg_turns_used": (
			round(avg_turns, 2) if avg_turns is not None else None
		),
		"task_batches": len(batches),
		"tasks_finished": len(task_fin),
		"collision_rate": round(collision_rate, 4),
		"collision_tasks": len(conflict_tasks),
		"write_stale_events": len(write_stale),
		"patch_retries": len(patch_retries),
		"cache_hit_rate_subagent": round(hit_rate, 4) if hit_rate is not None else None,
		"cache_hit": cache_hit,
		"cache_miss": cache_miss,
		"syntax_error_rate": round(syntax_error_rate, 4) if syntax_error_rate is not None else None,
		"recursive_file_paths": recursive_paths,
		"recommendations": recommendations,
		"ledger_events": len(_usage_events()),
	}


def main() -> int:
	parser = argparse.ArgumentParser(description="Multi-Agent P1 gate report")
	parser.add_argument("--json", action="store_true", help="输出 JSON")
	parser.add_argument("--workspace-id", default="", help="journal workspace id（memdir）")
	args = parser.parse_args()
	wsid = (args.workspace_id or "").strip() or None
	report = build_report(workspace_id=wsid)
	if args.json:
		print(json.dumps(report, ensure_ascii=False, indent=2))
		return 0
	print("# Multi-Agent P1 门控报告\n")
	for key, val in report.items():
		if key == "recommendations":
			continue
		print(f"- **{key}**: {val}")
	print("\n## 建议\n")
	for line in report["recommendations"]:
		print(f"- {line}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
