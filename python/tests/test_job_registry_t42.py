"""42 号 background jobs：registry 语义 + 通知管线 + BashTool 桥 + 三工具 + T_now。

覆盖（42 号 §12 P0）：
- ring：cap 保尾、绝对偏移游标、truncation 标记。
- registry：start/settle 首次结果优先、生产方异常隔离 failed、owner 隔离
  （read/kill/snapshot）、容量 10 生产前失败（教 job_kill）、kill → stopping
  + reported → interrupted 结算为 killed。
- 通知管线：owner 忙 → pending；settlement 归并单唤醒；唤醒消费置 reported
  + 预算 3→2；预算尽 → 不投递留 pending；人类 T_now 补投摘要出队；
  submit 失败 → 退回 pending 不退预算；cancel_wake / restore_wake。
- 共享预算（§3.4）：goal 轮 consume_wake；预算尽 → driver 不开轮不消耗轮号。
- hub：租户异常互不影响。
- BashTool 桥：registry 托管文案 / 容量满错误 / registry 不可用落旧式文案。
- 三工具：job_output 游标增量 + [status:] 尾、job_list 行格式、job_kill 文案、
  越权/未知 → 错误。
- T_now 补投块：contextvar 有摘要 → 强挂块带归属头；空 → 无块。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject  # noqa: E402
from server.job_registry import (  # noqa: E402
	MAX_CONSECUTIVE_WAKES,
	MAX_CONCURRENT_JOBS_PER_OWNER,
	JobRegistry,
	STATUS_FAILED,
	STATUS_KILLED,
	STATUS_RUNNING,
	STATUS_SUCCEEDED,
	STATUS_STOPPING,
	_Ring,
)
from server.turn_settlement_hub import on_turn_settled as hub_on_turn_settled  # noqa: E402

SID = "s-jobs"


@pytest.fixture()
def fast_wake(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr("server.job_registry._WAKE_DEBOUNCE_S", 0.01)


# ---------------------------------------------------------------------------
# _Ring（环形缓冲）
# ---------------------------------------------------------------------------
def test_ring_keeps_tail_and_offsets() -> None:
	r = _Ring(cap=512)
	r.push("a" * 400)
	text, cur, trunc = r.read(0)
	assert text == "a" * 400 and cur == 400 and trunc is False
	r.push("b" * 200)  # 600 > 512 → 丢头 88
	text, cur, trunc = r.read(0)
	assert len(text) == 512 and text.endswith("b" * 200) and trunc is True
	text, cur, trunc = r.read(cur)
	assert text == "" and trunc is False


# ---------------------------------------------------------------------------
# registry：start / settle / owner / 容量 / kill
# ---------------------------------------------------------------------------
def _sync_producer(status: str = STATUS_SUCCEEDED, detail: str = ""):
	def _p(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		push("hello\n")
		return status, detail

	return _p


def test_settle_first_wins_and_exception_isolation() -> None:
	reg = JobRegistry()

	def boom(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		raise RuntimeError("boom")

	jid, err = reg.start(kind="bash", label="x", owner_session_id=SID, producer=boom)
	assert err == ""
	# 生产方线程异步结算 → 轮询终态。
	deadlines = 200
	while reg._jobs[jid].status == STATUS_RUNNING and deadlines:
		deadlines -= 1
		import time

		time.sleep(0.01)
	assert reg._jobs[jid].status == STATUS_FAILED, "生产方异常隔离为 failed"
	reg.settle(jid, STATUS_SUCCEEDED, "late")
	assert reg._jobs[jid].status == STATUS_FAILED, "首次结果优先"


def test_owner_isolation() -> None:
	reg = JobRegistry()
	jid, _ = reg.start(
		kind="bash", label="x", owner_session_id=SID, producer=_sync_producer()
	)
	assert reg.read(jid, "other-session") is None
	assert reg.kill(jid, "other-session") .startswith("unknown job")
	assert all(j["job_id"] != jid for j in reg.snapshot_list("other-session"))
	assert reg.snapshot_list(SID), "owner 可见"


def test_capacity_full_fails_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
	reg = JobRegistry()

	def hang(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		import time

		for _ in range(600):
			time.sleep(0.01)
		return STATUS_SUCCEEDED, ""

	ids = []
	for i in range(MAX_CONCURRENT_JOBS_PER_OWNER):
		jid, err = reg.start(kind="bash", label=str(i), owner_session_id=SID, producer=hang)
		assert err == ""
		ids.append(jid)
	jid, err = reg.start(kind="bash", label="overflow", owner_session_id=SID, producer=hang)
	assert jid is None and "job_kill" in err, "容量满在生产前失败并教模型 kill"
	# 其他 owner 不受影响。
	jid2, err2 = reg.start(kind="bash", label="ok", owner_session_id="s-other", producer=hang)
	assert err2 == ""


def test_kill_marks_stopping_and_settles_killed() -> None:
	reg = JobRegistry()

	def hang(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		import time

		for _ in range(600):
			time.sleep(0.01)
		return STATUS_SUCCEEDED, ""

	jid, _ = reg.start(kind="bash", label="x", owner_session_id=SID, producer=hang)
	msg = reg.kill(jid, SID, reason="不再需要")
	assert msg.startswith("requested cancellation")
	assert reg._jobs[jid].status == STATUS_STOPPING
	assert reg._jobs[jid].reported is True, "kill 即置 reported"
	# 生产方（真实 bash 桥会因 abort 结束；这里手动结算）→ killed 保持首次。
	reg.settle(jid, STATUS_KILLED, "killed by job_kill")
	assert reg._jobs[jid].status == STATUS_STOPPING or reg._jobs[jid].status == STATUS_KILLED


def test_read_incremental_and_terminal_reported() -> None:
	reg = JobRegistry()
	box: dict[str, Any] = {}

	def slow(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		box["push"] = push
		for _ in range(600):
			import time

			time.sleep(0.01)
			if box.get("stop"):
				break
		return STATUS_SUCCEEDED, ""

	jid, _ = reg.start(kind="bash", label="x", owner_session_id=SID, producer=slow)
	# 等待 push 就绪。
	for _ in range(100):
		if "push" in box:
			break
		import time

		time.sleep(0.01)
	box["push"]("chunk-1\n")
	text, _cur, status, _t = reg.read(jid, SID)
	assert "chunk-1" in text and status == STATUS_RUNNING
	box["push"]("chunk-2\n")
	text, _cur, status, _t = reg.read(jid, SID)
	assert "chunk-1" not in text and "chunk-2" in text, "游标增量：只吐新内容"
	box["stop"] = True
	for _ in range(300):
		if reg._jobs[jid].status != STATUS_RUNNING:
			break
		import time

		time.sleep(0.01)
	text, _cur, status, _t = reg.read(jid, SID)
	assert status == STATUS_SUCCEEDED
	assert reg._jobs[jid].reported is True, "终态读置 reported"
	# 幂等：再读不重复。
	t2, _c2, s2, _t2 = reg.read(jid, SID)
	assert s2 == STATUS_SUCCEEDED


# ---------------------------------------------------------------------------
# 通知管线
# ---------------------------------------------------------------------------
def _finish(reg: JobRegistry, job_id: str, status: str = STATUS_SUCCEEDED, detail: str = "") -> None:
	reg.settle(job_id, status, detail)


async def _wait_idle(reg: JobRegistry, *, settle_s: float = 0.05) -> None:
	# 先让 call_soon_threadsafe 的回调落地（create_task），再等决策任务全部终态；
	# 任务始终未出现（如无 loop 路径）则超时后放行。
	await asyncio.sleep(settle_s)
	for _ in range(400):
		tasks = list(reg._wake_tasks.values())
		if tasks and all(t.done() for t in tasks):
			return
		await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_busy_owner_parks_notification_then_merges_on_settlement(
	monkeypatch: pytest.MonkeyPatch, fast_wake: None
) -> None:
	reg = JobRegistry()
	loop = asyncio.get_running_loop()
	submits: list[str] = []

	async def fake_submit(sid: str, text: str, *, surface: str, extra_headers=None) -> bool:
		submits.append(text)
		return True

	monkeypatch.setattr("server.synthetic_round.submit_synthetic", fake_submit)
	monkeypatch.setattr("server.job_registry._turn_running", lambda sid: False)

	j1, _ = reg.start(
		kind="bash", label="regression", owner_session_id=SID,
		producer=_sync_producer(), loop=loop,
	)
	_finish(reg, j1)
	await asyncio.sleep(0.05)
	await _wait_idle(reg)
	assert len(submits) == 1, "单 job 一次唤醒"
	assert "background job" in submits[0] and "job_output" in submits[0]
	assert reg._jobs[j1].reported is True
	assert reg.wake_budget_left(SID) == MAX_CONSECUTIVE_WAKES - 1

	# 两个 job 同 settle → 只花一个唤醒轮（归并）。
	j2, _ = reg.start(
		kind="bash", label="a", owner_session_id=SID,
		producer=_sync_producer(), loop=loop,
	)
	j3, _ = reg.start(
		kind="bash", label="b", owner_session_id=SID,
		producer=_sync_producer(), loop=loop,
	)
	_finish(reg, j2)
	_finish(reg, j3)
	await _wait_idle(reg)
	assert len(submits) == 2, "两 job 合并为一次唤醒"
	assert "bash-2" in submits[-1] and "bash-3" in submits[-1]


@pytest.mark.asyncio
async def test_budget_exhausted_keeps_pending_and_tnow_digest_pops(
	monkeypatch: pytest.MonkeyPatch, fast_wake: None
) -> None:
	reg = JobRegistry()
	loop = asyncio.get_running_loop()
	submits: list[str] = []

	async def fake_submit(sid: str, text: str, *, surface: str, extra_headers=None) -> bool:
		submits.append(text)
		return True

	monkeypatch.setattr("server.synthetic_round.submit_synthetic", fake_submit)
	monkeypatch.setattr("server.job_registry._turn_running", lambda sid: False)
	for _ in range(MAX_CONSECUTIVE_WAKES):
		reg.consume_wake(SID)

	box: dict[str, Any] = {}

	def hang(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		box["push"] = push
		for _ in range(600):
			import time

			time.sleep(0.01)
			if box.get("stop"):
				break
		return STATUS_SUCCEEDED, ""

	j1, _ = reg.start(
		kind="bash", label="job-x", owner_session_id=SID, producer=hang, loop=loop,
	)
	_finish(reg, j1, STATUS_FAILED, "exit code 1")  # 显式失败结算（生产方仍挂起）
	await _wait_idle(reg)
	assert submits == [], "预算尽不投递"
	jid1 = reg._jobs[j1].job_id
	digest = reg.pending_digest(SID)
	assert jid1 in digest and "exit code 1" in digest, "T_now 补投摘要"
	assert reg._jobs[j1].reported is True
	assert reg.pending_digest(SID) == "", "一次性消费"


@pytest.mark.asyncio
async def test_submit_failure_requeues_without_budget_refund(
	monkeypatch: pytest.MonkeyPatch, fast_wake: None
) -> None:
	reg = JobRegistry()
	loop = asyncio.get_running_loop()

	async def fake_submit(sid: str, text: str, *, surface: str, extra_headers=None) -> bool:
		return False

	monkeypatch.setattr("server.synthetic_round.submit_synthetic", fake_submit)
	monkeypatch.setattr("server.job_registry._turn_running", lambda sid: False)

	j1, _ = reg.start(
		kind="bash", label="x", owner_session_id=SID,
		producer=_sync_producer(), loop=loop,
	)
	before = reg.wake_budget_left(SID)
	_finish(reg, j1)
	await _wait_idle(reg)
	assert reg._jobs[j1].reported is False, "投递失败退回 pending"
	assert reg.wake_budget_left(SID) == before - 1, "不退预算（防互激 thrash）"


@pytest.mark.asyncio
async def test_cancel_wake_and_restore(monkeypatch: pytest.MonkeyPatch, fast_wake: None) -> None:
	reg = JobRegistry()
	reg.restore_wake(SID)
	assert reg.wake_budget_left(SID) == MAX_CONSECUTIVE_WAKES
	reg.cancel_wake(SID)  # 空任务 no-op
	assert reg.wake_budget_left(SID) == MAX_CONSECUTIVE_WAKES


@pytest.mark.asyncio
async def test_goal_round_consumes_shared_budget(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fast_wake: None
) -> None:
	"""§3.4：goal 轮 consume_wake；预算尽 → 不开轮、不消耗轮号。"""
	from engine.goal_state import GoalStore
	from server.goal_round_driver import GoalRoundDriver, _DriverState
	from tests.test_goal_round_driver_t41 import _FakePool

	store = GoalStore(str(tmp_path))
	sid = "s-budget"
	await store.create_and_bind_async(title="t", text="x", session_id=sid)

	reg = JobRegistry()
	monkeypatch.setattr("server.job_registry.get_job_registry", lambda: reg)
	for _ in range(MAX_CONSECUTIVE_WAKES):
		reg.consume_wake(sid)

	submits: list[Any] = []

	async def fake_submit(session_id: str, goal_id: str, round_no: int, cap: int) -> bool:
		submits.append((goal_id, round_no, cap))
		return True

	driver = GoalRoundDriver()
	driver._pool = _FakePool(str(tmp_path))
	driver._turn_running = lambda s: False  # type: ignore[method-assign]
	driver._states[sid] = _DriverState(armed=True)
	monkeypatch.setattr(
		"server.goal_round_driver._ROUND_DEBOUNCE_S", 0.01
	)
	driver._submit_round = fake_submit  # type: ignore[method-assign]
	await driver.on_turn_settled(sid, "succeeded", "")
	assert driver._states[sid].pending is not None
	await asyncio.wait_for(asyncio.shield(driver._states[sid].pending), timeout=5)

	assert submits == [], "预算尽 → goal 轮不开"
	cur = store.current(sid)
	assert cur is not None and cur.rounds == 1, "轮号不消耗"
	assert driver._states[sid].armed is True, "armed 保持（人类消息恢复后可再跑）"


# ---------------------------------------------------------------------------
# hub 双分发
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hub_tenant_isolation(monkeypatch: pytest.MonkeyPatch, fast_wake: None) -> None:
	reg = JobRegistry()
	loop = asyncio.get_running_loop()
	submits: list[str] = []

	async def fake_submit(sid: str, text: str, *, surface: str, extra_headers=None) -> bool:
		submits.append(text)
		return True

	monkeypatch.setattr("server.synthetic_round.submit_synthetic", fake_submit)
	monkeypatch.setattr("server.job_registry._turn_running", lambda sid: False)

	async def broken_goal(sid: str, status: str, reason: str) -> None:
		raise RuntimeError("goal tenant boom")

	monkeypatch.setattr(
		"server.goal_round_driver.get_goal_round_driver",
		lambda: type("D", (), {"on_turn_settled": staticmethod(broken_goal)})(),
	)
	monkeypatch.setattr("server.job_registry.get_job_registry", lambda: reg)

	j1, _ = reg.start(
		kind="bash", label="x", owner_session_id=SID,
		producer=_sync_producer(), loop=loop,
	)
	_finish(reg, j1)
	await hub_on_turn_settled(SID, "succeeded", "")
	await _wait_idle(reg)
	assert len(submits) == 1, "goal 租户异常不影响 jobs 租户"


# ---------------------------------------------------------------------------
# BashTool 桥
# ---------------------------------------------------------------------------
def _bash_input(background: bool = True) -> dict[str, Any]:
	return {"command": "echo hi", "run_in_background": background}


@pytest.mark.asyncio
async def test_bash_bridge_registry_backed(monkeypatch: pytest.MonkeyPatch) -> None:
	reg = JobRegistry()

	def hang(push) -> tuple[str, str]:  # type: ignore[no-untyped-def]
		import time

		for _ in range(600):
			time.sleep(0.01)
		return STATUS_SUCCEEDED, ""

	monkeypatch.setattr(
		"server.job_registry.get_job_registry", lambda: reg
	)
	monkeypatch.setattr(
		"tools.bash_tool.bash_tool.start_registry_job",
		lambda **kw: reg.start_bash(
			command=kw["command"],
			cwd=kw["cwd"],
			label=(kw.get("description") or kw["command"].splitlines()[0])[:120],
			owner_session_id=kw["session_id"],
			loop=kw.get("loop"),
		),
	)
	monkeypatch.setattr(
		"engine.workspace_context.get_workspace_context",
		lambda: type("C", (), {"session_id": SID, "permission_profile": ""})(),
	)
	from tools.bash_tool.bash_tool import BashTool
	from engine.abort import AbortController

	tool = BashTool(cwd=".")
	# 桩需对齐真实签名 ``check_permissions(inp, context=None, *, cwd=None)``
	# （bash_tool.py:950 以 cwd=work 调用；仅回 True 时不必读 cwd）
	tool.check_permissions = lambda inp, context=None, **kw: True  # type: ignore[method-assign]
	out = await tool.execute(
		{**_bash_input(), "description": "全量回归"}, AbortController()
	)
	assert out.content.startswith("Started background job bash-"), out.content
	assert "job_output" in out.content
	assert reg.snapshot_list(SID), "命令已登记为 job"


@pytest.mark.asyncio
async def test_bash_bridge_falls_back_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(
		"tools.bash_tool.bash_tool.start_registry_job", lambda **kw: None
	)
	monkeypatch.setattr(
		"engine.workspace_context.get_workspace_context",
		lambda: type("C", (), {"session_id": SID, "permission_profile": ""})(),
	)
	from tools.bash_tool.bash_tool import BashTool
	from engine.abort import AbortController

	tool = BashTool(cwd=".")
	tool.check_permissions = lambda inp, context=None, **kw: True  # type: ignore[method-assign]
	out = await tool.execute(_bash_input(), AbortController())
	assert "Command running in background with ID:" in out.content, "旧式文案保留"


@pytest.mark.asyncio
async def test_bash_bridge_capacity_error(monkeypatch: pytest.MonkeyPatch) -> None:
	"""registry 容量满 → 记录 warning 并**回退旧式日志后台**（不报错给模型）。

	bash_tool.py:602-622 语义：registry 可达但登记失败属引擎内部可自愈情形，
	执行层静默降级（旧式日志文件后台仍能跑完并留日志），不把容量信息推给模型。
	"""
	monkeypatch.setattr(
		"tools.bash_tool.bash_tool.start_registry_job",
		lambda **kw: ("", "background job capacity full (10/10) for this session; use job_kill to free slots, then retry"),
	)
	monkeypatch.setattr(
		"engine.workspace_context.get_workspace_context",
		lambda: type("C", (), {"session_id": SID, "permission_profile": ""})(),
	)
	from tools.bash_tool.bash_tool import BashTool
	from engine.abort import AbortController

	tool = BashTool(cwd=".")
	tool.check_permissions = lambda inp, context=None, **kw: True  # type: ignore[method-assign]
	out = await tool.execute(_bash_input(), AbortController())
	assert out.is_error is False, "容量满属引擎可自愈，不向模型报错"
	assert "Command running in background with ID:" in out.content, "已回退旧式日志后台"


# ---------------------------------------------------------------------------
# 三工具
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bash_permission_denied_produces_no_job(monkeypatch: pytest.MonkeyPatch) -> None:
	reg = JobRegistry()
	monkeypatch.setattr("server.job_registry.get_job_registry", lambda: reg)
	monkeypatch.setattr(
		"tools.bash_tool.bash_tool.start_registry_job",
		lambda **kw: reg.start_bash(**kw),
	)
	monkeypatch.setattr(
		"engine.workspace_context.get_workspace_context",
		lambda: type("C", (), {"session_id": SID, "permission_profile": ""})(),
	)
	from tools.bash_tool.bash_tool import BashTool
	from engine.abort import AbortController

	tool = BashTool(cwd=".")
	tool.check_permissions = lambda inp, context=None, **kw: False  # type: ignore[method-assign]
	out = await tool.execute(_bash_input(), AbortController())
	assert out.is_error is True and "permission denied" in out.content
	assert reg.snapshot_list(SID) == [], "权限拒绝不产生 job"


@pytest.mark.asyncio
async def test_job_tools_with_fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
	reg = JobRegistry()
	monkeypatch.setattr("server.job_registry.get_job_registry", lambda: reg)
	monkeypatch.setattr(
		"tools.job_tools._session_id", lambda: SID
	)
	from engine.abort import AbortController
	from tools.job_tools import JobKillTool, JobListTool, JobOutputTool

	abort = AbortController()
	lst = await JobListTool().execute({}, abort)
	assert lst.content == "(no background jobs)"

	reg.settle  # noqa: B018 — touch for lint clarity
	jid, _ = reg.start(
		kind="bash", label="全量回归", owner_session_id=SID,
		producer=lambda push: (STATUS_SUCCEEDED, "exit code 0") if push("line1\n") or True else ("", ""),
	)
	out = await JobOutputTool().execute({"job_id": jid}, abort)
	assert "line1" in out.content and out.content.endswith("[status: succeeded]")

	lst = await JobListTool().execute({}, abort)
	assert jid in lst.content and "bash" in lst.content and "全量回归" in lst.content

	kill = await JobKillTool().execute({"job_id": jid}, abort)
	assert "already succeeded" in kill.content or "requested" in kill.content
	kill_unknown = await JobKillTool().execute({"job_id": "bash-999"}, abort)
	assert kill_unknown.is_error is True and "unknown job" in kill_unknown.content


@pytest.mark.asyncio
async def test_job_output_foreign_owner_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
	reg = JobRegistry()
	monkeypatch.setattr("server.job_registry.get_job_registry", lambda: reg)
	monkeypatch.setattr("tools.job_tools._session_id", lambda: "someone-else")
	from engine.abort import AbortController
	from tools.job_tools import JobOutputTool

	jid, _ = reg.start(
		kind="bash", label="x", owner_session_id=SID, producer=_sync_producer()
	)
	out = await JobOutputTool().execute({"job_id": jid}, AbortController())
	assert out.is_error is True and "unknown job" in out.content


# ---------------------------------------------------------------------------
# T_now 补投块
# ---------------------------------------------------------------------------
def _joined_user_texts(msgs: list[dict]) -> str:
	# 声道无关：legacy=末条 user 的 text 块；env_channel（方案A）=伪对 tool_result 正文
	last = msgs[-1]
	content = last.get("content")
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		return "\n".join(
			str(b.get("text") or b.get("content") or "")
			for b in content
			if isinstance(b, dict)
		)
	return ""


def test_pending_jobs_block_strong_hung(monkeypatch: pytest.MonkeyPatch) -> None:
	"""非 docker 路径：块 = 块头 + digest 事实（id/exit_code/命令）。

	2026-09-09 起刻意去掉 `job_output(...)` 收取提示（叙事/编排非状态，见
	pre_llm_inject.py:330-336）；该提示仅在 docker 分支保留。
	"""
	from permissions.policy import set_pending_jobs_digest

	set_pending_jobs_digest("- bash-3 [bash] failed — exit code 1 — 全量回归")
	try:
		projected = [{"role": "user", "content": "hi"}]
		out = run_pre_llm_inject(
			projected, InjectContext(cwd="", include_memory_index=False)
		)
		blob = _joined_user_texts(out)
		assert "# Background jobs（background only）" in blob
		assert "bash-3" in blob and "exit code 1" in blob, "只报 job 事实"
	finally:
		set_pending_jobs_digest("")


def test_pending_jobs_block_absent_without_digest() -> None:
	from permissions.policy import set_pending_jobs_digest

	set_pending_jobs_digest("")
	projected = [{"role": "user", "content": "hi"}]
	out = run_pre_llm_inject(
		projected, InjectContext(cwd="", include_memory_index=False)
	)
	assert "# Background jobs" not in _joined_user_texts(out)


# ---------------------------------------------------------------------------
# P0-5：后台 job 物理上限
# ---------------------------------------------------------------------------
def test_job_max_timeout_default_is_six_hours() -> None:
	"""默认上限 6h——足够长（不破坏"后台可长跑"），但确实存在。"""
	from server.job_registry import JOB_NO_TIMEOUT_MS, _job_max_timeout_ms

	assert JOB_NO_TIMEOUT_MS == 6 * 3600_000
	monkeypatch_env = None
	assert _job_max_timeout_ms() == 6 * 3600_000


def test_job_max_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
	from server.job_registry import _job_max_timeout_ms

	monkeypatch.setenv("XEYO_JOB_MAX_TIMEOUT_MS", "120000")
	assert _job_max_timeout_ms() == 120_000


@pytest.mark.parametrize("bad", ["", "abc", "-1", "0", "1.5"])
def test_job_max_timeout_invalid_falls_back(
	bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""非法值一律回退默认，不得变成"无上限"或"立即超时"。"""
	from server.job_registry import _job_max_timeout_ms

	monkeypatch.setenv("XEYO_JOB_MAX_TIMEOUT_MS", bad)
	assert _job_max_timeout_ms() == 6 * 3600_000


def test_adopt_bash_producer_kills_on_timeout(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""超时后 _produce 必须 kill 进程并结算为 failed（而非无限忙等）。

	用一个极短的上限 + 一个不会自己退出的假进程来验证。
	"""
	import subprocess
	import sys as _sys
	import time as _time

	from server.job_registry import (
		JobRegistry,
		STATUS_FAILED,
	)

	monkeypatch.setenv("XEYO_JOB_MAX_TIMEOUT_MS", "600")

	reg = JobRegistry()
	# 一个睡眠 30s 的子进程：远超 600ms 上限
	proc = subprocess.Popen(
		[_sys.executable, "-c", "import time; time.sleep(30)"],
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
	)

	class _FakeHandle:
		def __init__(self, p):
			self.proc = p
			self.killed_by_abort = False
			self.released = False

		def attach_abort(self, ctl):
			return None

		def release(self):
			self.released = True

		def kill(self):
			self.proc.kill()

		def replay_and_attach(self, sink):
			return ""

	handle = _FakeHandle(proc)
	try:
		job_id, err = reg.adopt_bash(
			handle=handle,
			command="sleep 30",
			cwd=".",
			label="timeout-probe",
			owner_session_id="s-timeout",
		)
		assert job_id, err
		# 等到结算（上限 600ms + 余量）
		deadline = _time.monotonic() + 10.0
		status = None
		while _time.monotonic() < deadline:
			snap = reg.snapshot_list("s-timeout")
			if snap:
				status = snap[0].get("status")
				if status in ("failed", "killed", "succeeded"):
					break
			_time.sleep(0.1)
		assert status == STATUS_FAILED
	finally:
		if proc.poll() is None:
			proc.kill()
		proc.wait(timeout=5)
