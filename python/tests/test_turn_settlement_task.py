"""turn 终态广播（settlement）必须"抛得出声"，任务不能被丢下就走。

`engine/turn_runner.py` 在 turn 收尾时把 listener 起成后台任务，注释写着
"listener 内部自隔离异常，**这里再兜一层**"——可原来的那一层只包住了
`listener(...)` 这次**同步调用**；协体一旦被调度，它自己抛的东西没有任何人取回。
本仓从不配置 logging handler（见 diagnostics 的既有结论），未取回的异常连
"exception was never retrieved" 都不会出现 ⇒ settlement 承担的收尾（busy/租约
归还等）失败得**完全无声**，外在表现就是"会话一直忙"这种没人看得懂的症状。

另一半是引用：事件循环对 Task 只持**弱**引用，起完就丢是 asyncio 明文禁止的写法。
⇒ 这里同时钉"留强引用直到完成"与"完成后从集合里摘掉（不无界增长）"。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from engine import turn_runner


@pytest.mark.asyncio
async def test_raising_listener_is_logged(caplog) -> None:
    """违约的 listener（契约：自隔离异常、绝不抛）必须留下 warning。"""
    boom = RuntimeError("release busy failed")

    async def _bad() -> None:
        raise boom

    with caplog.at_level(logging.WARNING, logger="xeyo.turn_runner"):
        turn_runner._spawn_settlement(_bad())
        await _drain_settlement_tasks()

    assert any(
        "settlement listener failed" in r.getMessage() for r in caplog.records
    ), f"抛错没留痕（记录={[r.getMessage() for r in caplog.records]}）"
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_good_listener_runs_and_leaves_no_trace(caplog) -> None:
    """对照（必须绿）：正常 listener 要真的跑完，且不产生噪声日志。"""
    done = asyncio.Event()

    async def _ok() -> None:
        done.set()

    with caplog.at_level(logging.WARNING, logger="xeyo.turn_runner"):
        turn_runner._spawn_settlement(_ok())
        await asyncio.wait_for(done.wait(), timeout=2.0)
        await _drain_settlement_tasks()

    assert done.is_set(), "回调没被执行 ⇒ 后台化本身就是坏的"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "正常收尾不该报错（反向校：门不是无条件响）"
    )


@pytest.mark.asyncio
async def test_task_is_referenced_until_done_and_not_accumulated() -> None:
    """强引用要撑到任务结束；结束后必须摘干净（否则每回合漏一个条目）。"""
    gate = asyncio.Event()
    ran = asyncio.Event()

    async def _slow() -> None:
        ran.set()
        await gate.wait()

    turn_runner._spawn_settlement(_slow())
    await asyncio.wait_for(ran.wait(), timeout=2.0)
    assert len(turn_runner._SETTLEMENT_TASKS) == 1, (
        "在途任务没有被强引用持有：事件循环只持弱引用，起完就丢是 asyncio 明文禁止的"
    )

    gate.set()
    await _drain_settlement_tasks()
    assert turn_runner._SETTLEMENT_TASKS == set(), "done 回调没摘除 ⇒ 集合无界增长"


@pytest.mark.asyncio
async def test_many_turns_do_not_grow_the_settlement_set() -> None:
    """跑 50 次"终态广播"后集合必须回到空——这是本仓最容易复发的泄漏形状。"""
    for _ in range(50):
        turn_runner._spawn_settlement(_noop())
    await _drain_settlement_tasks()
    assert turn_runner._SETTLEMENT_TASKS == set()


async def _noop() -> None:
    return None


class _Pool:
    """teardown 只用到 ``end``；其余一概不需要。"""

    def __init__(self) -> None:
        self.ended: list[tuple[str, int]] = []

    def end(self, session_id: str, lease_id: int) -> None:
        self.ended.append((session_id, lease_id))


@pytest.mark.asyncio
async def test_real_turn_teardown_reports_raising_listener(caplog, tmp_path, monkeypatch) -> None:
    """接线自证：走**真实** turn 收尾，违约 listener 的抛错必须成为一条 warning。

    上一组用例直接调 `_spawn_settlement`，就算产品里还写着裸 `create_task` 也照样绿
    ⇒ 那组只证明辅助函数本身对，不证明终态广播接上了。这条从
    `TurnRunner.start()` 起一个空 producer 的回合，让产品自己的 teardown 派回调。
    """
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)

    invoked: list[str] = []

    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)

    async def _boom(session_id: str, final_status: str, stop_reason: str) -> None:
        # 产品契约是 async fn(session_id, final_status, stop_reason)；签名写错
        # 会走"派发失败"那一支（下面单独立一条测它）。
        invoked.append(f"{session_id}/{final_status}")
        raise RuntimeError("settlement 收尾失败")

    turn_runner.set_turn_settlement_listener(_boom)
    try:
        runner = turn_runner.TurnRunner(_Pool())
        with caplog.at_level(logging.WARNING, logger="xeyo.turn_runner"):
            await runner.start(
                session_id="settle-wiring",
                lease_id=7,
                model="m",
                goal_text="g",
                user_message_id="u1",
                producer=_empty_producer,
            )
            assert await runner.wait_done("settle-wiring", timeout=5.0) is True
            # 等**真实发生**：不能拿"集合为空"当退出条件（它在进循环前就成立，
            # 等于没等——那会让这条断言永远在任务跑起来之前就读日志）。
            for _ in range(300):
                if invoked and any(
                    "settlement listener failed" in r.getMessage()
                    for r in caplog.records
                ):
                    break
                await asyncio.sleep(0.01)
        messages = [r.getMessage() for r in caplog.records]
        assert invoked, f"teardown 根本没派回调 ⇒ 这条测的不是接线，是夹具（{messages}）"
        assert any("settlement listener failed" in m for m in messages), (
            f"真实 teardown 里抛错仍无声（记录={messages}）⇒ 那一层兜底没接上"
        )
    finally:
        turn_runner.set_turn_settlement_listener(None)


@pytest.mark.asyncio
async def test_dispatch_failure_is_audible(caplog, tmp_path, monkeypatch) -> None:
    """回调根本没被调度（签名不符/listener 同步抛）也必须到 warning。

    这一支比"协体晚到的异常"更严重：整件收尾没发生。原来它记在 debug，
    而本仓不配 handler ⇒ debug 等价于 pass。
    """
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    (tmp_path / "sessions").mkdir(parents=True, exist_ok=True)

    def _wrong_arity() -> None:  # 少两个参数：产品调用即 TypeError
        raise AssertionError("不该被调用")

    turn_runner.set_turn_settlement_listener(_wrong_arity)
    try:
        runner = turn_runner.TurnRunner(_Pool())
        with caplog.at_level(logging.WARNING, logger="xeyo.turn_runner"):
            await runner.start(
                session_id="settle-dispatch",
                lease_id=8,
                model="m",
                goal_text="g",
                user_message_id="u2",
                producer=_empty_producer,
            )
            assert await runner.wait_done("settle-dispatch", timeout=5.0) is True
            for _ in range(200):
                if any(
                    "settlement dispatch failed" in r.getMessage() for r in caplog.records
                ):
                    break
                await asyncio.sleep(0.01)
        assert any(
            "settlement dispatch failed" in r.getMessage() for r in caplog.records
        ), "派发失败仍记在 debug ⇒ 等于没说"
    finally:
        turn_runner.set_turn_settlement_listener(None)


async def _empty_producer():
    if False:  # pragma: no cover - 让它成为 async generator
        yield (1, b"", "data")


async def _drain_settlement_tasks() -> None:
    """等在途的 settlement 任务全部收尾（done 回调是同步调度，多轮 yield 足够）。"""
    for _ in range(50):
        if not turn_runner._SETTLEMENT_TASKS:
            return
        await asyncio.sleep(0)
    await asyncio.gather(*list(turn_runner._SETTLEMENT_TASKS), return_exceptions=True)
