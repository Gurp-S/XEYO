"""被拒的工具调用也要进审计——否则归属表看不见真实存在的失败类。

`tools/tool_registry.py::run` 有两条**在记账之前就 return** 的拒绝：
保留前缀（`RESERVED_CHANNEL`）与未知工具（`UNKNOWN_TOOL`）；两者都给了模型机器可读的
`error_kind`，但没有 `tool.started/tool.finished`，也没有任何审计行。
下一个分支（`readonly_gate` 的 DENY）就老老实实 `record("permission.denied", ...)`
⇒ 说明"拒绝要留痕"是本层既有口径，这两条是漏，不是设计。

现网分母（2026-10-04 全量 421 份转录 / 84,279 行全局审计）：
- 转录里 `unknown tool:` 出现 **360 次 / 38 个会话**、`reserved environment channel` **47 次 / 7 个会话**；
- 全局审计里 `UNKNOWN_TOOL` **0 次**、`RESERVED_CHANNEL` **0 次**（同期有 7,208 行带别的 error_kind）。
⇒ 这 407 次真实失败在归属/诊断面上完全不存在。

**10-05 已修**：两条早退各补一行 `_record_rejected_call(...)`
（记 `tool.rejected` + `error_kind` + `request_id`；boundary_of 落在 `tool_permission`
族，与 `permission.denied` 同面）；两条 strict xfail 已摘牌。

本文件先钉住**账真的记得到**（正控）——
没有正控，断言也可能只是因为我把测试写错了。
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry


def _audit_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _audit_env(tmp_path, monkeypatch) -> Path:
    from audit.log import reset_default_audit_log

    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("XEYO_AUDIT_LOG", str(path))
    reset_default_audit_log()
    return path


@pytest.mark.asyncio
async def test_a_normal_call_leaves_audit_rows(tmp_path, monkeypatch):
    """正控：记账通路本身是通的（否则下面两条 xfail 证明不了任何事）。"""
    path = _audit_env(tmp_path, monkeypatch)
    reg = build_default_registry(cwd=str(tmp_path))
    res = await reg.run(ToolUse(id="t-ok", name="getTime", input={}), AbortController())
    assert res.is_error is False, res.content
    kinds = {r.get("kind") for r in _audit_rows(path)}
    assert {"tool.started", "tool.finished"} <= kinds, (kinds, _audit_rows(path)[:3])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name,needle,kind",
    [
        ("NoSuchToolAtAll", "unknown tool", "UNKNOWN_TOOL"),
        ("xeyo_env_channel_probe", "reserved environment channel", "RESERVED_CHANNEL"),
    ],
    ids=["unknown_tool", "reserved_channel"],
)
async def test_rejected_tool_calls_are_audited(tmp_path, monkeypatch, tool_name, needle, kind):
    path = _audit_env(tmp_path, monkeypatch)
    reg = build_default_registry(cwd=str(tmp_path))
    res = await reg.run(ToolUse(id="t-bad", name=tool_name, input={}), AbortController())
    assert res.is_error is True and needle in res.content, res.content
    assert res.error_kind == kind, res.error_kind

    rows = _audit_rows(path)
    hit = [r for r in rows if r.get("error_kind") == kind and r.get("request_id") == "t-bad"]
    assert hit, f"{kind} 的拒绝没进审计（当前 {len(rows)} 行里只有 {sorted({r.get('kind') for r in rows})}）"
