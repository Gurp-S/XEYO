"""结构性修复回归：JobRegistry 的**资源回收**与**唤醒语义**（2026-10-13）。

本文件是 A/B 方法论的产物：每条用例在修复前**必须失败**（证明 bug 存在），
修复后必须通过（证明治本）。覆盖三类结构性根因：

1. **注册无补偿**（`adopt_bash` 收编失败留下永久 running 的幽灵 Job，
   并真实吃掉 `MAX_CONCURRENT_JOBS_PER_OWNER` 槽位）；
2. **资源无 owner / 无 GC**（终态 Job 及其 ring/游标/abort 永不回收）；
3. **唤醒去重判据错**（判"任务在跑"而不是"队列空"）——
   `_schedule_delivery_task` 在途即丢、`on_delivery_tick` 忙即裸 return、
   `pending_digest` 无视 `reported`。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.job_registry import (  # noqa: E402
    MAX_CONCURRENT_JOBS_PER_OWNER,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    JobRegistry,
)

SID = "s-structural"


@pytest.fixture()
def fast_wake(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr("server.job_registry._WAKE_DEBOUNCE_S", 0.01)


def _running(reg: JobRegistry, sid: str = SID) -> int:
	return sum(
		1
		for j in reg._jobs.values()
		if j.owner_session_id == sid and j.status in (STATUS_RUNNING, "stopping")
	)


# ---------------------------------------------------------------------------
# 1. adopt_bash：收编失败必须补偿（当前：留下永久 running 的幽灵 Job）
# ---------------------------------------------------------------------------
class _BrokenAttach:
	"""`attach_abort` 抛错——收编失败的第一条分支。"""

	def attach_abort(self, ctl: Any) -> None:
		raise RuntimeError("boom")


class _BrokenReplay:
	"""`replay_and_attach` 抛错——收编失败的第二条分支。"""

	def attach_abort(self, ctl: Any) -> None:
		return None

	def replay_and_attach(self, sink: Any) -> str:
		raise RuntimeError("boom")


def test_adopt_attach_failure_rolls_back_registered_job() -> None:
	"""`attach_abort` 失败 ⇒ 不得在 `_jobs` 留下任何记录。"""
	reg = JobRegistry()
	jid, err = reg.adopt_bash(
		handle=_BrokenAttach(), command="x", cwd=".", label="x", owner_session_id=SID
	)
	assert jid is None and err
	assert reg.snapshot_list(SID) == [], "收编失败不得留下幽灵 job"


def test_adopt_replay_failure_rolls_back_registered_job() -> None:
	"""`replay_and_attach` 失败 ⇒ 同样不得留下记录。"""
	reg = JobRegistry()
	jid, err = reg.adopt_bash(
		handle=_BrokenReplay(), command="x", cwd=".", label="x", owner_session_id=SID
	)
	assert jid is None and err
	assert reg.snapshot_list(SID) == [], "收编失败不得留下幽灵 job"


def test_adopt_failures_do_not_consume_capacity() -> None:
	"""连续收编失败不得吃掉并发槽位（否则多失败几次就永久 10/10）。"""
	reg = JobRegistry()
	for _ in range(MAX_CONCURRENT_JOBS_PER_OWNER * 2):
		reg.adopt_bash(
			handle=_BrokenAttach(), command="x", cwd=".", label="x", owner_session_id=SID
		)
	assert _running(reg) == 0, "失败收编不得占用容量"

	# 槽位仍然可用：真 job 能起来
	jid, err = reg.start(
		kind="bash", label="real", owner_session_id=SID,
		producer=lambda push: (STATUS_SUCCEEDED, ""),
	)
	assert jid is not None and not err


# ---------------------------------------------------------------------------
# 2. 终态 Job 必须有界回收（当前：五个 dict 单调增长）
# ---------------------------------------------------------------------------
def test_terminal_jobs_are_gc_bounded() -> None:
	"""终态 job 数量与配套 dict 必须有上界。"""
	from server.job_registry import MAX_RETAINED_TERMINAL_JOBS_PER_OWNER

	reg = JobRegistry()
	total = MAX_RETAINED_TERMINAL_JOBS_PER_OWNER * 3
	for i in range(total):
		jid, err = reg._register(kind="bash", label=str(i), owner_session_id=SID)
		assert jid and not err
		reg.settle(jid, STATUS_SUCCEEDED, "")

	assert len(reg.snapshot_list(SID)) <= MAX_RETAINED_TERMINAL_JOBS_PER_OWNER
	for name in ("_jobs", "_rings", "_cursors", "_change_seq", "_waiters"):
		bucket = getattr(reg, name)
		assert len(bucket) <= MAX_RETAINED_TERMINAL_JOBS_PER_OWNER, f"{name} 未回收"


def test_gc_never_evicts_a_job_that_is_pending_delivery() -> None:
	"""**致命细节**：pending 中的 job 被 GC 掉 ⇒ `pending_digest` 取不到 rec ⇒ 静默丢通知。"""
	from server.job_registry import MAX_RETAINED_TERMINAL_JOBS_PER_OWNER

	reg = JobRegistry()
	keep, _ = reg._register(kind="bash", label="keep", owner_session_id=SID)
	reg.settle(keep, STATUS_SUCCEEDED, "")
	with reg._lock:
		reg._pending.setdefault(SID, []).append(keep)
		reg._jobs[keep].reported = False

	# 灌入远超上限的终态 job，逼迫 GC 发生
	for i in range(MAX_RETAINED_TERMINAL_JOBS_PER_OWNER * 2):
		jid, _ = reg._register(kind="bash", label=str(i), owner_session_id=SID)
		reg.settle(jid, STATUS_SUCCEEDED, "")

	assert keep in reg._jobs, "pending 中的 job 不得被 GC"
	assert keep in reg.pending_digest(SID)


# ---------------------------------------------------------------------------
# 3. 唤醒语义：判据必须是"队列空"，不是"任务在跑"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_second_settlement_during_submit_is_not_lost(
	monkeypatch: pytest.MonkeyPatch, fast_wake: None
) -> None:
	"""B 在 A 的 `await submit_synthetic` 期间完成 ⇒ 必须仍被投递（当前：丢）。"""
	reg = JobRegistry()
	sid = "s-lost-wakeup"
	reg._loops[sid] = asyncio.get_running_loop()

	delivered: list[str] = []
	job_b: dict[str, str] = {}

	async def fake_submit(session_id: str, digest: str, surface: str = "") -> bool:
		delivered.append(digest)
		if len(delivered) == 1:
			# 关键时序：第一个 tick 正卡在 await 里，第二个 job 完成。
			reg.settle(job_b["id"], STATUS_SUCCEEDED, "")
			await asyncio.sleep(0)
		return True

	monkeypatch.setattr("server.synthetic_round.submit_synthetic", fake_submit)

	jid_a, _ = reg._register(kind="bash", label="A", owner_session_id=sid)
	job_b["id"], _ = reg._register(kind="bash", label="B", owner_session_id=sid)

	reg.settle(jid_a, STATUS_SUCCEEDED, "")
	await asyncio.sleep(0.4)

	assert len(delivered) >= 2, f"第二次完成被丢唤醒（实际投递 {len(delivered)} 次）"
	assert any(job_b["id"] in d for d in delivered), "B 从未被投递"


@pytest.mark.asyncio
async def test_busy_turn_requeues_instead_of_dropping(
	monkeypatch: pytest.MonkeyPatch, fast_wake: None
) -> None:
	"""owner 忙 ⇒ 通知必须退回 pending，不得裸 return（当前：永久不投）。"""
	reg = JobRegistry()
	sid = "s-busy"
	reg._loops[sid] = asyncio.get_running_loop()
	monkeypatch.setattr("server.job_registry._turn_running", lambda _sid: True)

	jid, _ = reg._register(kind="bash", label="busy", owner_session_id=sid)
	reg.settle(jid, STATUS_SUCCEEDED, "")
	await asyncio.sleep(0.2)

	assert jid in reg.pending_digest(sid), "忙时丢通知：人类下一轮 T_now 补投为空"


def test_pending_digest_never_reinjects_a_reported_job() -> None:
	"""已被 `job_output` 消费（reported）的完成消息，不得再进 T_now。"""
	reg = JobRegistry()
	jid, _ = reg._register(kind="bash", label="seen", owner_session_id=SID)
	reg.settle(jid, STATUS_SUCCEEDED, "")
	with reg._lock:
		reg._pending.setdefault(SID, []).append(jid)
		reg._jobs[jid].reported = False

	# 用户主动 `job_output` 看过结果
	assert reg.read(jid, SID) is not None
	assert reg._jobs[jid].reported is True

	assert jid not in reg.pending_digest(SID), "已消费的完成消息被重复注入模型"


def test_terminal_read_removes_job_from_pending() -> None:
	"""终态读走结果 ⇒ 同时从 pending 摘除（双保险的第一道）。"""
	reg = JobRegistry()
	jid, _ = reg._register(kind="bash", label="seen", owner_session_id=SID)
	reg.settle(jid, STATUS_SUCCEEDED, "")
	with reg._lock:
		reg._pending.setdefault(SID, []).append(jid)
		reg._jobs[jid].reported = False

	reg.read(jid, SID)
	with reg._lock:
		assert jid not in reg._pending.get(SID, []), "read() 未从 pending 摘除"
