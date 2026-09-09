"""[DONE] 与 rewind 收尾解耦（A2b）的契约锁测试。

问题根因（2026-09-09 审计）：GUI 判定回合结束只认 SSE ``[DONE]``，而该帧
在 chat producer 里要等 ``engine.submit`` 迭代自然排空（= finally 收尾全跑完：
transcript flush / memory 归档 / rewind After 快照 + AgentFileIndex 差量同步 /
journal 终态 / revision commit，大工作区数百 ms）才发 →「模型答完仍回复中」。

修复：producer 把完成信号锚定到「内容终结事件」ResultEvent（query_loop 不产它，
submit_message 保证它是最后一个事件；其后的 finally 全是不产帧的侧效应），
[DONE] 提前到收尾之前；runner/lease/settle 语义零变化。

本文件锁死两条契约：
1. 引擎契约：ResultEvent 是 submit 事件流最后一个事件；且收到 ResultEvent 时
   rewind journal 的 turn 终态记账尚未执行（settle 在其后）——这是 producer
   提前发 [DONE] 不出错的前提。
2. HTTP 契约：SSE 恰好一个 [DONE]，且出现在全部内容帧（finish_reason=stop）之后。

运行:
  py -3.11 -m pytest tests/test_rewind_done_decouple.py -q
"""

from __future__ import annotations

import uuid

import pytest

from msgtypes.events import ResultEvent
from engine.query_engine import build_default_engine


@pytest.mark.asyncio
async def test_result_event_is_last_and_settlement_runs_after(
    tmp_path, monkeypatch
) -> None:
    """引擎契约锁：ResultEvent 恒为最后一帧；其到达时 turn 仍 running。

    ``submit`` 在 yield ResultEvent 处挂起生成器，finally（journal 终态等）
    要等消费者索取下一项才执行。因此在 ResultEvent 到达时刻读 journal，
    若仍是 running，即证明 [DONE] 提前锚在 ResultEvent 不会早于任何内容帧、
    也不会吞掉收尾记账（收尾仍在 runner 侧照常完成）。
    """
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    ws = tmp_path / "ws"
    ws.mkdir()
    eng = build_default_engine(model_backend="fake", cwd=str(ws))

    agen = eng.submit(f"hello {uuid.uuid4().hex[:6]}")
    # journal turn_id 由 start_turn 自生成，与 TaskStateEvent.turn_id 不同；
    # 单引擎无并发，以「running 态最新 turn」定位当前回合。
    # 引擎在 yield ResultEvent 处暂停，finally（终态记账）等下一次 __anext__
    # 才执行——ResultEvent 到达瞬间 journal 里必然还能看到 running 记录。
    result_seen = 0
    status_at_result: str | None = None
    last: object = None
    while True:
        try:
            ev = await agen.__anext__()
        except StopAsyncIteration:
            break
        last = ev
        if isinstance(ev, ResultEvent):
            result_seen += 1
            live = [
                t for t in eng._rewind_journal.list_turns() if t.status == "running"
            ]
            if live:
                status_at_result = live[-1].status

    # 引擎契约：ResultEvent 恰好一个且是最后一个事件。
    assert result_seen == 1
    assert isinstance(last, ResultEvent)
    # [DONE] 提前锚的前提：ResultEvent 到达时收尾记账尚未执行。
    assert status_at_result == "running", "settlement 已在 ResultEvent 之前执行——契约被破坏"
    # 排空结束后终态记账已补上（runner settle 语义无损）。
    rows = eng._rewind_journal.list_turns()
    assert rows, "journal 无任何 turn 记录"
    post = rows[-1]
    assert post.status == "committed"


@pytest.mark.asyncio
async def test_settlement_slow_but_result_last(tmp_path, monkeypatch) -> None:
    """慢收尾（After 快照拖慢 300ms）不改契约：ResultEvent 仍最后、turn 仍终态。"""
    import engine.query_engine as qe_mod

    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    ws = tmp_path / "ws"
    ws.mkdir()

    real_snapshot = qe_mod._rewind_take_snapshot

    def _slow_snapshot(cwd: str, session_id: str, phase: str) -> str | None:
        import time

        time.sleep(0.3)
        return real_snapshot(cwd, session_id, phase)

    monkeypatch.setattr(qe_mod, "_rewind_take_snapshot", _slow_snapshot)

    eng = build_default_engine(model_backend="fake", cwd=str(ws))
    agen = eng.submit(f"slow {uuid.uuid4().hex[:6]}")
    last: object = None
    while True:
        try:
            ev = await agen.__anext__()
        except StopAsyncIteration:
            break
        last = ev
    assert isinstance(last, ResultEvent)
    rows = eng._rewind_journal.list_turns()
    assert rows, "journal 无任何 turn 记录"
    post = rows[-1]
    assert post.status == "committed"


def test_stream_has_exactly_one_done_after_content(monkeypatch) -> None:
    """HTTP 契约：SSE 恰好一个 [DONE]，且出现在 finish_reason=stop 之后。"""
    import re
    from fastapi.testclient import TestClient

    from server.app import app

    def _join_delta_content(text: str) -> str:
        """同 test_server_fake_provider：FakeModelClient 逐字符流式，raw SSE
        是 JSON 转义文本，需解码各 delta.content 再拼接后断言。"""
        parts: list[str] = []
        for m in re.finditer(
            r'"delta"\s*:\s*\{[^}]*"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text
        ):
            parts.append(m.group(1))
        return "".join(parts)

    # 会话目录隔离：用临时目录避免污染真实 ~/.xeyo。
    import tempfile
    from pathlib import Path

    monkeypatch.setenv("XEYO_ALLOW_FAKE_MODEL", "1")
    tmp = Path(tempfile.mkdtemp(prefix="xeyo-done-test-"))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp / "sessions"))
    monkeypatch.setenv("XEYO_SNAPSHOTS_DIR", str(tmp / "snapshots"))

    client = TestClient(app)
    sid = f"done-decouple-{uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "fake",
            "stream": True,
            "session_id": sid,
            "provider": "fake",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert resp.status_code == 200
    text = resp.text
    # 恰好一个 [DONE]
    assert text.count("[DONE]") == 1
    # [DONE] 在所有内容/收尾帧之后（content 已全部揭示完毕才宣告完成）
    assert '"finish_reason": "stop"' in text
    assert text.find("[DONE]") > text.rfind('"finish_reason": "stop"')
    # 内容未丢
    assert "ok: hi" in _join_delta_content(text)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
