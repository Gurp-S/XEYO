"""运行中子 Agent 的 Abort 注册表 + follow-up inbox（P2）。

主会话 abort 仍通过 LinkedAbortController 联动；对本表 abort 只杀指定工人。
inbox 语义（mid-turn inbox，**park 而非注入**）：

- ``post_to_agent`` 只入队，绝不打断正在进行的 ``_run_subagent_body`` 内 query_loop；
- 投递点 = 子 agent 回合 settle（``_run_subagent_body`` 同实例循环处消费）；
- 队列仅内存（随进程消失），与 ``_LIVE`` 同口径。

key = ``{session_id}::{agent_id}``（与 ``_LIVE`` 一致）。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from engine.abort import AbortController

_lock = threading.Lock()
# 键格式 key = "{session_id}::{agent_id}"
_LIVE: dict[str, "AbortController"] = {}
# follow-up inbox：key 同上；value = list[dict(text, message_id, queued_at, state)]
_INBOX: dict[str, list[dict[str, Any]]] = {}


def _key(session_id: str, agent_id: str) -> str:
	return f"{(session_id or '').strip()}::{(agent_id or '').strip()}"


def register_live_agent(
	session_id: str,
	agent_id: str,
	abort: "AbortController",
) -> None:
	sid = (session_id or "").strip()
	aid = (agent_id or "").strip()
	if not sid or not aid:
		return
	with _lock:
		_LIVE[_key(sid, aid)] = abort


def unregister_live_agent(session_id: str, agent_id: str) -> None:
	with _lock:
		_LIVE.pop(_key(session_id, agent_id), None)


def abort_live_agent(session_id: str, agent_id: str) -> bool:
	"""取消指定子 Agent；找不到返回 False。"""
	with _lock:
		ctl = _LIVE.get(_key(session_id, agent_id))
	if ctl is None:
		return False
	ctl.abort()
	return True


def is_live_agent(session_id: str, agent_id: str) -> bool:
	with _lock:
		return _key(session_id, agent_id) in _LIVE


# ---------------------------------------------------------------------------
# follow-up inbox（park 而非注入）
# ---------------------------------------------------------------------------
def post_to_agent(session_id: str, agent_id: str, text: str, message_id: str = "") -> int:
	"""向一个子 agent 投递一条 follow-up（入队）。返回队列长度。

	空文本拒收（返回 -1）；运行中或已结束均可调用——运行中由 settle 消费，
	已结束由调用方（retry）读 meta 决定是否附带。
	"""
	sid = (session_id or "").strip()
	aid = (agent_id or "").strip()
	t = (text or "").strip()
	if not sid or not aid or not t:
		return -1
	import time

	item: dict[str, Any] = {
		"text": t,
		"message_id": (message_id or "").strip(),
		"queued_at": time.time(),
		"state": "queued",
	}
	with _lock:
		q = _INBOX.setdefault(_key(sid, aid), [])
		q.append(item)
		return len(q)


def drain_agent_inbox(session_id: str, agent_id: str) -> list[dict[str, Any]]:
	"""原子取空该 agent 的 follow-up 队列（settle 时消费）。"""
	with _lock:
		return _INBOX.pop(_key(session_id, agent_id), [])


def inbox_count(session_id: str, agent_id: str) -> int:
	with _lock:
		return len(_INBOX.get(_key(session_id, agent_id), []))


def remove_agent_inbox_item(session_id: str, agent_id: str, message_id: str) -> bool:
	"""按 message_id（为空则取首条）移除一条 follow-up；返回是否命中。"""
	key = _key(session_id, agent_id)
	mid = (message_id or "").strip()
	with _lock:
		q = _INBOX.get(key)
		if not q:
			return False
		if mid:
			for i, it in enumerate(q):
				if str(it.get("message_id") or "") == mid:
					del q[i]
					if not q:
						_INBOX.pop(key, None)
					return True
		else:
			q.pop(0)
			if not q:
				_INBOX.pop(key, None)
			return True
	return False


def clear_agent_inbox(session_id: str, agent_id: str) -> None:
	with _lock:
		_INBOX.pop(_key(session_id, agent_id), None)


def clear_all_for_tests() -> None:
	with _lock:
		_LIVE.clear()
		_INBOX.clear()


__all__ = [
	"abort_live_agent",
	"clear_agent_inbox",
	"clear_all_for_tests",
	"drain_agent_inbox",
	"inbox_count",
	"is_live_agent",
	"post_to_agent",
	"register_live_agent",
	"remove_agent_inbox_item",
	"unregister_live_agent",
]
