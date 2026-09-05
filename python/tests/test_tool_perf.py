"""工具层「消耗/收益不变量」回归：断言优化方向成立，而非固定耗时（避免 flaky）。

覆盖：
- Read symbol < Read 全量（symbol-pack / codeindex 收益）
- Grep symbols < Grep content（symbols 输出形态收益）
- Bash compact < raw（stdout 压缩收益）
- 六个核心工具声明了输出上限（防 token 泄洪）
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.bash_tool.cmd_compact import compact_command_output
from tools.catalog import build_default_registry
from tools.glob_tool.glob_tool import GlobInput, GlobTool
from tools.grep_tool.grep_tool import GrepTool
from tools.file_read_tool.file_read_tool import FileReadTool

REPO_ROOT = str(Path(__file__).resolve().parents[2])


def tok(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


@pytest.fixture(scope="module")
def reg():
    return build_default_registry(cwd=REPO_ROOT)


def test_read_symbol_smaller_than_full(reg):
    reader = reg.get("Read")
    target = "python/tools/bash_tool/cmd_compact.py"
    full = awaitish_reader(reader, {"file_path": target})
    sym = awaitish_reader(reader, {"file_path": target, "symbol": "compact_command_output"})
    assert tok(sym) < tok(full)


def test_grep_symbols_smaller_than_content(reg):
    greper = reg.get("Grep")
    content = awaitish_grep(greper, {"pattern": "compact", "path": "python/tools/bash_tool", "output_mode": "content", "head_limit": 50})
    symbols = awaitish_grep(greper, {"pattern": "compact", "path": "python/tools/bash_tool", "output_mode": "symbols", "head_limit": 50})
    assert tok(symbols) < tok(content)


def test_bash_compact_reduces_tokens():
    # 与 bench_phase1 同源：pytest 大量 PASSED + 1 处失败。压缩应显著省 token。
    body = [f"tests/test_a.py::test_{i} PASSED" for i in range(100)]
    body += [
        "=========================== FAILURES ===========================",
        "_______________________ test_boom ________________________",
        "Traceback (most recent call last):",
        '  File "tests/test_a.py", line 3, in test_boom',
        "    assert False",
        "E       AssertionError",
        "===================== 100 passed, 1 failed =====================",
    ]
    raw = "\n".join(body)
    if len(raw) < 4500:
        raw += "\n" + ("ok filler line\n" * ((4500 - len(raw)) // 15 + 1))
    compacted = compact_command_output("pytest -q", raw)
    assert "Traceback" in compacted or "AssertionError" in compacted  # 失败信息保留
    assert tok(compacted) < tok(raw) * 0.5  # 至少省一半 token


def test_core_tools_declare_output_caps():
    names = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
    reg = build_default_registry(cwd=REPO_ROOT)
    for name in names:
        tool = reg.get(name)
        assert tool is not None, name
        assert getattr(tool, "max_result_size_chars", None) is not None, name


def test_glob_empty_nomatch_does_not_flood():
    # 空结果不应泄洪：只给 tip + 可能的 did-you-mean，不返回全库。
    tool = GlobTool(cwd=REPO_ROOT)
    out = tool.call(GlobInput(pattern="definitely_no_such_file_zzz.py"))
    assert out.filenames == []
    assert tok(tool.map_tool_result_to_content(out)) < 500


# --- 辅助函数（省去 async 夹具仪式） ---

def _run(coro):
    import asyncio

    return asyncio.run(coro)


def awaitish_reader(reader, args):
    return _run(reader.execute(args, AbortController())).content or ""


def awaitish_grep(greper, args):
    return _run(greper.execute(args, AbortController())).content or ""
