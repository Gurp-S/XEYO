"""`/status` 不许把"读不出"写成"没有"。

缺陷：``slash/dispatch.py::_cmd_status`` 里两处 ``except Exception: pass``——待批准条目
与最近任务的读取一旦失败（权限库不可读、通道 store 抛错），报告里那一行就**静默消失**。
使用者看到的是"没有待批准 / 没有最近任务"，而事实是"这两项读不出来"。

同族前两处已修：完成门控把"是目录"说成"磁盘上不存在"；单个非 UTF-8 文件连坐清空
嵌套项目指令。这条是它在人机界面上的第三处。

方向性都钉：正常路径不许因为这次改动冒出"读不出"噪声；真有待批准时那行照旧。
"""

from __future__ import annotations

import channels.api as capi
import permissions.store as pstore
from slash.dispatch import _cmd_status
from slash.dispatch import DispatchContext


def _ctx(session_id: str = "s1") -> DispatchContext:
	return DispatchContext(session_id=session_id, workspace="")


def test_pending_store_failure_is_reported_not_hidden() -> None:
	"""缺陷回归：读待批准炸了，界面上必须写"读不出"，不能整行蒸发。"""

	def boom(self, session_id: str):
		raise OSError("permission store unreadable")

	original = pstore.PendingPermissionStore.pending_for_session
	pstore.PendingPermissionStore.pending_for_session = boom
	try:
		res = _cmd_status(_ctx(), "")
	finally:
		pstore.PendingPermissionStore.pending_for_session = original
	text = str(res.message)
	assert "待批准" in text, f"整行被静默省略（消息={text!r}）"
	assert "读不出" in text, text
	assert res.result.get("pending_permission_error"), res.result


def test_jobs_store_failure_is_reported_not_hidden() -> None:
	def boom(*args, **kwargs):
		raise RuntimeError("channel store down")

	original = capi.get_store
	capi.get_store = boom
	try:
		res = _cmd_status(_ctx(), "")
	finally:
		capi.get_store = original
	text = str(res.message)
	assert "最近任务" in text and "读不出" in text, text
	assert res.result.get("recent_jobs_error"), res.result


def test_healthy_status_adds_no_error_keys() -> None:
	"""反向对照：一切正常时不许冒出"读不出"噪声。"""
	res = _cmd_status(_ctx(), "")
	text = str(res.message)
	assert "读不出" not in text, text
	assert "pending_permission_error" not in res.result, res.result
	assert "recent_jobs_error" not in res.result, res.result
	assert "会话 s1" in text


def test_real_pending_item_still_renders() -> None:
	"""既有行为不变：真有待批准时那行照旧，且不带"读不出"。"""

	class _Row:
		request_id = "r1"
		tool_name = "Bash"
		prompt = "要跑 rm 吗"

	original = pstore.PendingPermissionStore.pending_for_session
	pstore.PendingPermissionStore.pending_for_session = lambda self, sid: _Row()
	try:
		res = _cmd_status(_ctx(), "")
	finally:
		pstore.PendingPermissionStore.pending_for_session = original
	text = str(res.message)
	assert "待批准 Bash" in text, text
	assert "读不出" not in text
	assert res.result.get("pending_permission", {}).get("request_id") == "r1"


def test_status_command_is_registered() -> None:
	"""判据落在活路径上：/status 必须是注册在册的命令。"""
	from slash.registry import COMMANDS

	assert any(getattr(c, "name", "") == "status" for c in COMMANDS), [
		getattr(c, "name", "") for c in COMMANDS
	]
