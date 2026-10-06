"""多 agent 批次被取消时的两处收尾缺陷（2026-10-03 实测后钉死）。

夹具要点（踩过一次，别再踩）：`Scheduler(timeout_s=...)` **不生效**——
`engine/scheduler.py:495` 读的是 `t.timeout_s or self._default_timeout`，而
`Task.timeout_s` 默认 300.0 总会覆盖它。要进超时分支必须把超时写在 **Task** 上。
（我第一次的夹具就是栽在这里，结果"取消落在收尾窗口"的两条断言其实是走了
另一条本来就正确的分支而假绿。）

缺陷一（状态被钉错）：子 agent 超时后代码给它 2 秒收尾
（`await asyncio.wait_for(run_fut, timeout=2.0)`）。用户按停正好落在这 2 秒里时，
这个 except 把 ``CancelledError`` 与 ``TimeoutError`` **并成一支**处理，于是照旧
`_finalize(ok=False, reason="timeout")` ⇒ 任务永久记成 `failed/timeout`。
同文件其它三处取消分支（run() 外层、`_dispatch` 外层、子任务回收）一律记
`pending/interrupted`（可重认领）。⇒ 一次按停被写成终态，恢复/重认领不再捡它。

缺陷二（任务泄漏）：`run()` 每轮为批次建一个 `_watch_batch_abort` 轮询任务，
它的 `cancel()` 写在 `await asyncio.wait(...)` **之后**。取消正是落在那个 await 上、
直接跳到外层 except，于是这一轮的监视任务永不取消——实测它在 run() 结束后
仍以 20Hz 继续跑，且不会自终止。
"""

from __future__ import annotations

import asyncio

import pytest

from engine.scheduler import Scheduler, Task

_TASK_TIMEOUT_S = 0.05
_GRACE_S = 2.0


def _scheduler(tmp_path) -> Scheduler:
    return Scheduler(str(tmp_path), task_batch_id="tb")


async def _enter_grace_window(monkeypatch, tmp_path):
    """把任务推进"已超时、正在等子 agent 收尾"的窗口；子 agent 永不返回。"""
    started = asyncio.Event()
    never_release = asyncio.Event()
    holds: list = []

    async def _hang(self, t, *, patch_attempt=0, abort=None):  # noqa: ANN001
        holds.append(abort)
        started.set()
        await never_release.wait()
        raise AssertionError("子 agent 不该自己返回")

    monkeypatch.setattr(Scheduler, "_run_task", _hang)
    sched = _scheduler(tmp_path)
    task = Task(id="t1", desc="改一个文件", timeout_s=_TASK_TIMEOUT_S)
    sched.load([task])
    runner = asyncio.create_task(sched.run(), name="sched-run")
    await asyncio.wait_for(started.wait(), timeout=5.0)
    # 超时点已过、收尾窗口还开着（abort 必须已置位，否则我们其实在别的路径上）。
    await asyncio.sleep(_TASK_TIMEOUT_S + 0.15)
    assert holds and holds[0] is not None and holds[0].aborted, (
        "前置自证：此刻应已进入超时分支（AbortController 已置位）"
    )
    return sched, task, runner


@pytest.mark.asyncio
async def test_cancel_during_grace_is_not_recorded_as_timeout(monkeypatch, tmp_path) -> None:
    """收尾窗口里的取消应记成可重认领的 pending/interrupted。"""
    _sched, task, runner = await _enter_grace_window(monkeypatch, tmp_path)

    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(runner, timeout=_GRACE_S + 3.0)

    assert task.failure_reason != "timeout", (
        f"一次用户按停被钉成了终态 timeout（status={task.status}），"
        "恢复/重认领路径不会再捡它起来"
    )
    assert task.status == "pending", f"应为 pending，实际 {task.status}"
    assert "interrupt" in (task.failure_reason or "").lower()


@pytest.mark.asyncio
async def test_no_abort_watcher_survives_cancelled_batch(monkeypatch, tmp_path) -> None:
    """批次被取消后，`_watch_batch_abort` 轮询任务不能继续活着。"""
    _sched, _task, runner = await _enter_grace_window(monkeypatch, tmp_path)

    runner.cancel()
    try:
        await asyncio.wait_for(runner, timeout=_GRACE_S + 3.0)
    except asyncio.CancelledError:
        pass

    watchers = [
        t
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task()
        and "_watch_batch_abort" in repr(t.get_coro())
    ]
    assert not watchers, "泄漏的监视任务仍在跑：每取消一个批次就多一个 20Hz 轮询"
    # 反向自证：判据确实能看见活着的监视任务（否则这条门是装饰）。
    probe = asyncio.create_task(_watch_like_forever(), name="watcher-probe")
    await asyncio.sleep(0)
    still = [
        t
        for t in asyncio.all_tasks()
        if t is not asyncio.current_task()
        and (t is probe or "_watch_batch_abort" in repr(t.get_coro()))
    ]
    assert still, "判据看不见任何在跑的监视任务 ⇒ 匹配写法失效"
    probe.cancel()


async def _watch_like_forever() -> None:
    while True:
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_real_timeout_still_records_timeout(monkeypatch, tmp_path) -> None:
    """对照（必须绿）：没有人取消、真的超时，仍然要落终态 failed/timeout。

    没有这条，"把取消改成 pending" 的那一刀可能顺手把真超时也一起放行。
    """
    started = asyncio.Event()
    never_release = asyncio.Event()

    async def _hang(self, t, *, patch_attempt=0, abort=None):  # noqa: ANN001
        started.set()
        await never_release.wait()
        raise AssertionError("不该返回")

    monkeypatch.setattr(Scheduler, "_run_task", _hang)
    sched = _scheduler(tmp_path)
    task = Task(id="t1", desc="改一个文件", timeout_s=_TASK_TIMEOUT_S)
    sched.load([task])

    runner = asyncio.create_task(sched.run(), name="sched-timeout")
    await asyncio.wait_for(started.wait(), timeout=5.0)
    # 不取消：等满 2 秒收尾窗口，run() 自己落终态。
    await asyncio.wait_for(runner, timeout=_GRACE_S + 5.0)
    assert task.status == "failed", f"真超时必须落终态，实际 {task.status}"
    assert task.failure_reason == "timeout", f"实际原因 {task.failure_reason!r}"
