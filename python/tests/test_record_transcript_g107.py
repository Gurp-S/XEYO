"""G107: record_transcript 轮转/append 竞态 + fsync 落盘回归。

后台 writer 与 record_transcript_sync 直写共享磁盘临界区锁;轮转下同步/异步
交替写入不丢尾、无重复。小上限强制轮转多次。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from msgtypes.message import Message


def _msg(i: int) -> Message:
    body = f"payload-{i}-" + ("x" * 40)
    return SimpleNamespace(
        id=f"msg-{i:04d}",
        role="user",
        content=body,
        tool_call_id="",
        name="",
        narration="",
        interrupted=False,
    )  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_rotate_sync_async_no_tail_loss(tmp_path, monkeypatch) -> None:
    import importlib

    rt = importlib.import_module("session.record_transcript")

    monkeypatch.setenv("XEYO_TRANSCRIPT_MAX_BYTES", "1024")
    monkeypatch.delenv("XEYO_NO_SESSION_PERSISTENCE", raising=False)

    path = tmp_path / "s" / "t.jsonl"
    known: set[str] = set()
    n = 80
    for i in range(n):
        if i % 2 == 0:
            rt.record_transcript_sync(
                [_msg(i)], session_id="x", path=path, known_ids=known
            )
        else:
            await rt.record_transcript(
                [_msg(i)], session_id="x", path=path, known_ids=known
            )
        if i % 9 == 8:
            rt.flush_transcript(path)

    rt.flush_transcript(path)

    # 全链读取(归档+当前)的 id 必须构成无洞的连续尾段(轮转可能裁剪最旧一代)
    rows: list[dict] = []
    for p in rt.transcript_read_paths(path):
        rows.extend(rt.load_transcript(p))
    ids = sorted(int(r["id"].split("-")[1]) for r in rows)
    assert ids == list(range(ids[0], n)), f"tail has holes: {ids[:5]}...{ids[-5:]}"
    assert len(set(ids)) == len(ids)  # 无重复
    assert ids[-1] == n - 1  # 最新一条绝不丢
