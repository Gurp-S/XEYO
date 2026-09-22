"""Deterministic XEYO long-task control evidence benchmark.

This benchmark exercises the existing QueryEngine budget path and LoopBreaker
directly.  It does not change production code or existing tests.  The result is
written to ``benchmarks/resume_evidence/results/`` so the resume numbers can be
reproduced from a committed script.

Run from the repository root:

    py -3.11 benchmarks/resume_evidence/xeyo_long_task_control.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from engine.abort import AbortController
from engine.budget import BudgetTracker
from engine.loop_breaker import LoopBreaker
from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import (
    ResultEvent,
    StoppedEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)
from msgtypes.message import ToolUse
from tools.echo.echo_tool import EchoTool
from tools.tool_registry import ToolRegistry
from usage import pricing


PIN = {"input_miss": 2.0, "input_hit": 0.2, "output": 8.0}
OFFPEAK_TS = datetime(2026, 8, 16, 19, tzinfo=timezone.utc).timestamp()


class EndTurnModel:
    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        abort: AbortController,
    ) -> AsyncIterator[ModelChunk]:
        abort.raise_if_aborted()
        yield ModelChunk(kind="text_delta", text="done")


class AlwaysToolModel:
    def __init__(self, usage: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.usage = dict(usage or {})
        self.last_usage: dict[str, Any] | None = None

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        abort: AbortController,
    ) -> AsyncIterator[ModelChunk]:
        abort.raise_if_aborted()
        self.calls += 1
        if self.usage:
            self.last_usage = dict(self.usage)
        yield ModelChunk(
            kind="tool_use",
            tool_use=ToolUse(
                id=f"call_{self.calls}_{uuid4().hex[:8]}",
                name="echo",
                input={"text": "loop"},
            ),
        )


class MultiToolThenTextModel:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        abort: AbortController,
    ) -> AsyncIterator[ModelChunk]:
        abort.raise_if_aborted()
        self.calls += 1
        if self.calls == 1:
            for text in ("one", "two"):
                yield ModelChunk(
                    kind="tool_use",
                    tool_use=ToolUse(
                        id=f"call_{self.calls}_{text}",
                        name="echo",
                        input={"text": text},
                    ),
                )
            return
        yield ModelChunk(kind="text_delta", text="done")


def _git_head() -> str:
    configured = os.environ.get("XEYO_EVIDENCE_GIT_HEAD", "").strip()
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _usage() -> dict[str, int]:
    return {
        "prompt_tokens": 500,
        "completion_tokens": 600,
        "total_tokens": 1100,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 500,
    }


def _engine(workspace: Path, model: Any, **extra: Any) -> QueryEngine:
    registry = ToolRegistry(cwd=str(workspace))
    registry.register(EchoTool())
    config: dict[str, Any] = {
        "cwd": str(workspace),
        "tools": registry,
        "model_client": model,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "session_id": f"bench-{uuid4().hex}",
        "rewind_enabled": False,
        "runtime_checkpoint": False,
    }
    config.update(extra)
    return QueryEngine(config)


def _event_summary(events: list[Any], model: Any, elapsed_s: float) -> dict[str, Any]:
    stopped = [e for e in events if isinstance(e, StoppedEvent)]
    results = [e for e in events if isinstance(e, ResultEvent)]
    usage = [e for e in events if isinstance(e, UsageEvent)]
    return {
        "termination_reason": (
            stopped[-1].reason if stopped else (results[-1].stop_reason if results else None)
        ),
        "stopped_event": bool(stopped),
        "result_stop_reason": results[-1].stop_reason if results else None,
        "model_turns": int(getattr(model, "calls", 0)),
        "tool_calls_started": sum(isinstance(e, ToolCallEvent) for e in events),
        "tool_results": sum(isinstance(e, ToolResultEvent) for e in events),
        "usage_events": len(usage),
        "elapsed_ms": round(elapsed_s * 1000, 3),
    }


async def _run_engine_scenario(
    workspace: Path, name: str, model: Any, **config: Any
) -> dict[str, Any]:
    engine = _engine(workspace, model, **config)
    started = time.perf_counter()
    events = [event async for event in engine.submit("benchmark")]
    elapsed = time.perf_counter() - started
    budget = engine._session.budget
    result = _event_summary(events, model, elapsed)
    result.update(
        {
            "scenario": name,
            "budget": {
                "turn_count": budget.turn_count,
                "max_turns": budget.max_turns,
                "max_tool_calling": budget.max_tool_calling,
                "grace_turns_used": budget.grace_turns_used,
                "used_tokens": budget.used_tokens,
                "used_usd": round(budget.used_usd, 8),
                "usd_limit": budget.usd_limit,
                "hard_stop_reason": budget.hard_stop_reason,
            },
        }
    )
    return result


def _loop_scenarios() -> list[dict[str, Any]]:
    duplicate = LoopBreaker(same_at=3, probe_after=10**6)
    duplicate_seen: list[str] = []
    for _ in range(53):
        refusal = duplicate.admit("Bash", {"command": "rg -n foo"})
        duplicate_seen.append(refusal.kind if refusal else "allowed")

    cycle = LoopBreaker(same_at=99, cycle_at=3, probe_after=10**6)
    cycle_seen: list[str] = []
    calls = [("Read", {"path": "a"}), ("Bash", {"command": "b"})]
    for index in range(6):
        refusal = cycle.admit(*calls[index % 2])
        cycle_seen.append(refusal.kind if refusal else "allowed")

    normal = LoopBreaker(same_at=3, cycle_at=3, probe_after=10**6)
    normal_seen: list[str] = []
    for index in range(20):
        refusal = normal.admit("Read", {"path": f"file-{index}.txt"})
        normal_seen.append(refusal.kind if refusal else "allowed")

    return [
        {
            "scenario": "duplicate_tool_call",
            "attempts": len(duplicate_seen),
            "allowed": duplicate_seen.count("allowed"),
            "blocked": len(duplicate_seen) - duplicate_seen.count("allowed"),
            "first_block_kind": next(
                (item for item in duplicate_seen if item != "allowed"), None
            ),
            "last_block_kind": duplicate_seen[-1],
            "bounded": duplicate_seen[-1] != "allowed",
        },
        {
            "scenario": "periodic_tool_call",
            "attempts": len(cycle_seen),
            "allowed": cycle_seen.count("allowed"),
            "blocked": len(cycle_seen) - cycle_seen.count("allowed"),
            "first_block_kind": next(
                (item for item in cycle_seen if item != "allowed"), None
            ),
            "bounded": cycle_seen[-1] != "allowed",
        },
        {
            "scenario": "normal_distinct_tool_calls",
            "attempts": len(normal_seen),
            "allowed": normal_seen.count("allowed"),
            "blocked": len(normal_seen) - normal_seen.count("allowed"),
            "false_positive": any(item != "allowed" for item in normal_seen),
        },
    ]


async def _run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="xeyo-resume-evidence-") as temp:
        workspace = Path(temp) / "workspace"
        workspace.mkdir()
        os.environ["XEYO_HOME"] = str(Path(temp) / "xeyo-home")
        os.environ["XEYO_USAGE_DIR"] = str(Path(temp) / "usage")

        original_pricing = pricing.get_model_pricing
        original_time = pricing.time.time
        pricing.get_model_pricing = lambda provider, model, timeout=3.0: PIN  # type: ignore[assignment]
        pricing.time.time = lambda: OFFPEAK_TS  # type: ignore[assignment]
        try:
            engine_results = [
                await _run_engine_scenario(
                    workspace,
                    "normal_short_task",
                    EndTurnModel(),
                    max_turns=3,
                    max_tool_calling=8,
                ),
                await _run_engine_scenario(
                    workspace,
                    "normal_multi_tool_task",
                    MultiToolThenTextModel(),
                    max_turns=3,
                    max_tool_calling=8,
                ),
                await _run_engine_scenario(
                    workspace,
                    "runaway_turn_budget",
                    AlwaysToolModel(),
                    max_turns=3,
                    max_tool_calling=16,
                ),
                await _run_engine_scenario(
                    workspace,
                    "runaway_usd_budget",
                    AlwaysToolModel(_usage()),
                    max_turns=256,
                    max_tool_calling=16,
                    max_budget_usd=0.01,
                ),
            ]
        finally:
            pricing.get_model_pricing = original_pricing
            pricing.time.time = original_time

        return {
            "schema_version": 1,
            "benchmark": "xeyo_long_task_control",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": _git_head(),
            "conditions": {
                "python": sys.version,
                "workspace": "temporary isolated workspace",
                "model": "deterministic fake model; no network",
                "pricing": PIN,
                "usd_timestamp": OFFPEAK_TS,
                "probe_after": 10**6,
            },
            "engine_scenarios": engine_results,
            "loop_breaker_scenarios": _loop_scenarios(),
        }


def main() -> int:
    result = asyncio.run(_run())
    output = ROOT / "benchmarks" / "resume_evidence" / "results" / "xeyo_long_task_control.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"raw_result={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
