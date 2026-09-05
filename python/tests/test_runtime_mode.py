"""RuntimeModeStore 活审批模式：store 语义 + permission_mode 优先级 + 快照广播。

覆盖：严格度排序、T26 单向性（收紧即时/放宽延后）、增量广播（全量/变更/
切回默认/会话清理）、permission_mode() 优先级（store 活值 > body > config）。
"""

from __future__ import annotations

import pytest

from engine.workspace_context import WorkspaceContext, set_workspace_context
from permissions.policy import (
	begin_permission_turn,
	permission_mode,
	set_permission_mode,
)
from permissions.runtime_mode import (
	get_runtime_mode_store,
	normalize_mode,
	runtime_mode_snapshot_text,
	stricter,
)

SID = "rtmt-test-session"


@pytest.fixture
def ws_ctx():
	"""把当前上下文绑到一个测试会话，让 policy._session_id() 取到 sid。"""
	set_workspace_context(WorkspaceContext(session_id=SID, cwd="."))
	yield
	set_workspace_context(None)


def _clear() -> None:
	get_runtime_mode_store().clear(SID)


# ── 纯 store 单元（无需 workspace context）──────────────────────────────
def test_normalize_mode() -> None:
	assert normalize_mode("allow") == "never"
	assert normalize_mode("ALWAYS") == "always"
	assert normalize_mode("never") == "never"
	assert normalize_mode("risk") == "risk"
	assert normalize_mode("bogus") is None
	assert normalize_mode("") is None
	assert normalize_mode(None) is None


def test_stricter_ordering() -> None:
	assert stricter("always", "risk") == "always"
	assert stricter("never", "risk") == "risk"
	assert stricter("never", "always") == "always"
	assert stricter("always", "always") == "always"
	assert stricter("risk", "never") == "risk"


def test_store_set_live_effective() -> None:
	store = get_runtime_mode_store()
	_clear()
	assert store.live(SID) is None
	assert store.effective(SID) is None
	assert store.set(SID, "bogus") is None
	assert store.live(SID) is None
	assert store.set(SID, "never") == "never"
	assert store.live(SID) == "never"
	# 无基线时 effective = requested。
	assert store.effective(SID) == "never"
	_clear()


def test_tighten_immediate_relax_deferred() -> None:
	store = get_runtime_mode_store()
	_clear()
	# 轮首基线 = requestd(never) —— 宽松基线。
	store.set(SID, "never")
	base = store.begin_turn(SID, "risk")
	assert base == "never"
	# 收紧：把活值切到 always → 本轮 effective 立即取 always（更严）。
	store.set(SID, "always")
	assert store.effective(SID) == "always"
	# 放宽：把活值切回 never → 本轮仍保持较严基线（always），不静默放行。
	store.set(SID, "never")
	assert store.effective(SID) == "always"
	# 下一 turn 边界才拍定放宽：基线 = 活值(never)。
	assert store.begin_turn(SID, "risk") == "never"
	_clear()


def test_broadcast_turn_first_only() -> None:
	store = get_runtime_mode_store()
	_clear()
	# 本轮首即有活值 → armed；turn 首发一次。
	store.set(SID, "always")
	assert store.begin_turn(SID, "risk") == "always"
	assert store.mark_turn_broadcast(SID, "always") is True
	# 同 turn 不再重复（#1：轮内不再注入）。
	assert store.mark_turn_broadcast(SID, "always") is False
	store.set(SID, "never")  # 轮中改动（放宽/收紧），effective 仍取更严
	assert store.mark_turn_broadcast(SID, "always") is False
	# 下一 turn 首：复位后重新武装 → 再发。
	assert store.begin_turn(SID, "risk") == "never"
	assert store.mark_turn_broadcast(SID, "never") is True
	# 会话清理后：不再武装。
	store.clear(SID)
	assert store.mark_turn_broadcast(SID, "always") is False


def test_broadcast_skips_midturn_appearance() -> None:
	store = get_runtime_mode_store()
	_clear()
	# turn 首无活值 → 不武装；轮中才出现活值不该注入（#1）。
	store.begin_turn(SID, "risk")
	assert store.mark_turn_broadcast(SID, "always") is False
	store.set(SID, "always")
	assert store.mark_turn_broadcast(SID, "always") is False  # 轮中不注入
	# 下一 turn 首：有活值 → 武装 → 广播。
	store.begin_turn(SID, "risk")
	assert store.mark_turn_broadcast(SID, "always") is True
	_clear()


def test_snapshot_text_states_background() -> None:
	text = runtime_mode_snapshot_text("always")
	assert "background only" in text
	assert "supersedes" in text
	assert "当前审批模式: always" in text
	# #2：纯状态陈述，不含引导/要求性措辞。
	for hint in ("继续", "请", "按当前", "需要你"):
		assert hint not in text


# ── permission_mode() 优先级（store > body > config）─────────────────────
def test_permission_mode_store_beats_body(monkeypatch: pytest.MonkeyPatch, ws_ctx) -> None:
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	_clear()
	try:
		set_permission_mode("risk")  # body 显式 risk
		get_runtime_mode_store().set(SID, "never")
		# store 活值（你刚点的）盖过 body 快照。
		assert permission_mode() == "never"
	finally:
		set_permission_mode(None)
		_clear()


def test_permission_mode_body_when_store_empty(
	monkeypatch: pytest.MonkeyPatch, ws_ctx
) -> None:
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	_clear()
	try:
		set_permission_mode("always")
		assert permission_mode() == "always"
	finally:
		set_permission_mode(None)
		_clear()


def test_permission_mode_config_default(monkeypatch: pytest.MonkeyPatch, ws_ctx) -> None:
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	_clear()
	try:
		assert permission_mode() == "risk"
	finally:
		_clear()


def test_begin_permission_turn_tightens_immediately(
	monkeypatch: pytest.MonkeyPatch, ws_ctx
) -> None:
	monkeypatch.delenv("XEYO_PERMISSION_MODE", raising=False)
	_clear()
	try:
		set_permission_mode("never")  # body 宽松
		get_runtime_mode_store().set(SID, "never")
		begin_permission_turn(SID)
		get_runtime_mode_store().set(SID, "always")
		# 收紧即时：本轮立即 always。
		assert permission_mode() == "always"
	finally:
		set_permission_mode(None)
		_clear()
