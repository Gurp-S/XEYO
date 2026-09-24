"""A2 臂子进程入口：在**独立进程**里跑一臂的真实任务。

为什么要有这个文件：设计 §8 明确"基线与候选采用独立进程，隔离环境变量、WSC 内存
状态、session cache 和工具状态；当前 A/B 在进程内修改 ``os.environ`` 的方式不适合
并发自动实验"。因此一臂 = 一个进程，父进程只负责起它、给它隔离过的环境、读它写下
的结果文件。

凭证一律从继承来的环境读，绝不写进 spec 或结果文件。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from contextlib import aclosing
from pathlib import Path
from typing import Any

from diagnostics import store
from diagnostics.identity import _s

WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})


def _usage_from_event(ev: Any) -> dict[str, int] | None:
	"""把引擎的 usage 事件折成 ``usage.pricing.split_usage`` 认得的形状。"""
	if type(ev).__name__ != "UsageEvent" and _s(getattr(ev, "type", "")) != "usage":
		return None
	return {
		"prompt_cache_hit_tokens": int(getattr(ev, "cache_hit_tokens", 0) or 0),
		"prompt_cache_miss_tokens": int(getattr(ev, "cache_miss_tokens", 0) or 0),
		"prompt_tokens": int(getattr(ev, "prompt_tokens", 0) or 0),
		"completion_tokens": int(getattr(ev, "completion_tokens", 0) or 0),
	}


def _accumulate(total: dict[str, int], row: dict[str, int] | None) -> None:
	if not row:
		return
	for key, value in row.items():
		total[key] = int(total.get(key, 0)) + int(value or 0)


async def _drain(engine: Any, task: str, *, deadline: float) -> dict[str, Any]:
	text: list[str] = []
	tool_calls = 0
	tool_errors = 0
	error_signatures: dict[str, int] = {}
	touched: set[str] = set()
	usage: dict[str, int] = {}
	model_requests = 0
	retries = 0
	result_subtype = ""
	num_turns = 0
	async with aclosing(engine.submit(task)) as stream:
		async for ev in stream:
			name = type(ev).__name__
			etype = _s(getattr(ev, "type", ""))
			if etype in ("assistant_delta", "text_delta"):
				text.append(_s(getattr(ev, "text", "")))
			elif name == "ToolCallEvent":
				tool_calls += 1
				tool_name = _s(getattr(ev, "name", ""))
				payload = getattr(ev, "input", None)
				if tool_name in WRITE_TOOLS and isinstance(payload, dict):
					for key in ("file_path", "notebook_path", "path"):
						if _s(payload.get(key)):
							touched.add(_s(payload.get(key)))
			elif name == "ToolResultEvent":
				if bool(getattr(ev, "is_error", False)):
					tool_errors += 1
					signature = f"{_s(getattr(ev, 'name', ''))}|{_s(getattr(ev, 'error_kind', ''))}"
					error_signatures[signature] = error_signatures.get(signature, 0) + 1
			elif name == "UsageEvent":
				model_requests += 1
				_accumulate(usage, _usage_from_event(ev))
			elif name == "FinalEvent":
				if not text and _s(getattr(ev, "text", "")):
					text.append(_s(getattr(ev, "text")))
			elif name == "ResultEvent":
				result_subtype = _s(getattr(ev, "subtype", ""))
				num_turns = int(getattr(ev, "num_turns", 0) or 0)
				if not text and _s(getattr(ev, "result", "")):
					text.append(_s(getattr(ev, "result")))
			if deadline and time.monotonic() > deadline:
				result_subtype = result_subtype or "deadline_exceeded"
				break
	retries = max(0, model_requests - num_turns) if num_turns else 0
	return {
		"reply": "".join(text),
		"tool_calls": tool_calls,
		"tool_errors": tool_errors,
		"repeated_errors": sum(c - 1 for c in error_signatures.values() if c > 1),
		"error_signatures": dict(sorted(error_signatures.items())),
		"touched_paths": sorted(touched)[:200],
		"files_touched": len(touched),
		"usage": usage or None,
		"usage_seen": bool(usage),
		"model_requests": model_requests,
		"retries": retries,
		"turns": num_turns,
		"result_subtype": result_subtype,
	}


def run_arm(spec: dict[str, Any]) -> dict[str, Any]:
	"""在子进程里跑一臂：切到副本 cwd、施加该臂变体环境、跑引擎、返回事实计数。"""
	workspace = _s(spec.get("workspace"))
	if workspace:
		os.chdir(workspace)
	variant_env = {k: v for k, v in dict(spec.get("variant_env") or {}).items() if _s(k)}
	os.environ.update({_s(k): _s(v) for k, v in variant_env.items()})

	from engine.query_engine import build_default_engine

	backend = _s(spec.get("model_backend")) or "fake"
	kwargs: dict[str, Any] = {
		"cwd": workspace or os.getcwd(),
		"session_id": _s(spec.get("session_id")) or f"a2_{_s(spec.get('arm'))}",
		"model_backend": backend,
	}
	if _s(spec.get("max_turns")):
		kwargs["max_turns"] = int(spec["max_turns"])
	if backend != "fake":
		kwargs.update(
			{
				k: v
				for k, v in (
					("model", _s(spec.get("model"))),
					("provider", _s(spec.get("provider"))),
					("base_url", _s(spec.get("base_url"))),
				)
				if v
			}
		)
	deadline = time.monotonic() + float(spec.get("deadline_sec") or 0.0)
	started = time.time()
	error = ""
	counts: dict[str, Any] = {}
	try:
		engine = build_default_engine(**kwargs)
		counts = asyncio.run(_drain(engine, _s(spec.get("task")), deadline=deadline))
	except Exception as exc:  # noqa: BLE001 — 崩溃也要留下事实：这一臂无效但仍占预算
		error = f"{type(exc).__name__}: {exc}"
	reply = _s(counts.get("reply"))
	return {
		"schema": "diagnostics.a2_arm.v1",
		"experiment_id": _s(spec.get("experiment_id")),
		"arm": _s(spec.get("arm")),
		"session_id": _s(kwargs.get("session_id")),
		"workspace": os.getcwd(),
		"variant_env_keys": sorted(variant_env),
		"reply_chars": len(reply),
		"wall_ms": int((time.time() - started) * 1000),
		"error": error,
		"tool_calls": int(counts.get("tool_calls") or 0),
		"tool_errors": int(counts.get("tool_errors") or 0),
		"repeated_errors": int(counts.get("repeated_errors") or 0),
		"error_signatures": dict(counts.get("error_signatures") or {}),
		"files_touched": int(counts.get("files_touched") or 0),
		"touched_paths": list(counts.get("touched_paths") or []),
		"model_requests": int(counts.get("model_requests") or 0),
		"retries": int(counts.get("retries") or 0),
		"turns": int(counts.get("turns") or 0),
		"result_subtype": _s(counts.get("result_subtype")),
		"usage": counts.get("usage"),
		"usage_seen": bool(counts.get("usage_seen")),
		"audit_locator": _s(os.environ.get("XEYO_AUDIT_LOG")),
	}


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(prog="python -m diagnostics.experiments.worker")
	parser.add_argument("--spec", required=True, help="本臂的任务与环境（JSON）")
	args = parser.parse_args(argv)
	spec_path = Path(args.spec)
	try:
		spec = json.loads(spec_path.read_text(encoding="utf-8"))
	except (OSError, ValueError) as exc:
		print(f"spec_unreadable: {exc}", file=sys.stderr)
		return 2
	result = run_arm(spec if isinstance(spec, dict) else {})
	out = Path(_s(spec.get("result_path")) or f"arm-{_s(spec.get('arm'))}.json")
	store.write_json(out, result)
	# 退出码只表达"这一臂有没有跑完"，任务成败由父进程的 verifier 判定。
	return 0 if not result["error"] else 1


if __name__ == "__main__":
	raise SystemExit(main())


__all__ = ["main", "run_arm"]
