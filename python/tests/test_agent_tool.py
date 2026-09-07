"""AgentTool / 子 Agent 机制边界测试。

catalog 契约：任何副作用工具须有边界测试（此处覆盖 Agent 工具 + 子 Agent 机制）。
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.abort import AbortController
from engine.scheduler import Task, scope_conflicts, toposort
from engine.subagent_context import build_subagent_context
from engine.write_store import ChangeIntent, EditOp, WriteStore
from tools.agent_tool import AgentTool
from tools.catalog import build_default_registry, build_subagent_registry, default_tool_names
from tools.fileio.read_state import ReadFileState


# ---- Agent 工具在默认注册表 / 冻结集里 ----

def test_agent_in_default_registry():
	names = set(default_tool_names())
	assert "Agent" in names  # 已在 test_catalog._FROZEN_ENABLED 显式加入
	reg = build_default_registry(cwd=".")
	assert reg.get("Agent") is not None


# ---- 子 Agent 注册表：受限 + 剔除禁止项 + 注入 write_store ----

def test_subagent_registry_bounded_and_excludes_forbidden(tmp_path):
	reg = build_subagent_registry(
		cwd=str(tmp_path),
		tool_names=["Read", "Write", "Edit", "Bash", "_agent", "Memory"],
		read_state=ReadFileState(),
		agent_id="agent-x",
	)
	names = set(reg._tools)  # type: ignore[attr-defined]
	# Phase 2：Bash 可下发；Memory/_agent/Agent 仍禁
	assert "Bash" in names
	assert "_agent" not in names
	assert "Agent" not in names   # 递归禁（A8）：子 agent 无权再 spawn
	assert {"Read", "Write", "Edit", "Bash"} <= names
	assert "Memory" not in names  # Wave 6：子 agent 默认不可写 memdir


def test_subagent_registry_includes_journal_query(tmp_path):
	reg = build_subagent_registry(
		cwd=str(tmp_path),
		tool_names=["Read", "JournalQuery", "Grep"],
		read_state=ReadFileState(),
		agent_id="agent-j",
	)
	assert reg.get("JournalQuery") is not None


def test_agent_tool_concurrency_safe():
	"""工具化后：同轮可并行；旧 batch 闸已删除。"""
	at = AgentTool(cwd=".")
	assert AgentTool.is_concurrency_safe() is True
	assert not hasattr(at, "set_batch_active_check")
	# 无 runtime → 配置错误（不再是 scheduler batch 拒绝）。
	res = asyncio.run(at.execute({"task_id": "t1", "desc": "x"}, AbortController()))
	assert res.is_error
	assert "scheduler batch" not in res.content
	assert "runtime not configured" in res.content

@pytest.mark.asyncio
async def test_journal_query_execute(tmp_path, monkeypatch):
	from memory.journal import ChangeRecord
	import memory.journal as j
	from tools.journal_query_tool import JournalQueryTool

	monkeypatch.setattr(
		j,
		"recent_changes",
		lambda *_a, **_k: [
			ChangeRecord(
				seq=1,
				agent_id="agent-a",
				path="src/foo.ts",
				action="edit",
				file_hash_after="sha256:x",
				ts=1.0,
				brief="hook",
			),
		],
	)
	tool = JournalQueryTool(cwd=str(tmp_path))
	res = await tool.execute({}, AbortController())
	assert not res.is_error
	assert "src/foo.ts" in res.content


def test_subagent_registry_injects_write_store(tmp_path):
	from engine.write_store import WriteStore

	store = WriteStore(tmp_path)
	reg = build_subagent_registry(
		cwd=str(tmp_path),
		tool_names=["Read", "Write", "Edit"],
		read_state=ReadFileState(),
		write_store=store,
		agent_id="agent-y",
	)
	write_tool = reg.get("Write")
	edit_tool = reg.get("Edit")
	assert write_tool._write_store is store        # type: ignore[attr-defined]
	assert write_tool._agent_id == "agent-y"       # type: ignore[attr-defined]
	assert edit_tool._write_store is store         # type: ignore[attr-defined]


# ---- A3 前缀稳定 + A4/A8 剔除禁止项 ----

def test_subagent_context_a3_stable_and_forbidden_removed():
	base = "IDENTITY\nXEYO.md\nMEMORY_BEHAVIOR\nTOOL_SCHEMA"
	ctx = build_subagent_context(
		base_prefix=base,
		task_prompt="TASK edit foo",
		recent_changes="[journal] agent-b changed src/foo.ts",
		tool_whitelist=["Edit", "Read", "_agent", "Bash", "Grep"],
	)
	assert ctx.system_prompt.startswith(base)                 # 稳定前缀在最前、未被改
	assert ctx.system_prompt.rstrip().endswith(ctx.dynamic_tail)  # 动态在尾部（A3）
	assert ctx.dynamic_tail not in base                        # 动态未插进 base
	assert "_agent" not in ctx.tool_names
	assert "Bash" in ctx.tool_names  # Phase 2：Bash 可进白名单（另受策略沙箱约束）
	assert ctx.tool_names == ["Bash", "Edit", "Grep", "Read"]


# ---- AgentTool 边界：无运行时 / 超深度 安全失败 ----

def test_agent_tool_no_runtime_safe_error():
	at = AgentTool(cwd=".")
	res = asyncio.run(at.execute({"task_id": "t1", "desc": "do x"}, AbortController()))
	assert res.is_error
	assert "runtime not configured" in res.content


def test_agent_tool_max_depth_rejected():
	at = AgentTool(cwd=".")
	res = asyncio.run(
		at.execute({"task_id": "t1", "desc": "x", "parent_depth": 1}, AbortController())
	)
	assert res.is_error
	assert "max agent depth" in res.content


# ---- 每文件单写者写路径：stale 拒绝、不覆盖 ----

def test_write_store_submit_sync_stale_rejects(tmp_path, monkeypatch):
	import memory.journal as j

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "a.ts"
	# 新建
	r1 = store.submit_sync(
		ChangeIntent(agent_id="a", base_hashes={str(p): ""},
					 ops=[EditOp(path=str(p), new_content="hello")])
	)
	assert r1.ok
	assert Path(p).read_text() == "hello"
	# stale：base 哈希不符 -> 拒绝、不覆盖
	r2 = store.submit_sync(
		ChangeIntent(agent_id="b", base_hashes={str(p): "sha256:WRONG"},
					 ops=[EditOp(path=str(p), new_content="WORLD")])
	)
	assert not r2.ok and r2.base_stale
	assert Path(p).read_text() == "hello"      # 未被覆盖
	from memory.memdir import workspace_id

	wsid = workspace_id(str(tmp_path))
	rows = j.recent_changes(wsid)
	assert any(r.conflict_task and r.action == "stale_reject" for r in rows)


# ---- 调度器：DAG 拓扑 + 文件级冲突 ----

def test_scheduler_toposort_and_scope_conflict():
	ts = [Task(id="t1", desc="a", scope=["src/a.ts"]),
		  Task(id="t2", desc="b", depends_on=["t1"], scope=["src/b.ts"]),
		  Task(id="t3", desc="c", scope=["src/a.ts"])]
	assert [t.id for t in toposort(ts)] == ["t1", "t3", "t2"]  # t1 先于 t2（依赖）
	assert scope_conflicts(ts[0], ts[2])       # 同文件 -> 冲突
	assert not scope_conflicts(ts[0], ts[1])   # 不同文件 -> 不冲突
	# 未声明 scope：保守视为冲突
	assert scope_conflicts(Task(id="x", desc="x"), Task(id="y", desc="y", scope=["a.ts"]))
	assert scope_conflicts(Task(id="x", desc="x"), Task(id="y", desc="y"))


# ---- 侧链：agent_id snapshot 持久化 + GC（B6/C9） ----

def test_flush_subagent_snapshot(tmp_path, monkeypatch):
	from engine.subagent_runner import _flush_subagent_snapshot
	from engine.subagent_runner import _sidechain_dir  # noqa: F401
	from memory.working import WorkingSnapshot

	monkeypatch.setattr("engine.subagent_runner._sidechain_dir", lambda main: tmp_path)
	snap = WorkingSnapshot(session_id="main", agent_id="agent-z")
	_flush_subagent_snapshot("main", "agent-z", snap)
	f = tmp_path / "agent-z.working.json"
	assert f.exists()
	import json
	data = json.loads(f.read_text(encoding="utf-8"))
	assert data["agent_id"] == "agent-z"


def test_sidechain_gc(tmp_path, monkeypatch):
	import os
	import time

	from engine.subagent_runner import gc_sidechains

	monkeypatch.setattr("engine.subagent_runner._sidechain_dir", lambda main: tmp_path)
	old = tmp_path / "old.jsonl"
	old.write_text("x", encoding="utf-8")
	os.utime(old, (time.time() - 10 * 24 * 3600, time.time() - 10 * 24 * 3600))
	fresh = tmp_path / "new.jsonl"
	fresh.write_text("x", encoding="utf-8")
	removed = gc_sidechains("sess", ttl_seconds=7 * 24 * 3600)
	assert removed == 1
	assert not old.exists() and fresh.exists()

