"""All-tool performance + consumption audit (offline, deterministic).

Measures, per tool, on a representative task: wall latency (ms), output chars,
lines, token estimate (chars//4), and the tool's declared output cap, so both
cost (latency) and consumption (tokens into context) are visible side by side.
Tools that require network/API/UI/image/subagent are NOT invoked; their caps are
reported so token-flood risk can be reasoned about from the table.

Bash is measured through its real call() pipeline (run_command -> compact ->
truncate) so the compaction benefit is exercised; its permission gate is a
policy-layer concern orthogonal to this perf profile.

用法：cd python && python scripts/audit_tool_perf.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))

from engine.abort import AbortController
from tools.bash_tool.bash_tool import BashInput, BashTool
from tools.catalog import build_default_registry

REPO_ROOT = str(Path(__file__).resolve().parents[2])  # repo root (a git repo)
reg = build_default_registry(cwd=REPO_ROOT)
bash = BashTool(cwd=REPO_ROOT)

# 三元组 (tool, args, label)
CASES: list[tuple[str, dict, str]] = [
    ("getTime", {}, "getTime"),
    ("Glob", {"pattern": "**/*.py"}, "Glob broad **/*.py (dir sum)"),
    ("Glob", {"pattern": "*test_*.py", "path": "python/tests"}, "Glob name pat"),
    ("Grep", {"pattern": "def ", "path": "python/tools/glob_tool", "output_mode": "content", "head_limit": 50}, "Grep content"),
    ("Grep", {"pattern": "compact", "path": "python/tools/bash_tool", "output_mode": "symbols", "head_limit": 50}, "Grep symbols"),
    ("Read", {"file_path": "python/tools/catalog.py"}, "Read full file"),
    ("Read", {"file_path": "python/tools/bash_tool/cmd_compact.py", "symbol": "compact_command_output"}, "Read symbol"),
    ("Git", {"action": "summary"}, "Git summary"),
]

# 经 call() 管线跑 Bash（绕过策略门；测真实性能路径）。
BASH_CASES: list[tuple[str, str]] = [
    ("Bash echo", "echo hello"),
    ("Bash git log -n 80", "git log -n 80"),
    ("Bash python listdir", "python -c \"import os; print(len(os.listdir('.')))\""),
]


def tok(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


async def run_case(name: str, args: dict) -> dict:
    tool = reg.get(name)
    if tool is None:
        return {"ok": False, "note": "no tool"}
    cap = getattr(tool, "max_result_size_chars", None)
    start = time.perf_counter()
    try:
        result = await tool.execute(args, AbortController())
        ms = (time.perf_counter() - start) * 1000
        content = result.content or ""
        return {
            "ok": not result.is_error,
            "ms": ms,
            "chars": len(content),
            "lines": len(content.splitlines()),
            "tok": tok(content),
            "cap": cap,
        }
    except Exception as e:  # noqa: BLE001
        ms = (time.perf_counter() - start) * 1000
        return {"ok": False, "ms": ms, "note": f"ERR {type(e).__name__}: {str(e)[:60]}"}


def run_bash(label: str, command: str) -> dict:
    start = time.perf_counter()
    out = bash.call(BashInput(command=command))
    ms = (time.perf_counter() - start) * 1000
    body = (out.stdout or "").replace("\r\n", "\n").lstrip("\n").rstrip()
    return {
        "ok": not out.is_error,
        "ms": ms,
        "chars": len(body),
        "lines": len(body.splitlines()),
        "tok": tok(body),
        "cap": bash.max_result_size_chars,
        "note": out.return_code_interpretation or "",
    }


def cell(r: dict) -> str:
    if r.get("ok"):
        return f"{r['ms']:8.1f} {r['chars']:8d} {r['lines']:7d} {r['tok']:7d} {str(r['cap']) if r['cap'] else '∞':>7}"
    return f"{r.get('ms', 0):8.1f} {'-':>8} {'-':>7} {'-':>7} {'-':>7}  {r.get('note', '')}"


async def main() -> None:
    import asyncio

    print("=== XEYO tool perf/consumption audit (offline) ===\n")
    print(f"{'tool':<34} {'ms':>9} {'chars':>8} {'lines':>7} {'tok':>7} {'cap':>7}   note")
    print("-" * 86)
    for name, args, label in CASES:
        print(f"{label:<34} {cell(await run_case(name, args))}")
    for label, command in BASH_CASES:
        print(f"{label:<34} {cell(run_bash(label, command))}")

    print("\n=== Un-invoked tools (network/API/UI/image/subagent) — caps only ===")
    for name in ["WebFetch", "WebSearch", "Screenshot", "SendToWeChat", "Agent",
                 "NotebookEdit", "XeyoUI", "JournalQuery", "Memory", "Diagnostics",
                 "Skill", "TodoWrite"]:
        tool = reg.get(name)
        cap = getattr(tool, "max_result_size_chars", None) if tool else None
        print(f"{name:<24} cap={'∞ (unbounded)' if cap is None else cap}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
