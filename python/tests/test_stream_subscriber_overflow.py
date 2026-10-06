"""慢订阅者不再被掐死：尾部帧与 `[DONE]` 必须到达，丢帧按**这条连接**记洞（2026-10-03 修）。

## 取证史（2026-10-03，HTTP 全栈实测，provider=fake，零付费）

同一回合回复长度 907 / 1207 / 2107 字符三档，客户端无论读得多快都在**完全相同**的位置
断流：收到 685 帧、事件号 1..174 与 176..686（**175 号静默消失**），此后没有任何帧，也
没有 `[DONE]`；而引擎把整段正文完整落盘、`turn.json` 记 `status="succeeded"`。
界面侧 `gui/src/lib/api/chatStream.ts` 只能弹「连接中断…请重试」⇒ 长答案要整枪重付。

## 结构性根因

每连接发送缓冲是 `asyncio.Queue(maxsize=512)`，泵逐帧扇出时一满就把订阅者**摘除标死**：

1. 摘除后 [DONE] 再也不会扇出给它 ⇒ 违背本模块自述的「SSE 无 [DONE] 提前 EOF = 故障形态」；
2. 为塞 `_END` 哨兵先 `get_nowait()` 丢掉队首一帧（就是 175 号），且整条尾部不再扇出，
   **却什么都不记** ⇒ 违背 line 91-93 的「缺段必须留洞的证据，否则会被当成完整内容提交」；
3. 洞是**每条连接自己的属性**：同回合里快连接全帧收过。旧实现连记都没记，更没法区分。

根因校正：慢**不是**逐帧 `await request.is_disconnected()` 造成的——Starlette
`requests.py:328-340` 用立即 cancel 的 CancelScope 做非阻塞轮询。实测是每帧 SSE socket
写比泵产帧慢约 3×，积压从订阅那刻起就不收敛。所以修法不是"让泵等它"（一个卡住的连接
不该拖住整条流和其他订阅者），而是：额度抬到每连接 4096（环形缓冲本身才 4000 帧，
一枪长回复排得下），真溢出只丢**这条连接**的队首并在 `[DONE]` 之前把洞交给它。

## 现在的契约（本文件逐档钉住）

- 活着但慢的连接不被摘除 ⇒ 全帧 + `[DONE]`（反向校准档 + 慢消费者档）；
- 真溢出时：洞按连接记（`stream_gap` 帧 + `stream.gap` 审计行），且 `[DONE]` 必达；
- **一条连接的洞不污染 turn 级计数** ⇒ 别的连接重放时不会被谎报缺段；
- 界面收到 `stream_gap` 就改用服务端 transcript 收尾（`streamRecoverySlice.ts`），
  不把本地缺段当完整提交。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import engine.turn_runner as tr
from engine.turn_runner import TurnRunner
from server.routers.chat import _openai_chunk

TOTAL = 700
#: 每连接额度是 4096 ⇒ 溢出档必须超过它。
OVERFLOW_TOTAL = 5000


class _FakePool:
    """泵只需要 `touch_busy`（≥30s 心跳）与 `end`（归还租约）。"""

    def touch_busy(self, session_id: str) -> None:
        pass

    def end(self, session_id: str, lease_id: int | None = None) -> None:
        pass


def _expected_text(total: int) -> str:
    return "".join(f"字{i}" for i in range(1, total + 1))


def _producer(total: int):
    """帧由产品自己的构造器产出（`chat._openai_chunk`）。

    手写 `data: {"n": 1}` 那种形状与生产分叉：合并/游标都按 `choices[].delta.content`
    与 `xeyo_event_id` 走，夹具形状不对就等于没测。
    """

    async def _gen():
        for i in range(1, total + 1):
            await asyncio.sleep(0)
            frame = _openai_chunk(f"字{i}", model="fake-model", event_id=i)
            yield (str(i), frame.encode("utf-8"), "delta")
        yield (str(total + 1), b"data: [DONE]\n\n", "done")

    return _gen


def _decode(frames: list[bytes]) -> tuple[list[int], str, bool, list[int]]:
    ids: list[int] = []
    parts: list[str] = []
    saw_done = False
    gaps: list[int] = []
    for f in frames:
        txt = f.decode("utf-8")
        body = txt[txt.index("data: ") + len("data: ") :].strip()
        if body == "[DONE]":
            saw_done = True
            continue
        payload = json.loads(body)
        xy = payload.get("xy") or {}
        if xy.get("type") == "stream_gap":
            gaps.append(int(xy.get("dropped_through_event_id") or 0))
            continue
        delta = (payload.get("choices") or [{}])[0].get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            parts.append(content)
            if payload.get("xeyo_event_id") is not None:
                ids.append(int(payload["xeyo_event_id"]))
    return ids, "".join(parts), saw_done, gaps


@pytest.fixture(autouse=True)
def _isolate_sessions_dir(tmp_path, monkeypatch):
    """turn.json 落盘必须进 tmp：否则用例会写进用户真实 ~/.xeyo/sessions。"""
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))


async def _start(runner: TurnRunner, session_id: str, total: int) -> None:
    await runner.start(
        session_id=session_id,
        lease_id=1,
        model="fake-model",
        goal_text="g",
        user_message_id="u1",
        producer=_producer(total),
        turn_id="t-" + session_id,
    )


async def _drain(agen, received: list[bytes]) -> None:
    async for frame in agen:
        if frame is not None:
            received.append(frame)


@pytest.mark.asyncio
async def test_prompt_subscriber_gets_every_frame_and_done():
    """反向校准：消费者不慢 ⇒ 全帧 + [DONE]、没有 gap、turn 级计数也没被碰。"""
    runner = TurnRunner(_FakePool())
    await _start(runner, "ovl-fast", TOTAL)
    received: list[bytes] = []
    task = asyncio.create_task(_drain(runner.subscribe("ovl-fast", cursor=0), received))
    await runner.wait_done("ovl-fast", timeout=20.0)
    await asyncio.wait_for(task, timeout=10.0)

    ids, text, saw_done, gaps = _decode(received)
    assert saw_done, "健康订阅者必须收到 [DONE]"
    assert len(ids) == TOTAL, (len(ids), TOTAL)
    assert text == _expected_text(TOTAL), "正文必须逐字到齐"
    assert gaps == [], "健康连接不该被告知缺段"
    det = runner._turns.get("ovl-fast")
    assert det is not None and det.dropped_through_id == 0


@pytest.mark.asyncio
async def test_slow_subscriber_still_receives_terminal_done_frame():
    """主档（修后）：每帧停 1ms 的慢连接拿到整段正文 + [DONE]。

    旧实现在这里只送到 639/700 帧且无 [DONE] ⇒ 界面把截断当完整，或弹"请重试"。
    """
    runner = TurnRunner(_FakePool())
    await _start(runner, "ovl-slow-done", TOTAL)
    received: list[bytes] = []

    async def _slow_reader() -> None:
        async for frame in runner.subscribe("ovl-slow-done", cursor=0):
            if frame is None:
                continue
            received.append(frame)
            await asyncio.sleep(0.001)

    task = asyncio.create_task(_slow_reader())
    await runner.wait_done("ovl-slow-done", timeout=20.0)
    await asyncio.wait_for(task, timeout=20.0)

    _ids, text, saw_done, gaps = _decode(received)
    assert saw_done, "慢订阅者也必须收到终止帧，否则界面把截断当完整"
    assert text == _expected_text(TOTAL), "4096 额度内一帧都不该丢：正文必须逐字到齐"
    assert gaps == [], "没丢帧就不得谎报缺段"


@pytest.mark.asyncio
async def test_overflow_records_gap_on_that_connection_only(monkeypatch):
    """真溢出（积压 > 4096）：洞交给这条连接，且**不污染** turn 级计数。

    同回合挂两条连接：一条持续读、一条只取走第一帧后停住。环形缓冲被放大到不触发，
    所以 `det.dropped_through_id` 必须还是 0——若把洞记在 turn 级，快连接重放时会被
    谎报缺段（白拉一次 transcript + 诊断层多一条假证据）。
    """
    monkeypatch.setattr(tr, "_MAX_BUFFERED_FRAMES", 10_000_000)
    monkeypatch.setattr(tr, "_MAX_BUFFERED_BYTES", 1024 * 1024 * 1024)

    runner = TurnRunner(_FakePool())
    session = "ovl-two-cons"
    await _start(runner, session, OVERFLOW_TOTAL)

    # 慢连接：取走第一帧后不再读，让积压涨过每连接额度。
    stalled_agen = runner.subscribe(session, cursor=0)
    first = await asyncio.wait_for(stalled_agen.__anext__(), timeout=20.0)
    assert isinstance(first, bytes), "夹具自证：慢连接要先挂上"
    await asyncio.sleep(0.05)  # 让 subscribe 把队列挂进 det.subscribers

    # 快连接：全程持续读。
    fast: list[bytes] = []
    fast_task = asyncio.create_task(_drain(runner.subscribe(session, cursor=0), fast))

    await runner.wait_done(session, timeout=30.0)
    await asyncio.wait_for(fast_task, timeout=20.0)

    stalled: list[bytes] = [first]
    await asyncio.wait_for(_drain(stalled_agen, stalled), timeout=20.0)

    det = runner._turns.get(session)
    assert det is not None

    fast_ids, fast_text, fast_done, fast_gaps = _decode(fast)
    assert fast_done and fast_text == _expected_text(OVERFLOW_TOTAL), (
        "同一回合的快连接不能因为别人慢而缺段"
    )
    assert fast_gaps == [], "快连接不得被告知缺段"

    _slow_ids, _slow_text, slow_done, slow_gaps = _decode(stalled)
    assert slow_gaps and slow_gaps[-1] > 0, (
        "丢了帧必须把洞交给这条连接（stream_gap）"
    )
    assert slow_done, "溢出连接也必须收到 [DONE]，不许无终止标记收流"

    assert det.dropped_through_id == 0, (
        "洞属于这一条连接；记进 turn 级会让别的连接重放时被谎报缺段"
    )
