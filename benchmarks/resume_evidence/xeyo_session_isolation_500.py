"""500-session XEYO state-isolation benchmark.

The production SessionPool is exercised with a minimal real QueryEngine per
session.  Each engine owns a separate ToolRegistry, probe-tool state, budget and
message container.  Five hundred worker threads are held at a barrier so the
result describes simultaneous live sessions rather than merely 500 total
requests.

Run from the repository root:

    py -3.11 benchmarks/resume_evidence/xeyo_session_isolation_500.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from engine.abort import AbortController
from engine.query_engine import QueryEngine
from msgtypes.message import ToolUse
from server.session_pool import ModelConfig, SessionPool
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


SESSION_COUNT = 500


class ProbeTool:
    """Mutable per-registry state used as an isolation oracle."""

    def __init__(self, owner_session_id: str) -> None:
        self.name = "bench_probe"
        self.owner_session_id = owner_session_id
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def is_read_only() -> bool:
        return True

    @staticmethod
    def is_concurrency_safe() -> bool:
        return True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "benchmark probe",
            "input_schema": {"type": "object", "properties": {}},
        }

    async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
        abort.raise_if_aborted()
        self.calls.append(dict(input or {}))
        return ToolResult(content=self.owner_session_id)


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


def main() -> int:
    started = time.perf_counter()
    old_env = {
        key: os.environ.get(key)
        for key in ("XEYO_HOME", "XEYO_USAGE_DIR", "XEYO_REWIND_ENABLED", "XEYO_RUNTIME_CHECKPOINT")
    }
    with tempfile.TemporaryDirectory(prefix="xeyo-session-evidence-") as temp:
        temp_root = Path(temp)
        os.environ["XEYO_HOME"] = str(temp_root / "xeyo-home")
        os.environ["XEYO_USAGE_DIR"] = str(temp_root / "usage")
        os.environ["XEYO_REWIND_ENABLED"] = "0"
        os.environ["XEYO_RUNTIME_CHECKPOINT"] = "0"

        workspace_root = temp_root / "workspaces"
        workspace_root.mkdir()
        workspace_paths = []
        for index in range(SESSION_COUNT):
            path = workspace_root / f"ws-{index:04d}"
            path.mkdir()
            workspace_paths.append(path)

        cfg = ModelConfig(
            provider="fake",
            api_key="bench",
            base_url="http://127.0.0.1/unused",
            model="fake",
        )
        pool = SessionPool(
            cwd=str(workspace_paths[0]),
            busy_stale_sec=600,
            max_engines=SESSION_COUNT,
        )

        def build(
            build_cfg: ModelConfig,
            *,
            session_id: str,
            initial_messages: list[Any] | None = None,
            cwd: str,
        ) -> QueryEngine:
            registry = ToolRegistry(cwd=cwd)
            registry.register(ProbeTool(session_id))
            return QueryEngine(
                {
                    "cwd": cwd,
                    "tools": registry,
                    "model_client": object(),
                    "provider": build_cfg.provider,
                    "model": build_cfg.model,
                    "session_id": session_id,
                    "initial_messages": initial_messages or [],
                    "rewind_enabled": False,
                    "runtime_checkpoint": False,
                }
            )

        # SessionPool is production code; only its external model-building seam
        # is replaced to prevent network/model startup from contaminating this
        # isolation experiment.
        pool._build = build  # type: ignore[method-assign]
        barrier = threading.Barrier(SESSION_COUNT, timeout=120)
        errors: list[str] = []
        errors_lock = threading.Lock()

        def one(index: int) -> dict[str, Any]:
            session_id = f"bench-session-{index:04d}"
            workspace = workspace_paths[index]
            try:
                engine = pool.get_or_create(session_id, cfg, cwd=str(workspace))
                registry = engine.config["tools"]
                probe = registry.get("bench_probe")
                if not isinstance(probe, ProbeTool):
                    raise AssertionError("probe tool missing or shared type mismatch")
                probe.calls.append({"session_id": session_id, "arg": f"arg-{index}"})
                barrier.wait()
                return {
                    "session_id": session_id,
                    "engine_session_id": engine.session_id,
                    "config_cwd": str(engine.config["cwd"]),
                    "registry_cwd": registry.cwd,
                    "probe_owner": probe.owner_session_id,
                    "probe_calls": list(probe.calls),
                    "budget_identity": id(engine._session.budget),
                    "message_identity": id(engine._session.messages),
                    "tool_identity": id(probe),
                }
            except Exception as exc:  # pragma: no cover - raw failure evidence
                with errors_lock:
                    errors.append(f"{session_id}: {type(exc).__name__}: {exc}")
                try:
                    barrier.abort()
                except Exception:
                    pass
                return {"session_id": session_id, "error": f"{type(exc).__name__}: {exc}"}

        records: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=SESSION_COUNT) as executor:
            futures = [executor.submit(one, index) for index in range(SESSION_COUNT)]
            for future in as_completed(futures):
                records.append(future.result())

        records.sort(key=lambda item: item["session_id"])
        valid = [record for record in records if "error" not in record]
        unique_session_ids = len({record["session_id"] for record in valid})
        unique_engine_ids = len({record["engine_session_id"] for record in valid})
        unique_budget_ids = len({record["budget_identity"] for record in valid})
        unique_message_ids = len({record["message_identity"] for record in valid})
        unique_tool_ids = len({record["tool_identity"] for record in valid})
        owner_mismatches = [
            record
            for record in valid
            if record["session_id"] != record["engine_session_id"]
            or record["session_id"] != record["probe_owner"]
            or record["config_cwd"] != record["registry_cwd"]
            or len(record["probe_calls"]) != 1
            or record["probe_calls"][0].get("session_id") != record["session_id"]
        ]
        expected_cwds = {
            f"bench-session-{index:04d}": str(workspace_paths[index])
            for index in range(SESSION_COUNT)
        }
        cwd_mismatches = [
            record
            for record in valid
            if expected_cwds.get(record["session_id"]) != record["config_cwd"]
        ]

        passed = (
            not errors
            and len(valid) == SESSION_COUNT
            and unique_session_ids == SESSION_COUNT
            and unique_engine_ids == SESSION_COUNT
            and unique_budget_ids == SESSION_COUNT
            and unique_message_ids == SESSION_COUNT
            and unique_tool_ids == SESSION_COUNT
            and not owner_mismatches
            and not cwd_mismatches
            and pool.loaded_sessions() == SESSION_COUNT
        )
        result = {
            "schema_version": 1,
            "benchmark": "xeyo_session_isolation_500",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "git_head": _git_head(),
            "conditions": {
                "python": sys.version,
                "session_count": SESSION_COUNT,
                "worker_threads": SESSION_COUNT,
                "simultaneous_barrier": SESSION_COUNT,
                "model": "minimal local QueryEngine with deterministic probe tool; no network",
                "pool_max_engines": SESSION_COUNT,
            },
            "summary": {
                "passed": passed,
                "sessions_created": len(valid),
                "loaded_sessions": pool.loaded_sessions(),
                "unique_engine_instances": unique_engine_ids,
                "unique_budget_instances": unique_budget_ids,
                "unique_message_containers": unique_message_ids,
                "unique_tool_instances": unique_tool_ids,
                "owner_mismatches": len(owner_mismatches),
                "cwd_mismatches": len(cwd_mismatches),
                "errors": len(errors),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            },
            "errors": errors[:20],
            "mismatch_examples": (owner_mismatches + cwd_mismatches)[:20],
            "records": records,
        }

    for key, value in old_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    output = ROOT / "benchmarks" / "resume_evidence" / "results" / "xeyo_session_isolation_500.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"raw_result={output}")
    return 0 if result["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
