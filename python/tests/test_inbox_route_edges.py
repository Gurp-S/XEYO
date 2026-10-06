"""inbox 单条 resume 路由的边缘校验：与家族其余 5 条同一套固定点谓词。

2026-10-06 实测分歧：GET / ack / DELETE / PATCH / resume(整队) 全部走
``require_session_id``（DELETE/PATCH 还带 ``_require_stable_id(queue_id)``），
唯 ``POST .../inbox/{queue_id}/resume`` 只 ``strip()`` —— 带首尾空白的 id
在别的动作 422、在这里被**静默清洗**后命中目标会话/队列（同一固定点事故
家族的「两条入口一套校验」；`victim.` 这类改写形态还会得到与兄弟路由
不同的错误类 409 而非 422）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.routers.sessions import session_inbox_item_resume  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_inbox(tmp_path, monkeypatch):
	"""与 test_inbox_persistence 同款隔离：tmp 会话目录 + 全新单例 + 关 autorun。"""
	import server.inbox_registry as reg_mod

	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")
	monkeypatch.setattr(reg_mod, "_registry", reg_mod.InboxRegistry())
	yield


def _call(sid: str, qid: str) -> None:
    asyncio.run(session_inbox_item_resume(sid, qid))


def test_whitespace_wrapped_session_id_is_422_not_silently_cleaned() -> None:
    with pytest.raises(HTTPException) as ei:
        _call("victim ", "q1")
    assert ei.value.status_code == 422


def test_whitespace_wrapped_queue_id_is_422() -> None:
    with pytest.raises(HTTPException) as ei:
        _call("victim", " q1")
    assert ei.value.status_code == 422


# -- #3/DSH QueueAction:steer：单条排队项 → 边界引导 ---------------------------------

def test_steer_moves_item_to_boundary_queue() -> None:
	import asyncio

	from engine import t_now_steer
	from server.inbox_registry import get_inbox_registry
	from server.routers.sessions import session_inbox_item_steer

	sid = "s-steer-happy"
	t_now_steer.clear(sid)
	item = get_inbox_registry().enqueue(sid, "把这条立刻插话")
	out = asyncio.run(session_inbox_item_steer(sid, item.queue_id))
	assert out["ok"] is True and out["delivery"] == "boundary"
	assert t_now_steer.pending_count(sid) == 1
	# 管道契约：条目离开「queued」转入「delivering」（t_now_steer 承担至少一次投递），
	# 快照仍可见它直到边界投递/收尾——不是从快照里凭空消失。
	items = get_inbox_registry().snapshot(sid)["items"]
	assert [it["state"] for it in items] == ["delivering"]
	t_now_steer.clear(sid)


def test_steer_missing_item_is_409() -> None:
	import asyncio

	from server.routers.sessions import session_inbox_item_steer

	with pytest.raises(HTTPException) as ei:
		asyncio.run(session_inbox_item_steer("s-steer-none", "no-such-queue-id"))
	assert ei.value.status_code == 409


def test_steer_push_fail_restores_item_to_queue(monkeypatch) -> None:
	import asyncio

	import engine.t_now_steer as steer_mod
	from server.inbox_registry import get_inbox_registry
	from server.routers import sessions as S

	sid = "s-steer-restore"
	item = get_inbox_registry().enqueue(sid, "别丢我")
	monkeypatch.setattr(steer_mod, "push", lambda *a, **k: False)
	with pytest.raises(HTTPException) as ei:
		asyncio.run(S.session_inbox_item_steer(sid, item.queue_id))
	assert ei.value.status_code == 409
	items = get_inbox_registry().snapshot(sid)["items"]
	assert [it["queue_id"] for it in items] == [item.queue_id]
	assert items[0]["state"] == "queued"


def test_steer_blank_ids_are_422() -> None:
	import asyncio

	from server.routers.sessions import session_inbox_item_steer

	with pytest.raises(HTTPException) as ei:
		asyncio.run(session_inbox_item_steer("s-steer-x", " q1"))
	assert ei.value.status_code == 422
