"""统一取消树公开入口。

``engine.abort`` 仍是历史兼容入口；新 runtime 代码从本模块导入语义化的
``CancellationScope``，避免继续把 session、turn、job 和 process 当成同一层
的裸 boolean。
"""

import threading

from engine.abort import (
	AbortController,
	Aborted,
	CancellationScope,
	LinkedAbortController,
)


_SESSION_LOCK = threading.RLock()
_SESSION_SCOPES: dict[str, CancellationScope] = {}


def get_session_scope(session_id: str) -> CancellationScope:
	"""返回进程内 session 生命周期根。

	turn scope 不挂在这里，因此普通 turn interrupt 不会杀掉已经 detached 的
	后台 job；session 被删除时由 ``cancel_session_scope`` 统一收口。
	"""
	sid = str(session_id or "").strip()
	if not sid:
		raise ValueError("session_id is required")
	with _SESSION_LOCK:
		scope = _SESSION_SCOPES.get(sid)
		if scope is None or scope.aborted:
			scope = CancellationScope(label=f"session:{sid}")
			_SESSION_SCOPES[sid] = scope
		return scope


def cancel_session_scope(session_id: str, reason: str = "session_closed") -> bool:
	"""取消并移除 session 根；返回是否存在该根。"""
	sid = str(session_id or "").strip()
	if not sid:
		return False
	with _SESSION_LOCK:
		scope = _SESSION_SCOPES.pop(sid, None)
	if scope is None:
		return False
	scope.abort(reason)
	return True


__all__ = [
	"AbortController",
	"Aborted",
	"CancellationScope",
	"LinkedAbortController",
	"cancel_session_scope",
	"get_session_scope",
]
