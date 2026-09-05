"""T1/T27 spill seam 回归：原始输出先落盘，模型只见「预览 + 全文路径」。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from audit.log import default_audit_log, reset_default_audit_log
from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.spill import save_text
from tools.tool_registry import ToolRegistry


class _BigOutputTool:
	name = "echo"

	def schema(self) -> dict:
		return {"name": self.name, "description": "test", "parameters": {}}

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	async def execute(self, input: dict, abort) -> ToolResult:  # type: ignore[no-untyped-def]
		return ToolResult(content="x" * 20_000)


@pytest.fixture()
def spill_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
	root = tmp_path / "spill"
	monkeypatch.setenv("XEYO_SPILL_DIR", str(root))
	return root


def test_save_text_writes_full_content(spill_env: Path) -> None:
	ref = save_text("sess:abc", "hello world")
	p = Path(ref.path)
	assert p.is_file()
	assert p.read_text(encoding="utf-8") == "hello world"
	assert ref.bytes == len("hello world".encode())
	assert spill_env in p.parents


def test_save_text_exclusive_names(spill_env: Path) -> None:
	r1 = save_text("s", "a")
	r2 = save_text("s", "b")
	assert r1.path != r2.path


@pytest.mark.asyncio
async def test_registry_spills_over_budget_output(
	spill_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	_reset_audit(monkeypatch, tmp := spill_env.parent / "audit")
	reg = ToolRegistry(cwd=str(tmp))
	reg.register(_BigOutputTool())
	res = await reg.run(
		ToolUse(id="t1", name="echo", input={}),
		AbortController(),
	)
	assert not res.is_error
	assert "full output:" in res.content
	assert "预算截断" in res.content
	assert len(res.content) < 20_000  # 预览远小于原文
	spill_path = str((res.metadata or {}).get("spill_path"))
	assert spill_path
	assert Path(spill_path).read_text(encoding="utf-8") == "x" * 20_000
	# T27：原始证据可从 spill 文件取回原文
	events = default_audit_log().query(kind="tool.spill")
	assert events and events[-1].get("path") == spill_path


@pytest.mark.asyncio
async def test_registry_keeps_small_output(spill_env: Path) -> None:
	class SmallTool(_BigOutputTool):
		async def execute(self, input: dict, abort) -> ToolResult:  # type: ignore[no-untyped-def]
			return ToolResult(content="tiny")

	reg = ToolRegistry()
	reg.register(SmallTool())
	res = await reg.run(ToolUse(id="t2", name="echo", input={}), AbortController())
	assert res.content == "tiny"
	assert not (res.metadata or {}).get("spilled")


@pytest.mark.asyncio
async def test_spill_failure_returns_original(spill_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	def _boom(session_id: str, text: str):  # type: ignore[no-untyped-def]
		raise OSError("disk full")

	monkeypatch.setattr("tools.spill.save_text", _boom)
	reg = ToolRegistry()
	reg.register(_BigOutputTool())
	res = await reg.run(ToolUse(id="t3", name="echo", input={}), AbortController())
	assert not res.is_error
	assert res.content == "x" * 20_000  # 原样返回，宁可超预算不丢证据


def test_read_and_bash_exempt_via_meta() -> None:
	from tools.meta import meta_for

	assert meta_for("Read").output_budget == 0  # 防 read→spill→read 循环
	assert meta_for("Bash").output_budget == 0  # 自带 raw→落盘→截断 seam


def _reset_audit(monkeypatch: pytest.MonkeyPatch, tmp: Path) -> None:
	log_path = tmp / "audit.jsonl"
	log_path.parent.mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_AUDIT_LOG", str(log_path))
	reset_default_audit_log()


def test_retention_prune_old_files(spill_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	ref = save_text("s", "old evidence")
	# 把文件 mtime 拨回 30 天前，再保存一次触发清理
	old = Path(ref.path)
	import os as _os

	past = __import__("time").time() - 30 * 86400
	_os.utime(old, (past, past))
	save_text("s", "new evidence")
	assert not old.exists()  # 超过默认 7 天被清理


def test_retention_zero_disables_prune(spill_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_SPILL_RETENTION_DAYS", "0")
	ref = save_text("s", "keep me")
	old = Path(ref.path)
	past = __import__("time").time() - 365 * 86400
	os.utime(old, (past, past))
	save_text("s", "trigger")
	assert old.exists()  # 保留期<=0 视为永久保留
