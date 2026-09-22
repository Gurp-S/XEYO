"""T_now v2 留痕面（C 阶段）契约测试：进历史 → 值不变不重注 → 压缩后重注。

链路（与 ``engine/query_loop`` 的边界顺序一致）：
1. 装配轮：``_dedup_round`` 判定「值变了」→ 块照常注入 + 登记留痕条目；
2. 下一个边界：``persist_pending`` 把条目写进 MessageStore + transcript；
3. 此后同 key 同值 → 台账判「值没变」→ 尾部不重发（历史里已有那一版）；
4. 压缩改写历史 → ``invalidate_after_compaction`` 清账 → 下一轮按当前值重注。

失败面：``off`` 档（默认）逐字节等价旧行为；事件类永不过台账。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PATH = Path(__file__).resolve().parents[1]

from msgtypes.message import Message, system_note
from prompt import inject_store
from prompt.pre_llm_inject import _dedup_round
from session.hydrate import message_from_row
from session.message_store import MessageStore
from session.transcript_blobs import row_from_message


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	monkeypatch.delenv(inject_store.FLAG_ENV, raising=False)
	inject_store.get_store().clear()
	yield
	inject_store.get_store().clear()
	monkeypatch.delenv(inject_store.FLAG_ENV, raising=False)


def _round(
	session_id: str,
	tagged: list[tuple[str, str]],
	*,
	visible: frozenset[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
	token = inject_store.begin_round(session_id)
	try:
		return _dedup_round(tagged, visible=visible)
	finally:
		inject_store.end_round(token)


# ------------------------------------------------------------------ 形态 / 往返


def test_system_note_shape_is_not_callable_and_not_user():
	msg = system_note("# Goal\n目标：发布", key="goal", fp="abc123")
	assert msg.role == "system"
	assert msg.hidden is True
	assert msg.note_key == "goal"
	assert msg.note_fp == "abc123"
	assert msg.note_kind == "state"
	# 说话人隔离：既不是 user（引擎文本冒充用户）也不是 assistant（伪工具对）
	assert msg.role not in ("user", "assistant")


def test_note_row_roundtrip(tmp_path):
	msg = system_note("# Goal\n目标：发布", key="goal", fp="abc123")
	row = row_from_message(msg, anchor=tmp_path / "t.jsonl")
	assert row["note_key"] == "goal"
	assert row["note_fp"] == "abc123"
	assert row["note_kind"] == "state"
	back = message_from_row(row)
	assert back is not None
	assert back.hidden is True
	assert back.note_key == "goal"
	assert back.note_fp == "abc123"


def test_plain_message_is_not_hidden():
	assert Message(role="user", content="hi").hidden is False
	row = row_from_message(Message(role="user", content="hi"), anchor=Path("x.jsonl"))
	assert "note_key" not in row


# ------------------------------------------------------------- 值不变不重注


def test_on_mode_skips_unchanged_and_persists_note(tmp_path):
	from engine.t_now_notes import persist_pending

	inject_store.get_store().clear()
	import os

	os.environ[inject_store.FLAG_ENV] = inject_store.MODE_ON
	try:
		store = MessageStore()
		# 第 1 轮：值变了 → 注入 + 登记
		kept = _round("s1", [("goal", "# Goal\n目标：发布")])
		assert [n for n, _ in kept] == ["goal"]
		# 边界：落库进历史（hidden system 条目）
		assert persist_pending(store, session_id="s1", snapshot=None) == 1
		assert len(store) == 1
		assert store.items[0].role == "system"
		assert store.items[0].note_key == "goal"
		# 第 2 轮：同一份值（历史里已有）→ 尾部不重发
		assert _round("s1", [("goal", "# Goal\n目标：发布")]) == []
		# 第 3 轮：值变了 → 重新注入
		assert [n for n, _ in _round("s1", [("goal", "# Goal\n目标：改口径")])] == ["goal"]
		# 同 key 只留最新版本：落库第二条（第二版），旧版仍在历史里
		assert persist_pending(store, session_id="s1", snapshot=None) == 1
		assert len(store) == 2
	finally:
		os.environ.pop(inject_store.FLAG_ENV, None)


def test_compaction_invalidates_ledger_and_reinjects():
	from engine.t_now_notes import invalidate_after_compaction, persist_pending

	store = MessageStore()
	_round("s2", [("compact", "输出精简：开")])
	# 落库成功才算"这一版在可见面"（台账提交）
	assert persist_pending(store, session_id="s2") == 1
	assert _round("s2", [("compact", "输出精简：开")]) == []
	# 压缩改写历史 → 清账 → 下一轮按当前值重注（先压缩、后重注）
	invalidate_after_compaction("s2")
	assert [n for n, _ in _round("s2", [("compact", "输出精简：开")])] == ["compact"]


def test_event_blocks_never_go_through_ledger():
	import os

	os.environ[inject_store.FLAG_ENV] = inject_store.MODE_ON
	try:
		# 事件类（drain 语义）：同一段文本第二次发生也必须第二次送达
		for _ in range(3):
			kept = _round("s3", [("reconcile_events", "# 工具面变更\n新增工具 Foo")])
			assert [n for n, _ in kept] == ["reconcile_events"]
		# 事件类不登记留痕（每次发生都是新事实，不是"当前值"）
		assert inject_store.get_store().pending_count("s3") == 0
	finally:
		os.environ.pop(inject_store.FLAG_ENV, None)


# ----------------------------------------------------------------- 旁路 / 失败面


def test_off_mode_is_byte_identical_and_writes_nothing(monkeypatch):
	# 逃生门 off：不登记、不跳过、不写历史（逐字节回到旧行为）
	monkeypatch.setenv(inject_store.FLAG_ENV, inject_store.MODE_OFF)
	assert inject_store.mode() == inject_store.MODE_OFF
	tagged = [("goal", "# Goal\n目标：发布")]
	assert _round("s4", tagged) == tagged
	assert _round("s4", tagged) == tagged
	assert inject_store.get_store().pending_count("s4") == 0


def test_unpersisted_version_is_reinjected():
	"""留痕没落库成功的版本下一轮照旧重发（绝不"账上有、历史里没有"）。"""
	first = _round("s7", [("goal", "# Goal\n目标：发布")])
	assert [n for n, _ in first] == ["goal"]
	# 故意不调用 persist_pending：台账未提交 ⇒ 不能判「值没变」
	again = _round("s7", [("goal", "# Goal\n目标：发布")])
	assert [n for n, _ in again] == ["goal"]


def test_persist_without_session_is_noop():
	from engine.t_now_notes import persist_pending

	store = MessageStore()
	assert persist_pending(store, session_id="") == 0
	assert len(store) == 0


def test_persist_clears_projection_cache():
	import os

	from engine.t_now_notes import persist_pending

	class _Snap:
		proj_cache = ("sentinel",)

	os.environ[inject_store.FLAG_ENV] = inject_store.MODE_ON
	try:
		_round("s5", [("goal", "# Goal\n目标：发布")])
		snap = _Snap()
		assert persist_pending(MessageStore(), session_id="s5", snapshot=snap) == 1
		assert snap.proj_cache is None
	finally:
		os.environ.pop(inject_store.FLAG_ENV, None)


def test_drain_is_take_and_clear():
	import os

	from engine.t_now_notes import persist_pending

	os.environ[inject_store.FLAG_ENV] = inject_store.MODE_ON
	try:
		_round("s6", [("goal", "# Goal\n目标：发布")])
		store = MessageStore()
		assert persist_pending(store, session_id="s6") == 1
		# 取走即清：再落库不会重复追加同一条
		assert persist_pending(store, session_id="s6") == 0
		assert len(store) == 1
	finally:
		os.environ.pop(inject_store.FLAG_ENV, None)


# ------------------------------------------------- 真相源 = 本轮投影（不是台账）


def test_visible_face_is_truth_source():
	"""台账说"在历史里"、本轮投影却没有 ⇒ 必须重发（绝不静默丢块）。"""
	from engine.t_now_notes import persist_pending

	text = "# Goal\n目标：发布"
	store = MessageStore()
	_round("s8", [("goal", text)])
	assert persist_pending(store, session_id="s8") == 1
	fp = inject_store.fingerprint(text)
	# 投影里确实有这一版 ⇒ 允许跳过
	assert _round("s8", [("goal", text)], visible=frozenset({("goal", fp)})) == []
	# 投影里没有（历史被改写却没人清账）⇒ 重发，并留下 stale 证据
	assert [n for n, _ in _round("s8", [("goal", text)], visible=frozenset())] == [
		"goal"
	]
	assert inject_store.get_store().stats()["stale"] >= 1


def test_per_block_keys_are_independent():
	"""同名多段各自成键：一段变了只重发那一段。"""
	from prompt.pre_llm_inject import _dedup_round  # noqa: F401  （文档用）

	from engine.t_now_notes import persist_pending

	store = MessageStore()
	_round("s10", [("mode_instructions", "段 A"), ("mode_instructions", "段 B")])
	assert persist_pending(store, session_id="s10") == 2  # 两段 → 两条留痕
	keys = sorted(m.note_key for m in store.items if m.hidden)
	assert keys == ["mode_instructions#0", "mode_instructions#1"]
	visible = frozenset(
		(m.note_key, m.note_fp) for m in store.items if m.hidden
	)
	# 只有第二段变了 ⇒ 只重发第二段
	kept = _round(
		"s10",
		[("mode_instructions", "段 A"), ("mode_instructions", "段 C")],
		visible=visible,
	)
	assert [t for _n, t in kept] == ["段 C"]


# ------------------------------------------------------- A 闸（声道兼容）


def test_allow_notes_false_discards_and_disarms():
	"""A 闸：本轮不是 system 声道 ⇒ 不写留痕、清账，改走 notice 声道重注。"""
	from engine.t_now_notes import persist_pending

	_round("s9", [("goal", "# Goal\n目标：发布")])
	store = MessageStore()
	assert persist_pending(store, session_id="s9", allow_notes=False) == 0
	assert len(store) == 0
	assert inject_store.get_store().stats()["disarmed"].get("s9") == 1
	# 清账后下一轮按当前值重注（不会因为"曾经登记过"而跳过）
	assert [n for n, _ in _round("s9", [("goal", "# Goal\n目标：发布")])] == ["goal"]


# ------------------------------------------- 留痕形态跟随声道（通报片段档）


def test_notice_fragment_carrier_writes_wrapped_user_note():
	"""片段档的留痕 = 带信封的 user 片段（对齐 Codex ContextualUserFragment）。"""
	from engine.t_now_notes import persist_pending
	from prompt.notice_channel import notice_key_of
	from prompt.t_now_strategy import STRATEGY_NOTICE_FRAGMENT

	text = "# Goal\n目标：发布"
	_round("f1", [("goal", text)])
	store = MessageStore()
	assert (
		persist_pending(store, session_id="f1", carrier=STRATEGY_NOTICE_FRAGMENT) == 1
	)
	msg = store.items[0]
	assert msg.role == "user"
	# 身份仍由 note_key 决定：UI 面照样过滤，与形态无关
	assert msg.hidden is True
	assert msg.note_key == "goal"
	assert msg.note_fp == inject_store.fingerprint(text)
	# 信封自述维度 ⇒ 落库后仍能被认出、被替换、被单独计预算
	assert notice_key_of(msg.content) == "goal"
	assert text in msg.content


def test_notice_fragment_carrier_keeps_dedup_alive():
	"""「值不变不重注」在片段档同样成立（2026-09-21 事故：默认档换成片段后，
	A 闸仍按"只有 system 声道才落留痕"判定 ⇒ 留痕每轮被丢弃并清账，7 个状态块
	退化成每个边界重发一次）。"""
	from engine.t_now_notes import persist_pending
	from prompt.t_now_strategy import STRATEGY_NOTICE_FRAGMENT

	text = "# Goal\n目标：发布"
	store = MessageStore()
	_round("f2", [("goal", text)])
	assert (
		persist_pending(store, session_id="f2", carrier=STRATEGY_NOTICE_FRAGMENT) == 1
	)
	visible = frozenset(store.note_fingerprints())
	assert ("goal", inject_store.fingerprint(text)) in visible
	assert _round("f2", [("goal", text)], visible=visible) == []
	# 值变了 ⇒ 重新注入（并按 key 折叠掉旧版，见 test_per_block_keys_are_independent）
	assert [
		n for n, _ in _round("f2", [("goal", "# Goal\n目标：改口径")], visible=visible)
	] == ["goal"]


def test_a_gate_hides_only_system_shaped_notes():
	"""A 闸只管 system 形态：降到片段档后，降级前落库的 system 留痕必须继续逐出
	（否则厂商每次请求又吃中段 system ⇒ 逐枪 4xx），而 user 形态照常携带。"""
	from engine.t_now_notes import persist_pending
	from prompt.t_now_strategy import (
		STRATEGY_NOTICE_FRAGMENT,
		STRATEGY_SYSTEM_CHANNEL,
	)

	system_text = "# Goal\n甲"
	fragment_text = "输出精简：开"
	store = MessageStore()
	_round("f3", [("goal", system_text)])
	assert (
		persist_pending(store, session_id="f3", carrier=STRATEGY_SYSTEM_CHANNEL) == 1
	)
	_round("f3", [("compact", fragment_text)])
	assert (
		persist_pending(store, session_id="f3", carrier=STRATEGY_NOTICE_FRAGMENT) == 1
	)
	assert [m.role for m in store.items] == ["system", "user"]
	store.set_note_policy(False)
	projected = store.as_api_messages()
	assert [m["role"] for m in projected] == ["user"]
	assert fragment_text in projected[0]["content"]
	assert system_text not in projected[0]["content"]
	# 可见面口径与投影一致：被逐出的 system 留痕不得算"还在模型面前"
	assert store.note_fingerprints() == {
		("compact", inject_store.fingerprint(fragment_text))
	}


def test_note_carriers_cover_both_shaped_arms():
	from engine.t_now_notes import NOTE_CARRIERS
	from prompt.t_now_strategy import (
		STRATEGY_NOTICE_FRAGMENT,
		STRATEGY_SYSTEM_CHANNEL,
	)

	assert NOTE_CARRIERS == frozenset({STRATEGY_SYSTEM_CHANNEL, STRATEGY_NOTICE_FRAGMENT})


def test_query_loop_passes_resolved_carrier_to_persist():
	"""接线门：留痕形态必须由解析出的声道决定，不得在调用点写死。"""
	src = (
		_PATH / "engine" / "query_loop.py"
	).read_text(encoding="utf-8")
	assert "carrier=_note_carrier" in src
	assert "allow_notes=_notes_ok" in src
	assert "_notes_ok = _note_carrier in NOTE_CARRIERS" in src


def test_fingerprint_is_128bit():
	assert len(inject_store.fingerprint("任意文本")) == 32


def test_retract_marks_only_that_dimension_and_keeps_the_row():
	"""撤回 = 逐出模型投影，不删历史行（审计/恢复仍要能取出那一版）。"""
	from engine.t_now_notes import persist_pending
	from prompt.pre_llm_inject import _aggregate_state_sections
	from prompt.t_now_strategy import STRATEGY_NOTICE_FRAGMENT

	# 台账默认 on（autouse 夹具已清 env），这里不再自己写环境变量
	tagged = _aggregate_state_sections([("goal", "# Goal\n甲"), ("compact", "输出精简：开")])
	assert [n for n, _ in tagged] == ["world_state"]
	_round("r1", tagged)
	store = MessageStore()
	assert persist_pending(store, session_id="r1", carrier=STRATEGY_NOTICE_FRAGMENT) == 1
	key = store.items[0].note_key
	assert key == "world_state"
	assert store.retract_note("goal") == 0, "没有这个维度就什么都不动"
	assert store.retract_note(key) == 1
	assert "输出精简" not in str(store.as_api_messages())
	assert store.items[0].hidden is True  # 历史面原样保留
	# 投影可见面也不该再报它"还在模型面前"
	assert store.note_fingerprints() == set()


def test_retraction_is_cancelled_when_the_state_comes_back():
	"""撤回还挂着、同维度又产出正文 ⇒ 撤回作废：状态回来了就不该把它逐出投影。"""
	assert inject_store.mode() == inject_store.MODE_ON
	store = inject_store.get_store()
	_round("r2", [("goal", "# Goal\n甲")])
	assert store.drain_notes("r2"), "前置：上一轮的留痕已落库（待撤回只看台账）"
	assert store.retract("r2", "goal") is True
	_round("r2", [("goal", "# Goal\n乙")])  # 状态又回来 ⇒ note() 撤销待撤回
	assert store.take_retractions("r2") == []
	# 反向：本轮没有任何正文 ⇒ 撤回登记成功
	store.drain_notes("r2")
	assert store.retract("r2", "goal") is True
	assert store.take_retractions("r2") == ["goal"]
