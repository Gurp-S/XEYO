"""Offline paired rollout probes; no model/API requests or production artifacts."""
from __future__ import annotations
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

DOMAINS = ("WRITES", "FACTS", "HEALTH", "QUERIES", "RESOURCES", "OUTPUT_BYTES")


@contextmanager
def environment(values):
    old = dict(os.environ)
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def worker():
    config = json.loads(sys.stdin.readline())
    from engine.write_store import WriteStore, ChangeIntent, EditOp, _content_hash_text
    class SlowStore(WriteStore):
        @staticmethod
        def _atomic_write(path, content, encoding="utf-8"):
            time.sleep(.15)
            path.write_text(content, encoding=encoding)
    root = Path(config["root"])
    print("ready", flush=True)
    deadline = time.monotonic() + 10
    while not (root / "start").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("worker_start_timeout")
        time.sleep(.01)
    path = root / "race.txt"
    result = SlowStore(root).submit_sync(ChangeIntent("a", [EditOp(str(path), new_content=config["value"])],
                                                  {str(path): _content_hash_text("old")}))
    print(json.dumps({"ok": result.ok, "reason": result.reason}), flush=True)


def process_probe(root):
    root.mkdir()
    (root / "race.txt").write_text("old")
    children = []
    try:
        for value in ("one", "two"):
            process = subprocess.Popen([sys.executable, "-m", "evals.harness_repair_ab", "--worker"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", cwd=Path(__file__).resolve().parents[1])
            children.append(process)
            process.stdin.write(json.dumps({"root": str(root), "value": value}) + "\n")
            process.stdin.flush()
        for process in children:
            if process.stdout.readline().strip() != "ready":
                raise RuntimeError("worker_not_ready: " + process.stderr.read())
        (root / "start").touch()
        results = []
        for process in children:
            output, error = process.communicate(timeout=15)
            if process.returncode:
                raise RuntimeError(error)
            results.append(json.loads(output.strip()))
        return {"accepted": sum(item["ok"] for item in results), "results": results,
                "fixture": "two real processes; delayed deterministic write boundary"}
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.communicate()


def sample(root, on):
    from tools.file_edit_tool.file_edit_tool import FileEditTool, EditInput
    from prompt.tool_result_diff_digest import apply_tool_result_digest
    from tools.file_write_tool.file_write_tool import FileWriteTool
    from tools.tool_registry import ToolRegistry
    from engine.abort import AbortController
    from msgtypes.message import ToolUse
    from evals.changedetect import trace
    from evals.changedetect.health import failures
    from engine import env_facts
    from tools.spill import save_text
    from session.workset_index import query
    from memory import journal
    root.mkdir()
    path = root / "race.py"
    path.write_text("value = 1\n")
    tool = FileEditTool(cwd=str(root))
    tool.set_session_id("ab")
    inp = EditInput(str(path), "1", "2")
    assert tool.validate_input(inp)["result"]
    path.write_text("value = 99\n")
    try:
        tool.call(inp)
        rejected = False
    except RuntimeError:
        rejected = True

    deletion = root / "deletion.py"
    deletion.write_text('message = (\n    "ERROR: "\n    "details"\n)\n')
    tool2 = FileEditTool(cwd=str(root))
    tool2.set_session_id("ab")
    registry = ToolRegistry(cwd=str(root))
    registry.register(tool2)
    registry.register(FileWriteTool(cwd=str(root)))
    result = asyncio.run(registry.run(ToolUse(id="deletion", name="Edit", input={
                "file_path": str(deletion), "old_string": '    "ERROR: "\n', "new_string": ""}),
                AbortController(), skip_ask=True))
    messages = [{"name": "Edit", "content": [{"type": "tool_result", "tool_use_id": "deletion", "content": result.content}]}]
    body = apply_tool_result_digest(messages)[0]["content"][0]["content"]
    strict = root / "strict.py"
    strict.write_text("value = 1\n")
    checked = asyncio.run(registry.run(ToolUse(id="strict", name="Write", input={
                "file_path": str(strict), "content": "return 1\n", "validation_policy": "strict"}),
                AbortController(), skip_ask=True))
    traces = trace.collect({"loop"})
    env_facts._FACTS_CACHE.clear()
    calls = []
    with patch.object(env_facts, "collect", side_effect=lambda _: calls.append(1) or {"shell": "fixture"}), \
         patch.object(env_facts, "probe_scratch", return_value=""), \
         patch.object(env_facts, "probe_browser", return_value=""), \
         patch("engine.execution_facts.writable", return_value=False):
        env_facts.facts(str(root))
        env_facts.facts(str(root))
        env_facts._FACTS_CACHE[str(root)] = {"scratch": ".xeyo/tmp", "shell": "fixture"}
        stale_scratch = "scratch" in env_facts.facts(str(root))
    env_facts._FACTS_CACHE.clear()
    original_write = os.write
    with patch("os.write", side_effect=lambda fd, data: original_write(fd, data[:3])):
        spill = save_text("ab", "abcdefghijk")
    for index in range(85):
        journal.record_change("paging", journal.ChangeRecord(seq=0, agent_id="a", path=f"file{index}.py",
                action="write", file_hash_after="h", ts=1,
                metadata={"session_id": "ab" if index < 3 else "other"}))
    legacy = journal.recent_changes("paging", limit=60)
    legacy_visible = [row for row in legacy if row.metadata.get("session_id") == "ab"]
    page = query("paging", "ab", limit=2)
    from tools.file_write_tool.file_write_tool import FileWriteTool, WriteInput
    from tools.fileio.text import get_mtime_ms
    same_time = root / "same-time.py"
    same_time.write_text("value = 1\n")
    previous = same_time.stat()
    write_tool = FileWriteTool(cwd=str(root))
    write_tool._read_state.set_written(str(same_time), same_time.read_text(), get_mtime_ms(str(same_time)), "ab", offset=None, limit=None)
    same_time.write_text("value = 9\n")
    os.utime(same_time, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    same_time_rejected = False
    try:
        write_tool.call(WriteInput(str(same_time), "value = 2\n"))
    except RuntimeError:
        same_time_rejected = True
    return {"external_change_rejected": rejected, "external_content_retained": path.read_text() == "value = 99\n",
            "registry_deletion_error": result.is_error, "deletion_visible_to_model": '-    "ERROR: "' in body,
            "legal_deletion_allowed": '"ERROR: "' not in deletion.read_text(),
            "visible_chars": len(body), "raw_result_chars": len(result.content),
            "strict_registry_rejected": checked.is_error, "strict_disk_unchanged": strict.read_text() == "value = 1\n",
            "trace_unhealthy": len(failures(traces)), "trace_multi_turn": traces["loop/multi_turn"],
            "stable_probe_calls": len(calls), "cached_scratch_stale": stale_scratch,
            "spill_complete": Path(spill.path).read_text() == "abcdefghijk",
            "session_page_returned": page["returned"] if on else len(legacy_visible),
            "session_page_total": page["total_matching_before_cursor"] if on else None,
            "unchanged_mtime_write_rejected": same_time_rejected,
            "unchanged_mtime_external_retained": same_time.read_text() == "value = 9\n"}


def run():
    repo = Path(__file__).resolve().parents[2]
    result = {"scope": "deterministic mechanisms and registry; no model task success claim",
              "variants": {}, "source_sha256": {}}
    with tempfile.TemporaryDirectory(prefix="xeyo-repair-ab-") as temporary:
        root = Path(temporary)
        for label, on in (("A", False), ("B", True)):
            values = {"XEYO_HARNESS_" + name: "1" if on else "0" for name in DOMAINS}
            for key in ("HOME", "JOURNAL_DIR", "METRICS_DIR", "SPILL_DIR", "SNAPSHOTS_DIR", "SESSIONS_DIR"):
                values["XEYO_" + key] = str(root / label / key)
            values["XEYO_TOOL_RESULT_DIFF"] = None
            values["XEYO_EXECUTION_FACT_CONTRACTS"] = "1"
            with environment(values):
                sample_root = root / label / "workspace"
                sample_root.parent.mkdir(parents=True, exist_ok=True)
                result["variants"][label] = sample(sample_root, on)
                result["variants"][label]["two_process_writes"] = process_probe(root / label / "processes")
    for path in (repo / "python/engine", repo / "python/tools", repo / "python/prompt", repo / "python/evals", repo / "python/session", repo / "python/memory"):
        for source in path.rglob("*.py"):
            result["source_sha256"][source.relative_to(repo).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    a, b = result["variants"]["A"], result["variants"]["B"]
    result["checks"] = {name: not a[name] and b[name] for name in (
        "external_change_rejected", "external_content_retained", "deletion_visible_to_model",
        "strict_registry_rejected", "strict_disk_unchanged", "spill_complete",
        "unchanged_mtime_write_rejected", "unchanged_mtime_external_retained")}
    result["checks"].update(
        cooperative_process_mutex=a["two_process_writes"]["accepted"] == 2 and b["two_process_writes"]["accepted"] == 1,
        trace_health=a["trace_unhealthy"] == 1 and b["trace_unhealthy"] == 0,
        stable_cache=a["stable_probe_calls"] == 2 and b["stable_probe_calls"] == 1,
        live_permissions=a["cached_scratch_stale"] and not b["cached_scratch_stale"],
        paging=a["session_page_returned"] == 0 and b["session_page_returned"] == 2 and b["session_page_total"] == 3,
        legal_deletion_remains_allowed=a["legal_deletion_allowed"] and b["legal_deletion_allowed"],
        registry_success=not a["registry_deletion_error"] and not b["registry_deletion_error"])
    from engine.harness_policy import DEFAULTS
    result["production_defaults"] = dict(DEFAULTS)
    result["passed"] = all(result["checks"].values())
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker()
        return
    if not args.out:
        parser.error("--out is required")
    result = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["variants"], ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit("repair_ab_failed: " + str(result["checks"]))


if __name__ == "__main__":
    main()
