"""Multi-Agent P1 指标（与计费 ledger 分离）。

写入 ``~/.xeyo/metrics/multi_agent.jsonl``（可用 ``XEYO_METRICS_DIR`` 覆盖）。
供离线门控分析（``scripts/multi_agent_gate_report.py``）与 P1 测量（29 §6）。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def metrics_dir() -> Path:
	override = os.environ.get("XEYO_METRICS_DIR", "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo" / "metrics"


def metrics_path() -> Path:
	return metrics_dir() / "multi_agent.jsonl"


def _append(event: dict[str, Any]) -> None:
	path = metrics_path()
	line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
	with _lock:
		path.parent.mkdir(parents=True, exist_ok=True)
		with path.open("a", encoding="utf-8", newline="") as handle:
			handle.write(line + "\n")


def _base(**fields: Any) -> dict[str, Any]:
	return {"ts": round(time.time(), 3), **fields}


def record(**fields: Any) -> None:
	_append(_base(**fields))


def record_batch_start(
	*,
	task_batch_id: str,
	session_id: str,
	task_count: int,
) -> None:
	record(
		kind="task_batch_start",
		task_batch_id=task_batch_id,
		session_id=session_id,
		task_count=int(task_count),
	)


def record_batch_end(
	*,
	task_batch_id: str,
	session_id: str,
	done: int,
	failed: int,
) -> None:
	record(
		kind="task_batch_end",
		task_batch_id=task_batch_id,
		session_id=session_id,
		done=int(done),
		failed=int(failed),
	)


def record_task_finished(
	*,
	task_batch_id: str,
	session_id: str,
	task_id: str,
	agent_id: str,
	status: str,
	reason: str = "",
	paths: list[str] | None = None,
	patch_attempt: int = 0,
	had_write_stale: bool = False,
) -> None:
	record(
		kind="task_finished",
		task_batch_id=task_batch_id,
		session_id=session_id,
		task_id=task_id,
		agent_id=agent_id,
		status=status,
		reason=(reason or "")[:200],
		paths=list(paths or []),
		patch_attempt=int(patch_attempt),
		had_write_stale=bool(had_write_stale),
	)


def record_patch_retry(
	*,
	task_batch_id: str,
	session_id: str,
	task_id: str,
	agent_id: str,
	attempt: int,
) -> None:
	record(
		kind="patch_retry",
		task_batch_id=task_batch_id,
		session_id=session_id,
		task_id=task_id,
		agent_id=agent_id,
		attempt=int(attempt),
	)


def record_write_stale(
	*,
	agent_id: str,
	path: str,
	session_id: str = "",
	task_batch_id: str = "",
) -> None:
	record(
		kind="write_stale",
		agent_id=agent_id,
		path=path,
		session_id=session_id,
		task_batch_id=task_batch_id,
	)


def record_agent_tool_start(
	*,
	session_id: str,
	agent_id: str,
	task_id: str,
	desc: str = "",
) -> None:
	record(
		kind="agent_tool_start",
		session_id=session_id,
		agent_id=agent_id,
		task_id=task_id,
		desc=(desc or "")[:200],
	)


def record_agent_tool_end(
	*,
	session_id: str,
	agent_id: str,
	task_id: str,
	status: str,
	duration_ms: int = 0,
) -> None:
	record(
		kind="agent_tool_end",
		session_id=session_id,
		agent_id=agent_id,
		task_id=task_id,
		status=status,
		duration_ms=int(duration_ms),
	)


def record_subagent_usage(
	*,
	task_batch_id: str,
	session_id: str,
	agent_id: str,
	task_id: str,
	usage: dict[str, Any],
) -> None:
	if not isinstance(usage, dict) or not usage:
		return
	from usage.pricing import split_usage

	hit, miss, out = split_usage(usage)
	prompt = int(usage.get("prompt_tokens") or 0)
	record(
		kind="subagent_usage",
		task_batch_id=task_batch_id,
		session_id=session_id,
		agent_id=agent_id,
		task_id=task_id,
		prompt_tokens=prompt,
		cache_hit=int(hit),
		cache_miss=int(miss),
		output=int(out),
	)


def record_agent_tool_start(
	*,
	session_id: str,
	agent_id: str,
	task_id: str,
	desc: str = "",
	multi_agent_chip: bool = False,
	read_only: bool = False,
) -> None:
	"""Agent 工具 spawn 起点（工具化路径；非旧 batch 调度）。"""
	record(
		kind="agent_tool_start",
		session_id=session_id or "",
		agent_id=agent_id or "",
		task_id=task_id or "",
		desc=(desc or "")[:160],
		multi_agent_chip=bool(multi_agent_chip),
		read_only=bool(read_only),
	)


def record_agent_tool_end(
	*,
	session_id: str,
	agent_id: str,
	task_id: str,
	status: str,
	duration_ms: int = 0,
	reason: str = "",
	read_only: bool = False,
	turns_used: int = 0,
	max_turns: int = 0,
) -> None:
	"""Agent 工具结束：status ∈ done / failed / cancelled。"""
	record(
		kind="agent_tool_end",
		session_id=session_id or "",
		agent_id=agent_id or "",
		task_id=task_id or "",
		status=(status or "failed")[:32],
		duration_ms=max(0, int(duration_ms)),
		reason=(reason or "")[:200],
		read_only=bool(read_only),
		turns_used=max(0, int(turns_used)),
		max_turns=max(0, int(max_turns)),
	)


def read_events(limit: int = 0) -> list[dict[str, Any]]:
	path = metrics_path()
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	with path.open("r", encoding="utf-8", errors="ignore") as handle:
		for line in handle:
			line = line.strip()
			if not line:
				continue
			try:
				out.append(json.loads(line))
			except json.JSONDecodeError:
				continue
	if limit > 0:
		return out[-limit:]
	return out


__all__ = [
	"metrics_dir",
	"metrics_path",
	"read_events",
	"record",
	"record_agent_tool_end",
	"record_agent_tool_start",
	"record_batch_end",
	"record_batch_start",
	"record_patch_retry",
	"record_subagent_usage",
	"record_task_finished",
	"record_write_stale",
]
