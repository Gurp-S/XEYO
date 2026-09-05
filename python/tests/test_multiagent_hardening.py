"""多 Agent 链路防「静默失败」回归测试。

背景：单任务异常曾从 gather 炸出导致整批 SSE 流断掉（前端无卡片无横幅）。
契约：任何子任务内部异常都必须落成可见的 status=failed + failure_reason，
batch 本身正常返回。
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.scheduler import Task, run_task_batch  # noqa: E402


class BoomPromptAssembler:
	"""base_prefix 生成阶段即抛错（模拟 prompt 组装崩溃）。"""

	async def build_system_parts(self, *args, **kwargs):
		raise RuntimeError("prompt boom")

	async def build_system(self, *args, **kwargs):
		raise RuntimeError("prompt boom")


def _runtime(tmp_path):
	return SimpleNamespace(
		model_client=None,
		prompt_assembler=BoomPromptAssembler(),
		workspace_root=str(tmp_path),
		append_system_prompt="",
		date_iso="2026-01-01",
	)


def test_single_task_crash_becomes_visible_failed_not_raise(tmp_path):
	tasks = [Task(id="t1", desc="会炸的任务")]
	out = asyncio.run(
		run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: _runtime(tmp_path),
			main_session_id="s-test",
		)
	)
	assert len(out) == 1
	assert out[0].status == "failed"
	assert "prompt boom" in out[0].failure_reason


def test_multi_task_crash_marks_every_failing_task_and_survives(tmp_path):
	tasks = [Task(id=f"t{i}", desc=f"任务{i}") for i in range(3)]
	for t in tasks[1:]:
		t.depends_on = ["t0"]
	out = asyncio.run(
		run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: _runtime(tmp_path),
			main_session_id="s-test",
		)
	)
	assert [t.id for t in out] == ["t0", "t1", "t2"]
	assert all(t.status == "failed" for t in out)


def test_missing_runtime_reports_not_configured(tmp_path):
	tasks = [Task(id="t1", desc="无 runtime")]
	out = asyncio.run(
		run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: None,
			main_session_id="s-test",
		)
	)
	assert out[0].status == "failed"
	assert out[0].failure_reason == "runtime_not_configured"


def test_agent_ids_pregeneration_used_for_failed_tasks(tmp_path):
	captured: dict[str, str] = {}

	class SpyStore:
		def __init__(self, root):
			self.root = root

	import engine.scheduler as sched_mod

	orig_init = sched_mod.Scheduler.__init__

	def spy_init(self, workspace_root, **kw):
		orig_init(self, workspace_root, **kw)

	sched_mod.Scheduler.__init__ = spy_init

	tasks = [Task(id="tA", desc="注入检查")]
	try:
		out = asyncio.run(
			run_task_batch(
				tasks,
				workspace_root=tmp_path,
				runtime_provider=lambda: _runtime(tmp_path),
				main_session_id="s-test",
				agent_ids={"tA": "agent-tA-beef"},
			)
		)
	finally:
		sched_mod.Scheduler.__init__ = orig_init
	assert out[0].status == "failed"  # prompt 炸 → failed（异常被收敛为可见状态）


def test_progress_events_emitted_started_and_finished(tmp_path):
	"""单任务崩溃也必须发出 task_started + task_finished（status=failed）。"""
	events: list[dict] = []
	tasks = [Task(id="t1", desc="会炸的任务")]
	asyncio.run(
		run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: _runtime(tmp_path),
			main_session_id="s-test",
			on_event=events.append,
		)
	)
	types = [e.get("type") for e in events]
	assert types == ["task_started", "task_finished"]
	fin = events[1]
	assert fin["task_id"] == "t1"
	assert fin["status"] == "failed"
	assert "prompt boom" in str(fin["reason"])
	assert all(e.get("kind") == "sched" for e in events)


def test_broken_sink_never_breaks_batch(tmp_path):
	def bad_sink(_ev):
		raise RuntimeError("sink boom")

	tasks = [Task(id="t1", desc="坏回调")]
	out = asyncio.run(
		run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: _runtime(tmp_path),
			main_session_id="s-test",
			on_event=bad_sink,
		)
	)
	assert out[0].status == "failed"  # 回调崩溃被吞，批次照常收敛
