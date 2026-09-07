"""Multi-Agent P1 metrics + journal + scheduler patch helpers."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.scheduler import MAX_PATCH_RETRIES, Scheduler, TaskRunResult
from memory.journal import ChangeRecord, format_changes_for_agent
from usage.multi_agent_metrics import read_events, record, record_write_stale


def test_format_changes_for_agent():
	text = format_changes_for_agent([
		ChangeRecord(
			seq=1,
			agent_id="agent-a",
			path="src/foo.ts",
			action="edit",
			file_hash_after="sha256:x",
			ts=1.0,
			brief="hook",
		),
	])
	assert "src/foo.ts" in text
	assert "agent-a" in text


def test_metrics_roundtrip(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path))
	record(kind="test_ping", value=1)
	rows = read_events()
	assert any(r.get("kind") == "test_ping" for r in rows)


def test_record_write_stale(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path))
	record_write_stale(agent_id="agent-x", path="src/a.ts", task_batch_id="tb1")
	rows = read_events()
	assert rows[-1]["kind"] == "write_stale"


def test_build_patch_desc(tmp_path):
	sched = Scheduler(str(tmp_path), task_batch_id="tb")
	sched._original_desc["t1"] = "edit foo"
	text = sched._build_patch_desc("t1", 1)
	assert "Patch retry" in text
	assert "edit foo" in text


def test_max_patch_retries_constant():
	assert MAX_PATCH_RETRIES == 3


def test_task_run_result_defaults():
	r = TaskRunResult(ok=False, reason="stale", had_write_stale=True)
	assert r.had_write_stale is True


def test_scheduler_run_subagent_kwargs_compatible():
	import inspect
	from engine.subagent_runner import run_subagent

	params = inspect.signature(run_subagent).parameters
	for name in ("task_batch_id", "session_id", "task_id", "on_text_delta", "recent_changes"):
		assert name in params, f"run_subagent missing {name}"


def test_gate_report_empty(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_METRICS_DIR", str(tmp_path))
	from scripts.multi_agent_gate_report import build_report

	report = build_report()
	assert "collision_rate" in report
	assert report["recommendations"]


def test_format_findings_for_synthesis_truncates():
	from engine.subagent_runner import format_findings_for_synthesis

	text = format_findings_for_synthesis([
		{
			"desc": "查找文件",
			"status": "done",
			"result": "x" * 2000,
		},
		{
			"desc": "分析",
			"status": "failed",
			"reason": "timeout",
		},
	])
	assert "[done] 查找文件" in text
	assert "[failed] 分析" in text
	assert "…" in text
	assert "timeout" in text


@pytest.mark.asyncio
async def test_synthesize_multi_agent_answer_streams_tokens():
	from engine.subagent_runner import synthesize_multi_agent_answer
	from model.chunks import ModelChunk

	class FakeClient:
		async def stream(self, messages, tools, abort):
			yield ModelChunk(kind="text_delta", text="方案：")
			yield ModelChunk(kind="text_delta", text="用加号菜单")

	parts: list[str] = []
	async for piece in synthesize_multi_agent_answer(
		user_text="不要改代码，怎么做加号菜单？",
		task_rows=[{"desc": "查 Sidebar", "status": "done", "result": "Sidebar.tsx"}],
		model_client=FakeClient(),
	):
		parts.append(piece)
	assert "".join(parts) == "方案：用加号菜单"


def test_dag_dependent_tasks_run_after_upstream(tmp_path, monkeypatch):
	"""P1：depends_on 必须等上游完成后再启动（不能 gather 全 pending）。"""
	import asyncio
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	start_order: list[str] = []
	lock = asyncio.Lock()

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		async with lock:
			start_order.append(t.id)
		await asyncio.sleep(0.02)
		t.last_result = f"ok-{t.id}"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)

	tasks = [
		Task(id="t1", desc="first"),
		Task(id="t2", desc="second", depends_on=["t1"]),
	]
	out = asyncio.run(
		run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: object(),
			main_session_id="sess-dag",
		)
	)
	by_id = {t.id: t for t in out}
	assert start_order.index("t1") < start_order.index("t2")
	assert by_id["t1"].status == "done"
	assert by_id["t2"].status == "done"


def test_checkpoint_helpers_persist_resume_abandon(tmp_path):
	from engine.scheduler import (
		Scheduler,
		Task,
		checkpoint_is_incomplete,
		checkpoint_summary,
		clear_scheduler_checkpoint,
		read_scheduler_checkpoint,
		scheduler_state_path,
	)

	sched = Scheduler(
		tmp_path,
		main_session_id="sess-ckpt",
		agent_ids={"t1": "agent-t1", "t2": "agent-t2"},
		task_batch_id="batch-1",
		ui_uids={"t1": "t1:u", "t2": "t2:u"},
	)
	sched.load([
		Task(id="t1", desc="done already", status="done", last_result="ok"),
		Task(id="t2", desc="was running", status="running", agent_id="agent-t2"),
	])
	sched._persist()

	raw = read_scheduler_checkpoint(tmp_path, "sess-ckpt")
	assert raw is not None
	assert checkpoint_is_incomplete(raw)
	assert raw.get("task_batch_id") == "batch-1"
	assert raw.get("ui_uids", {}).get("t2") == "t2:u"
	summary = checkpoint_summary(raw)
	assert summary["counts"]["done"] == 1
	assert summary["counts"]["running"] == 1

	sched2 = Scheduler(tmp_path, main_session_id="sess-ckpt")
	assert sched2.load_state() is True
	pending = sched2.prepare_for_resume()
	assert [t.id for t in pending] == ["t2"]
	assert sched2._tasks["t2"].status == "pending"
	assert sched2._tasks["t1"].status == "done"
	assert sched2._agent_ids.get("t2") == "agent-t2"

	clear_scheduler_checkpoint(tmp_path, "sess-ckpt")
	assert not scheduler_state_path(tmp_path, "sess-ckpt").is_file()
	assert read_scheduler_checkpoint(tmp_path, "sess-ckpt") is None
	assert checkpoint_is_incomplete(None) is False


@pytest.mark.asyncio
async def test_run_task_batch_resume_skips_done(tmp_path, monkeypatch):
	from engine.scheduler import (
		Scheduler,
		Task,
		TaskRunResult,
		read_scheduler_checkpoint,
		run_task_batch,
	)

	ran: list[str] = []

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		ran.append(t.id)
		t.last_result = f"resumed-{t.id}"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)

	# 预置未完成 checkpoint：t1 完成，t2 中途被打断。
	seed = Scheduler(
		tmp_path,
		main_session_id="sess-resume",
		agent_ids={"t1": "a1", "t2": "a2"},
		task_batch_id="batch-resume",
		ui_uids={"t1": "u1", "t2": "u2"},
	)
	seed.load([
		Task(id="t1", desc="first", status="done", last_result="already"),
		Task(id="t2", desc="second", status="running", depends_on=["t1"]),
	])
	seed._persist()

	out = await run_task_batch(
		None,
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-resume",
		resume=True,
	)
	by_id = {t.id: t for t in out}
	assert ran == ["t2"]
	assert by_id["t1"].status == "done"
	assert by_id["t1"].last_result == "already"
	assert by_id["t2"].status == "done"
	assert by_id["t2"].last_result == "resumed-t2"
	# 全成功后保留 awaiting_synthesis，供主回复合成中断后续跑。
	raw = read_scheduler_checkpoint(tmp_path, "sess-resume")
	assert raw is not None
	assert raw.get("batch_status") == "awaiting_synthesis"
	from engine.scheduler import checkpoint_awaiting_synthesis, checkpoint_is_incomplete

	assert checkpoint_awaiting_synthesis(raw) is True
	assert checkpoint_is_incomplete(raw) is True


def test_checkpoint_awaiting_synthesis_helpers():
	from engine.scheduler import checkpoint_awaiting_synthesis, checkpoint_is_incomplete

	raw = {
		"batch_status": "awaiting_synthesis",
		"tasks": [{"id": "t1", "status": "done"}],
	}
	assert checkpoint_awaiting_synthesis(raw) is True
	assert checkpoint_is_incomplete(raw) is True
	assert checkpoint_awaiting_synthesis({"tasks": [{"id": "t1", "status": "done"}]}) is True
	assert checkpoint_is_incomplete({"tasks": [{"id": "t1", "status": "pending"}]}) is True
	assert checkpoint_awaiting_synthesis({"tasks": [{"id": "t1", "status": "pending"}]}) is False


@pytest.mark.asyncio
async def test_subagent_hydrates_sidechain_on_resume(tmp_path, monkeypatch):
	"""同 agent_id 侧链有历史时，续跑应带上旧消息，而不是空开局。"""
	from engine.subagent_runner import run_subagent
	from msgtypes.events import FinalEvent
	from msgtypes.message import Message, user_message
	from session.record_transcript import record_transcript

	agent_id = "agent-t1-resume"
	main = "sess-hydrate"
	from engine.subagent_runner import _sidechain_path

	side = _sidechain_path(main, agent_id)
	side.parent.mkdir(parents=True, exist_ok=True)
	await record_transcript(
		[
			user_message("find docs"),
			Message(role="assistant", content="found docs/设计"),
		],
		session_id=agent_id,
		path=side,
		session_persistence_disabled=False,
		known_ids=set(),
	)

	captured: dict = {}

	class FakeClient:
		async def stream(self, messages, tools, abort):
			if False:
				yield None

	async def fake_query_loop(**kwargs):
		captured["store_len"] = len(kwargs["store"].items)
		captured["last"] = kwargs["store"].items[-1].content
		yield FinalEvent(text="done summarizing")

	monkeypatch.setattr("engine.query_loop.query_loop", fake_query_loop)

	class FakeAssembler:
		async def build_system(self, **kwargs):
			return "sys"

	rr = await run_subagent(
		workspace_root=tmp_path,
		agent_id=agent_id,
		task_prompt="[Resume] continue\n\nsummarize docs",
		tool_whitelist=["Read", "Glob"],
		model_client=FakeClient(),
		prompt_assembler=FakeAssembler(),
		write_store=None,
		main_session_id=main,
	)
	assert rr.conclusion == "done summarizing"
	assert captured["store_len"] >= 3  # prior 2 + resume nudge
	assert "[Resume] Continue." in str(captured["last"])


@pytest.mark.asyncio
async def test_run_task_batch_interrupt_leaves_checkpoint(tmp_path, monkeypatch):
	import asyncio
	from engine.scheduler import (
		Scheduler,
		Task,
		TaskRunResult,
		checkpoint_is_incomplete,
		read_scheduler_checkpoint,
		run_task_batch,
	)

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		if t.id == "t2":
			raise asyncio.CancelledError()
		t.last_result = "ok"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)

	tasks = [
		Task(id="t1", desc="first"),
		Task(id="t2", desc="second", depends_on=["t1"]),
	]
	with pytest.raises(asyncio.CancelledError):
		await run_task_batch(
			tasks,
			workspace_root=tmp_path,
			runtime_provider=lambda: object(),
			main_session_id="sess-cancel",
			task_batch_id="batch-cancel",
		)

	raw = read_scheduler_checkpoint(tmp_path, "sess-cancel")
	assert checkpoint_is_incomplete(raw)
	statuses = {t["id"]: t["status"] for t in (raw or {}).get("tasks") or []}
	assert statuses.get("t1") == "done"
	# 视取消时机，t2 可能运行中或待运行；两者都算未完成。
	assert statuses.get("t2") in ("pending", "running")


def test_checkpoint_persists_user_goal(tmp_path):
	from engine.scheduler import Scheduler, Task, read_scheduler_checkpoint

	sched = Scheduler(
		tmp_path,
		main_session_id="sess-goal",
		task_batch_id="batch-goal",
		user_goal="把侧边栏加号改成下拉菜单",
	)
	sched.load([Task(id="t1", desc="分析侧边栏", status="running")])
	sched._persist()
	raw = read_scheduler_checkpoint(tmp_path, "sess-goal")
	assert raw is not None
	assert raw.get("user_goal") == "把侧边栏加号改成下拉菜单"

	sched2 = Scheduler(tmp_path, main_session_id="sess-goal")
	assert sched2.load_state() is True
	assert sched2._user_goal == "把侧边栏加号改成下拉菜单"


def test_resume_cue_helpers():
	from server.routers.chat import (
		ChatMessage,
		_is_multi_agent_resume_cue,
		_previous_user_goal,
	)

	assert _is_multi_agent_resume_cue("继续")
	assert _is_multi_agent_resume_cue("continue")
	assert _is_multi_agent_resume_cue("请继续")
	assert not _is_multi_agent_resume_cue("继续把侧边栏改成非持久")
	assert not _is_multi_agent_resume_cue("分析侧边栏实现")

	msgs = [
		ChatMessage(role="user", content="把本地工作区改成非持久，加号下拉"),
		ChatMessage(role="assistant", content="好的"),
		ChatMessage(role="user", content="继续"),
	]
	assert _previous_user_goal(msgs) == "把本地工作区改成非持久，加号下拉"


def test_resume_cue_skips_checkpoint_ask_logic():
	"""续跑口令应直接 resume，不走 Ask；非口令才弹确认。"""
	from server.routers.chat import _is_multi_agent_resume_cue

	# 与 chat._multi_agent_stream 分支条件对齐
	assert _is_multi_agent_resume_cue("继续") is True
	assert _is_multi_agent_resume_cue("请继续") is True
	assert _is_multi_agent_resume_cue("接着做") is True
	assert _is_multi_agent_resume_cue("帮我看看侧边栏") is False
	assert _is_multi_agent_resume_cue("重新拆分任务") is False


def test_heuristic_split_dual_conflict_prompt():
	from engine.subagent_runner import (
		heuristic_split_tasks,
		user_requests_multi_tasks,
	)

	text = (
		"两个子任务都去改 README.md 的同一段「快速开始」，"
		"一个加安装步骤，一个加故障排查。故意同文件。"
	)
	assert user_requests_multi_tasks(text) is True
	tasks = heuristic_split_tasks(text)
	assert len(tasks) == 2
	assert all(t.depends_on == [] for t in tasks)
	assert any("README.md" in s for t in tasks for s in t.scope)


def test_heuristic_split_three_md_files():
	from engine.subagent_runner import (
		extract_target_files,
		heuristic_split_tasks,
		user_requests_multi_tasks,
	)

	text = (
		"在 docs/ 下新建三个短 md：agent-a.md / agent-b.md / agent-c.md，"
		"各写一段「本文件由谁创建」说明，互不改对方文件。"
	)
	assert user_requests_multi_tasks(text) is True
	files = extract_target_files(text)
	assert files == [
		"docs/agent-a.md",
		"docs/agent-b.md",
		"docs/agent-c.md",
	]
	tasks = heuristic_split_tasks(text)
	assert len(tasks) == 3
	assert [t.scope[0] for t in tasks] == files
	assert all(t.depends_on == [] for t in tasks)


def test_split_decompose_output_plan_then_json():
	from engine.subagent_runner import split_decompose_output

	raw = (
		"分配说明：\n"
		"按三个文件拆成并行任务，互不改对方。\n"
		'[{"id":"t1","desc":"写 a","depends_on":[],"scope":["a.md"]},'
		'{"id":"t2","desc":"写 b","depends_on":[],"scope":["b.md"]}]'
	)
	plan, blob = split_decompose_output(raw)
	assert "三个文件" in plan
	assert plan.startswith("按三个") or "并行" in plan
	assert blob.strip().startswith("[")
	assert '"t1"' in blob


def test_split_decompose_output_json_only():
	from engine.subagent_runner import split_decompose_output

	raw = '[{"id":"t1","desc":"only","depends_on":[],"scope":[]}]'
	plan, blob = split_decompose_output(raw)
	assert plan == ""
	assert blob.startswith("[")


def test_schedule_overlap_note_same_file():
	from engine.scheduler import Task
	from engine.subagent_runner import schedule_overlap_note, with_schedule_note

	tasks = [
		Task(id="t1", desc="a", scope=["gui/src/index.css"]),
		Task(id="t2", desc="b", scope=["gui/src/index.css"]),
	]
	note = schedule_overlap_note(tasks)
	assert "串行" in note
	assert "并行" not in note or "不会真正并行" in note
	plan = with_schedule_note("将任务拆分为两个并行子任务。", tasks)
	assert "串行" in plan


def test_schedule_overlap_note_different_files():
	from engine.scheduler import Task
	from engine.subagent_runner import schedule_overlap_note

	tasks = [
		Task(id="t1", desc="a", scope=["a.md"]),
		Task(id="t2", desc="b", scope=["b.md"]),
	]
	assert schedule_overlap_note(tasks) == ""


def test_format_heuristic_plan_mentions_parallel():
	from engine.scheduler import Task
	from engine.subagent_runner import format_heuristic_plan

	tasks = [
		Task(id="t1", desc="a", scope=["a.md"]),
		Task(id="t2", desc="b", scope=["b.md"]),
	]
	text = format_heuristic_plan(tasks)
	assert "2" in text
	assert "并行" in text


def test_plan_prefix_stops_at_json():
	from engine.subagent_runner import _plan_prefix_before_json

	plan, hit = _plan_prefix_before_json("先并行三个文件\n[{\"id\":\"t1\"}")
	assert hit is True
	assert "并行" in plan
	assert "[" not in plan


def test_plan_prefix_stops_at_lone_bracket():
	"""模型先吐完说明再吐 '[' 时，不能把 '[' 漏进主气泡。"""
	from engine.subagent_runner import _plan_prefix_before_json

	plan, hit = _plan_prefix_before_json("可以并行执行。\n[")
	assert hit is True
	assert plan.endswith("可以并行执行。\n") or "并行" in plan
	assert "[" not in plan


@pytest.mark.asyncio
async def test_decompose_keeps_llm_two_tasks_even_if_three_files(tmp_path):
	"""有 3 个文件名但模型拆出 2 个任务时，不得被启发式覆盖。"""
	from types import SimpleNamespace

	from engine.subagent_runner import decompose_tasks

	chunks = [
		SimpleNamespace(
			kind="text_delta",
			text=(
				"按相关度合并成两个任务。\n"
				'[{"id":"t1","desc":"写 a 与 b","depends_on":[],"scope":["docs/a.md","docs/b.md"]},'
				'{"id":"t2","desc":"写 c","depends_on":[],"scope":["docs/c.md"]}]'
			),
		)
	]

	class _Client:
		async def stream(self, *_a, **_k):
			for c in chunks:
				yield c

	result = await decompose_tasks(
		"新建 docs/a.md docs/b.md docs/c.md 三个短文件",
		model_client=_Client(),
		workspace_root=tmp_path,
	)
	assert result.used_heuristic is False
	assert len(result.tasks) == 2
	assert "两个任务" in result.plan_text or "合并" in result.plan_text


@pytest.mark.asyncio
async def test_event_driven_dag_starts_unblocked_before_slow_sibling(tmp_path, monkeypatch):
	"""t3 depends only on short t2; must start before long independent t1 finishes."""
	import time
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	started: dict[str, float] = {}
	finished: dict[str, float] = {}

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		started[t.id] = time.monotonic()
		await asyncio.sleep(0.12 if t.id == "t1" else 0.02)
		finished[t.id] = time.monotonic()
		t.last_result = f"ok-{t.id}"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)
	out = await run_task_batch(
		[
			Task(id="t1", desc="long", scope=["a.ts"]),
			Task(id="t2", desc="short", scope=["b.ts"]),
			Task(id="t3", desc="after t2", depends_on=["t2"], scope=["c.ts"]),
		],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-wave",
	)
	assert all(t.status == "done" for t in out)
	assert started["t3"] < finished["t1"]


@pytest.mark.asyncio
async def test_same_scope_tasks_do_not_overlap(tmp_path, monkeypatch):
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	active: set[str] = set()
	overlap = False

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		nonlocal overlap
		if active:
			overlap = True
		active.add(t.id)
		await asyncio.sleep(0.04)
		active.discard(t.id)
		t.last_result = "ok"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)
	out = await run_task_batch(
		[
			Task(id="t1", desc="a", scope=["src/foo.ts"]),
			Task(id="t2", desc="b", scope=["src/foo.ts"]),
		],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-scope",
	)
	assert all(t.status == "done" for t in out)
	assert overlap is False


@pytest.mark.asyncio
async def test_task_timeout_marks_failed(tmp_path, monkeypatch):
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		await asyncio.sleep(1.0)
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)
	out = await run_task_batch(
		[Task(id="t1", desc="hang", timeout_s=0.08)],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-timeout",
	)
	assert out[0].status == "failed"
	assert out[0].failure_reason == "timeout"


@pytest.mark.asyncio
async def test_batch_abort_stops_running_task(tmp_path, monkeypatch):
	from engine.abort import AbortController
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	abort = AbortController()

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		if t.id == "t1":
			await asyncio.sleep(0.02)
			t.last_result = "ok"
			return TaskRunResult(ok=True, reason="ok")
		for _ in range(50):
			if abort is not None and abort.aborted:
				return TaskRunResult(ok=False, reason="interrupted")
			await asyncio.sleep(0.02)
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)

	async def killer():
		await asyncio.sleep(0.05)
		abort.abort()

	asyncio.create_task(killer())
	out = await run_task_batch(
		[
			Task(id="t1", desc="first", scope=["a.ts"]),
			Task(id="t2", desc="second", depends_on=["t1"], scope=["b.ts"]),
		],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-abort",
		abort=abort,
	)
	by_id = {t.id: t for t in out}
	assert by_id["t1"].status == "done"
	assert by_id["t2"].status in ("pending", "failed")


def test_repair_task_graph_drops_bad_edges_and_caps():
	from engine.scheduler import Task, repair_task_graph

	tasks = [
		Task(id="t1", desc="a", depends_on=["missing"], required_tools=["Bash"]),
		Task(id="t2", desc="b", depends_on=["t1"]),
		Task(id="t3", desc="c", depends_on=["t3"]),
	]
	out = repair_task_graph(tasks, max_tasks=8)
	assert [t.id for t in out] == ["t1", "t2", "t3"]
	assert out[0].depends_on == []
	assert "Bash" in out[0].required_tools  # Phase 2：Bash 不再被 repair 剔除
	# Memory / Agent 仍剔除
	tasks2 = [
		Task(id="m1", desc="x", required_tools=["Memory", "Agent", "Read"]),
	]
	out2 = repair_task_graph(tasks2, max_tasks=8)
	assert "Memory" not in out2[0].required_tools
	assert "Agent" not in out2[0].required_tools
	assert "Read" in out2[0].required_tools


def test_checkpoint_is_per_session(tmp_path):
	from engine.scheduler import Scheduler, Task, read_scheduler_checkpoint

	a = Scheduler(tmp_path, main_session_id="sess-a", user_goal="goal-a")
	a.load([Task(id="t1", desc="a", status="running")])
	a._persist()
	b = Scheduler(tmp_path, main_session_id="sess-b", user_goal="goal-b")
	b.load([Task(id="t9", desc="b", status="pending")])
	b._persist()
	ra = read_scheduler_checkpoint(tmp_path, "sess-a")
	rb = read_scheduler_checkpoint(tmp_path, "sess-b")
	assert ra is not None and rb is not None
	assert ra["user_goal"] == "goal-a"
	assert rb["user_goal"] == "goal-b"
	assert ra["tasks"][0]["id"] == "t1"
	assert rb["tasks"][0]["id"] == "t9"


def test_batch_whitelist_frozen_across_tasks(tmp_path):
	from engine.scheduler import Scheduler, Task, batch_tool_whitelist

	tasks = [
		Task(id="t1", desc="a", required_tools=["Grep"]),
		Task(id="t2", desc="b", required_tools=["Glob"]),
	]
	frozen = batch_tool_whitelist(tasks)
	assert "Grep" in frozen and "Glob" in frozen and "JournalQuery" in frozen
	sched = Scheduler(str(tmp_path))
	sched.load(tasks)
	assert sched.whitelist_for(tasks[0]) == sched.whitelist_for(tasks[1])
	assert sched.whitelist_for(tasks[0]) == frozen


def test_write_store_syntax_incremental(tmp_path, monkeypatch):
	import memory.journal as j
	from engine.write_store import ChangeIntent, EditOp, WriteStore, _content_hash

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "bad.py"
	ok = store.submit_sync(
		ChangeIntent(agent_id="a", ops=[EditOp(path=str(p), new_content="def f(:\n")])
	)
	assert ok.ok
	assert ok.syntax_valid is False
	canon = str(p.resolve())
	good = store.submit_sync(
		ChangeIntent(
			agent_id="a",
			base_hashes={canon: _content_hash(p)},
			ops=[EditOp(path=str(p), new_content="def f():\n    return 1\n")],
		)
	)
	assert good.ok
	assert good.syntax_valid is True


def test_write_store_rejects_missing_read(tmp_path, monkeypatch):
	import memory.journal as j
	from engine.write_store import ChangeIntent, EditOp, WriteStore

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "a.py"
	p.write_text("x = 1\n", encoding="utf-8")
	bad = store.submit_sync(
		ChangeIntent(
			agent_id="a",
			base_hashes={},
			ops=[EditOp(path=str(p), new_content="x = 2\n")],
		)
	)
	assert not bad.ok
	assert bad.reason == "missing_read"
	assert p.read_text(encoding="utf-8") == "x = 1\n"


@pytest.mark.asyncio
async def test_empty_scope_tasks_do_not_overlap(tmp_path, monkeypatch):
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch, scope_conflicts

	assert scope_conflicts(Task(id="a", desc="a"), Task(id="b", desc="b"))
	active: set[str] = set()
	overlap = False

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		nonlocal overlap
		if active:
			overlap = True
		active.add(t.id)
		await asyncio.sleep(0.04)
		active.discard(t.id)
		t.last_result = "ok"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)
	out = await run_task_batch(
		[Task(id="t1", desc="a"), Task(id="t2", desc="b")],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-empty-scope",
	)
	assert all(t.status == "done" for t in out)
	assert overlap is False


@pytest.mark.asyncio
async def test_upstream_handoff_injected_into_prompt(tmp_path, monkeypatch):
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	prompts: dict[str, str] = {}

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		prompts[t.id] = self._task_prompt_with_upstream(t)
		t.last_result = f"result-{t.id}"
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)
	await run_task_batch(
		[
			Task(id="t1", desc="analyze", scope=["a.ts"]),
			Task(id="t2", desc="implement", depends_on=["t1"], scope=["b.ts"]),
		],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-handoff",
	)
	assert "result-t1" in prompts["t2"]
	assert "Context from completed dependencies" in prompts["t2"]


def test_prepare_for_resume_interrupted_pending_gets_hint(tmp_path):
	from engine.scheduler import Scheduler, Task

	sched = Scheduler(tmp_path, main_session_id="sess-hint")
	sched.load([
		Task(id="t1", desc="edit foo", status="done", last_result="ok"),
		Task(
			id="t2",
			desc="edit bar",
			status="pending",
			failure_reason="interrupted",
			files_touched=["src/bar.ts"],
		),
	])
	pending = sched.prepare_for_resume()
	assert [t.id for t in pending] == ["t2"]
	assert sched._tasks["t2"].desc.startswith("[Resume]")
	assert "edit bar" in sched._tasks["t2"].desc


def test_failed_batch_keeps_checkpoint_for_retry(tmp_path, monkeypatch):
	from engine.scheduler import (
		Scheduler,
		Task,
		TaskRunResult,
		checkpoint_is_incomplete,
		read_scheduler_checkpoint,
		run_task_batch,
	)

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		if t.id == "t1":
			t.last_result = "ok"
			return TaskRunResult(ok=True, reason="ok")
		return TaskRunResult(ok=False, reason="timeout")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)
	out = asyncio.run(
		run_task_batch(
			[
				Task(id="t1", desc="ok", scope=["a.ts"]),
				Task(id="t2", desc="fail", scope=["b.ts"]),
			],
			workspace_root=tmp_path,
			runtime_provider=lambda: object(),
			main_session_id="sess-keep-fail",
		)
	)
	assert out[0].status == "done"
	assert out[1].status == "failed"
	raw = read_scheduler_checkpoint(tmp_path, "sess-keep-fail")
	assert raw is not None
	sched = Scheduler(tmp_path, main_session_id="sess-keep-fail")
	assert sched.load_state()
	pending = sched.prepare_for_resume()
	assert "t2" in [t.id for t in pending]
	assert checkpoint_is_incomplete(
		{"tasks": [t.to_dict() for t in sched._tasks.values()]}
	)


def test_prepare_for_resume_skips_non_retryable_failed(tmp_path):
	from engine.scheduler import Scheduler, Task

	sched = Scheduler(tmp_path, main_session_id="sess-no-retry")
	sched.load([
		Task(id="t1", desc="ok", status="done"),
		Task(id="t2", desc="boom", status="failed", failure_reason="boom"),
		Task(id="t3", desc="dep", status="failed", failure_reason="dependency_failed"),
	])
	pending = sched.prepare_for_resume()
	assert pending == []
	assert sched._tasks["t2"].status == "failed"
	assert sched._tasks["t3"].status == "failed"


def test_repair_task_graph_breaks_cycle_without_clearing_all():
	from engine.scheduler import Task, repair_task_graph, toposort

	tasks = [
		Task(id="t1", desc="a", depends_on=["t2"]),
		Task(id="t2", desc="b", depends_on=["t1"]),
		Task(id="t3", desc="c", depends_on=["t1"]),
	]
	out = repair_task_graph(tasks, max_tasks=8)
	assert toposort(out)
	# 破环后仍应保留至少一条非环边（t3→t1），不是清空全部
	assert any(t.depends_on for t in out)


def test_journal_prefix_matches_relative_vs_absolute(tmp_path, monkeypatch):
	from memory.journal import ChangeRecord, _path_matches_prefix, format_changes_for_agent
	import memory.journal as j

	abs_path = str((tmp_path / "src" / "foo.ts").resolve())
	assert _path_matches_prefix(
		abs_path, "src/foo.ts", workspace_root=str(tmp_path)
	)
	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	j.record_change(
		"ws",
		ChangeRecord(
			seq=0,
			agent_id="a",
			path=abs_path,
			action="edit",
			file_hash_after="sha256:x",
			ts=1.0,
			brief="x",
		),
	)
	rows = j.recent_changes(
		"ws", path_prefix="src/foo.ts", workspace_root=str(tmp_path), limit=10
	)
	assert len(rows) == 1
	assert "foo.ts" in format_changes_for_agent(rows)


@pytest.mark.asyncio
async def test_batch_abort_leaves_interrupted_pending(tmp_path, monkeypatch):
	from engine.abort import AbortController
	from engine.scheduler import Scheduler, Task, TaskRunResult, run_task_batch

	abort = AbortController()

	async def fake_run_task(self, t, *, patch_attempt=0, abort=None):
		for _ in range(40):
			if abort is not None and abort.aborted:
				return TaskRunResult(ok=False, reason="interrupted")
			await asyncio.sleep(0.02)
		return TaskRunResult(ok=True, reason="ok")

	monkeypatch.setattr(Scheduler, "_run_task", fake_run_task)

	async def killer():
		await asyncio.sleep(0.05)
		abort.abort()

	asyncio.create_task(killer())
	out = await run_task_batch(
		[Task(id="t1", desc="hang", scope=["a.ts"])],
		workspace_root=tmp_path,
		runtime_provider=lambda: object(),
		main_session_id="sess-cancel-synth",
		abort=abort,
	)
	assert out[0].status == "pending"
	assert out[0].failure_reason == "interrupted"



def test_write_store_crlf_file_roundtrip(tmp_path, monkeypatch):
	"""CRLF 文件经 store 写入：base(归一化文本哈希) 必须命中、换行形态保持。

	回归：_content_hash 曾按磁盘原始字节哈希，与 _content_hash_text(Read
	归一化后的 LF 文本) 永远对不上 → CRLF 文件首次子 agent 写必报 stale。
	"""
	import memory.journal as j
	from engine.write_store import ChangeIntent, EditOp, WriteStore, _content_hash_text
	from tools.fileio.text import read_text_file

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "crlf.py"
	p.write_bytes(b"x = 1\r\ny = 2\r\n")
	canon = str(p.resolve())

	# 模拟生产端 base 来源：Read 归一化文本的哈希
	base = _content_hash_text(read_text_file(str(p))[0])
	ok = store.submit_sync(
		ChangeIntent(
			agent_id="a",
			base_hashes={canon: base},
			ops=[EditOp(path=str(p), new_content="x = 9\r\ny = 2\r\n")],
			encoding="utf-8",
		)
	)
	assert ok.ok, ok.detail
	# newline=''：调用方给的 CRLF 形态原样落盘，不做平台翻译
	assert p.read_bytes() == b"x = 9\r\ny = 2\r\n"


def test_write_store_lf_not_translated_on_windows(tmp_path, monkeypatch):
	"""LF 文件经 store 写入后不得被 Python 翻译成 CRLF（回归 _atomic_write）。"""
	import memory.journal as j
	from engine.write_store import ChangeIntent, EditOp, WriteStore

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "lf.py"
	ok = store.submit_sync(
		ChangeIntent(
			agent_id="a",
			ops=[EditOp(path=str(p), new_content="a = 1\nb = 2\n")],
		)
	)
	assert ok.ok
	assert p.read_bytes() == b"a = 1\nb = 2\n"


def test_write_store_edit_op_applies_to_crlf(tmp_path, monkeypatch):
	"""edit op（old_string/new_string）在 CRLF 文件上可应用：读盘侧用与 Read
	同源的归一化文本，模型的 LF old_string 不再假 conflict。"""
	import memory.journal as j
	from engine.write_store import ChangeIntent, EditOp, WriteStore, _content_hash
	from tools.fileio.text import read_text_file

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "crlf_edit.py"
	p.write_bytes(b"x = 1\r\ny = 2\r\n")
	canon = str(p.resolve())
	ok = store.submit_sync(
		ChangeIntent(
			agent_id="a",
			base_hashes={canon: _content_hash(p)},
			ops=[EditOp(path=str(p), old_string="y = 2", new_string="y = 3")],
		)
	)
	assert ok.ok, ok.detail
	text, _endings, _enc = read_text_file(str(p))
	assert text == "x = 1\ny = 3\n"


def test_write_store_utf16_encoding_preserved(tmp_path, monkeypatch):
	"""UTF-16 文件经 store 写入：文本等价、编码不被重写成 UTF-8。"""
	import memory.journal as j
	from engine.write_store import ChangeIntent, EditOp, WriteStore, _content_hash_text
	from tools.fileio.text import read_text_file

	monkeypatch.setattr(j, "_changes_path", lambda ws: Path(tmp_path) / f"{ws}.jsonl")
	store = WriteStore(tmp_path)
	p = tmp_path / "u16.txt"
	p.write_bytes("x = 1\n".encode("utf-16"))
	base = _content_hash_text(read_text_file(str(p))[0])
	ok = store.submit_sync(
		ChangeIntent(
			agent_id="a",
			base_hashes={str(p.resolve()): base},
			ops=[EditOp(path=str(p), new_content="x = 2\n")],
			encoding="utf-16",
		)
	)
	assert ok.ok, ok.detail
	text, _endings, enc = read_text_file(str(p))
	assert text == "x = 2\n"
	assert enc == "utf-16-le"
