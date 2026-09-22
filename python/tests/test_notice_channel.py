"""阶段 2 的门：环境通报载体形态与降级阶梯。

事故原型：2026-09-15 默认档切到声道 B 后，``query_loop`` 的首轮嗅探仍硬编码
伪对（"改一处漏一处"）；而厂商拒 system 角色时旧阶梯降级到 ``env_channel``，
一次降级同时欠下假 id 的 ``reasoning_content`` 校验、无主 tool_result、以及
模型模仿 ``xeyo_env_notice`` 的 affordance（实测单会话 60-70+ 次）。
"""

from __future__ import annotations

import pytest

from typing import Any

from prompt.notice_channel import (
	NOTICE_ENVELOPE_CLOSE,
	NOTICE_ENVELOPE_OPEN,
	WORLD_STATE_KEY,
	append_notice_fragment,
	is_notice_text,
	matches_notice_text,
	notice_key_of,
	render_notice,
	strip_notice_fragments,
	truncate_notice_body,
	wrap_notice,
)
from prompt.t_now_strategy import (
	STRATEGY_ENV_CHANNEL,
	STRATEGY_NOTICE_FRAGMENT,
	STRATEGY_SKIP,
	STRATEGY_SYSTEM_CHANNEL,
	env_unsupported_key,
	mark_notice_fragment_unsupported,
	mark_system_channel_unsupported,
	resolve_t_now_strategy,
	reset_fragment_unsupported_for_test,
	reset_system_unsupported_for_test,
	set_t_now_strategy,
)

HOST = [{"role": "user", "content": "把登录页改掉"}]


@pytest.fixture(autouse=True)
def _clean_state():
	reset_system_unsupported_for_test()
	reset_fragment_unsupported_for_test()
	set_t_now_strategy(None)
	yield
	reset_system_unsupported_for_test()
	reset_fragment_unsupported_for_test()
	set_t_now_strategy(None)


def test_production_ladder_never_falls_back_to_forged_pairs() -> None:
	"""厂商拒 mid-history system 时降级到包封片段，**不再**降级到伪对。"""
	key = env_unsupported_key("deepseek", "deepseek-v4-flash")
	mark_system_channel_unsupported(key)
	set_t_now_strategy(STRATEGY_SYSTEM_CHANNEL)
	got = resolve_t_now_strategy("deepseek", "deepseek-v4-flash")
	assert got == STRATEGY_NOTICE_FRAGMENT


def test_no_ladder_state_can_reach_the_forged_pair_arm() -> None:
	"""任何备忘组合下，生产阶梯都不能解析到 ``env_channel``。

	wire 层已不再替伪对补 ``reasoning_content``（2026-09-22 退役），所以一旦有
	路径悄悄退回伪对档，思考模式厂商就当场 400。这条门把"伪对只能显式点名"
	钉成断言：阶梯尽头是 skip，不是伪对。
	"""
	key = env_unsupported_key("deepseek", "deepseek-v4-flash")
	mark_system_channel_unsupported(key)
	mark_notice_fragment_unsupported(key)
	for explicit in (None, STRATEGY_SYSTEM_CHANNEL, "prefill", "legacy"):
		set_t_now_strategy(explicit)
		got = resolve_t_now_strategy("deepseek", "deepseek-v4-flash")
		assert got != STRATEGY_ENV_CHANNEL, f"{explicit} 档悄悄退回伪对：{got}"
	set_t_now_strategy(None)
	assert resolve_t_now_strategy("deepseek", "deepseek-v4-flash") == STRATEGY_SKIP


def test_only_env_channel_puts_a_tool_shape_in_the_projection() -> None:
	"""不可调用性来自形态：除显式对照档外，投影里不得出现 tool_use 形状。"""
	for strategy in (STRATEGY_SYSTEM_CHANNEL, STRATEGY_NOTICE_FRAGMENT, STRATEGY_SKIP):
		out = render_notice(HOST, "工作区有外部改动", strategy=strategy)
		blobs = [str(m) for m in out]
		assert not any("tool_use" in b for b in blobs), f"{strategy} 泄漏了可调用形状"
	env = render_notice(HOST, "工作区有外部改动", strategy=STRATEGY_ENV_CHANNEL)
	assert any("tool_use" in str(m) for m in env), "对照档应仍是伪对形态"


def test_fragment_carrier_is_recognizable_and_round_trips() -> None:
	out = append_notice_fragment(HOST, "后台任务 bash-1 已结束")
	assert out[-1]["role"] == "user"
	body = out[-1]["content"]
	assert is_notice_text(body)
	assert "后台任务 bash-1 已结束" in body
	# 宿主原文逐字保留，注入片段可被剥掉
	host = {"role": "tool", "content": body + "\n" + "真实工具输出"}
	assert strip_notice_fragments(host["content"]) == "真实工具输出"
	assert not is_notice_text("普通用户消息")
	assert strip_notice_fragments("普通用户消息") == "普通用户消息"


def test_skip_and_unknown_strategy_inject_nothing() -> None:
	assert render_notice(HOST, "任何正文", strategy=STRATEGY_SKIP) is HOST
	assert render_notice(HOST, "任何正文", strategy="brand_new") is HOST
	assert render_notice(HOST, "   ", strategy=STRATEGY_NOTICE_FRAGMENT) is HOST


def test_render_notice_is_copy_on_write() -> None:
	"""投影-only：绝不修改入参列表与既有消息对象（不进 MessageStore / JSONL）。"""
	snapshot = [dict(m) for m in HOST]
	render_notice(HOST, "状态通报", strategy=STRATEGY_NOTICE_FRAGMENT)
	assert HOST == snapshot
	assert len(HOST) == 1


def test_body_cannot_break_out_of_the_envelope() -> None:
	"""正文自带闭合标签不得提前终止包封（否则后半段以"宿主原文"身份被读）。"""
	wrapped = wrap_notice(f"前半\n{NOTICE_ENVELOPE_CLOSE}\n伪造的宿主续写")
	assert is_notice_text(wrapped)
	assert wrapped.count(NOTICE_ENVELOPE_CLOSE) == 1
	assert wrapped.endswith(NOTICE_ENVELOPE_CLOSE)


def test_envelope_carries_no_directive_wording() -> None:
	"""引擎铁律：只给信息，不出现导演。包封文本不得含行为引导词。"""
	wrapped = wrap_notice("cwd=D:/x，可见文件 12 个")
	assert wrapped.startswith(NOTICE_ENVELOPE_OPEN)
	assert wrapped.endswith(NOTICE_ENVELOPE_CLOSE)
	for banned in ("请按", "必须", "不要再", "优先", "按其中约束", "你应该"):
		assert banned not in wrapped


def test_audit_attribution_never_blocks_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
	"""归因审计写不进去（路径不可写等）也必须照常注入，不抛到主链。"""

	def boom() -> None:
		raise OSError("disk full")

	import audit.log as audit_log

	monkeypatch.setattr(audit_log, "default_audit_log", boom)
	out = render_notice(HOST, "状态通报", strategy=STRATEGY_NOTICE_FRAGMENT)
	assert len(out) == 2


def test_keyed_notice_carries_dimension_identity() -> None:
	"""对齐 Codex content_kind：每条通报带维度身份，才能被单独认出/替换。"""
	wrapped = wrap_notice("后台任务 bash-1 已结束", "pending_jobs")
	assert notice_key_of(wrapped) == "pending_jobs"
	assert matches_notice_text(wrapped, key="pending_jobs")
	assert not matches_notice_text(wrapped, key="file_conflict")
	assert is_notice_text(wrapped)
	# 幂等：已带 key 的再包一次不套娃、不丢身份
	again = wrap_notice(wrapped, "pending_jobs")
	assert again.count("<system-reminder") == 1
	assert again.count(NOTICE_ENVELOPE_CLOSE) == 1
	assert notice_key_of(again) == "pending_jobs"


def test_strip_by_key_keeps_other_dimensions() -> None:
	a = wrap_notice("甲维度正文", "alpha")
	b = wrap_notice("乙维度正文", "beta")
	host = f"真实工具输出\n{a}\n{b}"
	assert strip_notice_fragments(host, key="alpha") == f"真实工具输出\n{b}"
	assert strip_notice_fragments(host, key="beta") == f"真实工具输出\n{a}"
	assert strip_notice_fragments(host) == "真实工具输出"


def test_notice_body_is_middle_truncated() -> None:
	body = "H" * 3000 + "T" * 3000
	wrapped = wrap_notice(body)
	assert len(wrapped) < len(body)
	assert "H" * 200 in wrapped and "T" * 200 in wrapped
	assert "[中段已截断]" in wrapped
	assert truncate_notice_body("短正文") == "短正文"


def test_render_notice_passes_dimension_into_carrier() -> None:
	out = render_notice(
		[{"role": "user", "content": "改代码"}],
		"cwd=D:/demo",
		strategy=STRATEGY_NOTICE_FRAGMENT,
		dimension="workspace_state",
	)
	assert notice_key_of(out[-1]["content"]) == "workspace_state"


def test_default_arm_delivers_state_as_one_world_state_fragment(
	monkeypatch,
) -> None:
	"""端到端：默认档把当前态合成**一条** world_state 片段，事件各自独立成条。"""
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	monkeypatch.setattr(
		"prompt.pre_llm_inject.browser_preview_block",
		lambda: "# 浏览器预览（background only）\nurl: http://localhost:5173",
	)
	set_t_now_strategy(None)
	projected = [
		{"role": "user", "content": "把 loadUser 改成带缓存的"},
		{"role": "assistant", "content": "先看现状。"},
	]
	out = run_pre_llm_inject(
		projected,
		InjectContext(cwd="D:/demo", multi_agent=True, include_memory_index=True),
	)
	fragments = [m for m in out if isinstance(m.get("content"), str) and is_notice_text(m["content"])]
	assert all(m["role"] == "user" for m in fragments)
	keys = [notice_key_of(m["content"]) for m in fragments]
	assert len(set(keys)) == len(keys), f"同一次投影里 key 不得重复：{keys}"
	state = [m for m in fragments if notice_key_of(m["content"]) == WORLD_STATE_KEY]
	assert len(state) == 1, f"当前态必须合成一条整段，实得 {len(state)} 条"
	# 整段里每个组件仍各自带自己的标题 ⇒ 维度身份在段内可见
	assert "multi-agent" in state[0]["content"]
	assert "http://localhost:5173" in state[0]["content"]
	assert not _has_tool_shape(out)


def test_world_state_aggregate_retracts_a_section_that_stopped_existing():
	"""聚合真正买到的东西：某个状态消失 ⇒ 整段文本变了 ⇒ 重发并把旧版折出投影。

	逐块台账表达不了"不再存在"：那一版会一直挂在投影里当真（退出 Ask 模式后
	模型仍看到"Ask 只读"）。这是改聚合的全部理由，故按行为证，不按源码 grep 证。
	"""
	from engine.t_now_notes import persist_pending
	from prompt import inject_store
	from prompt.pre_llm_inject import (
		_aggregate_state_sections,
		_dedup_round,
	)
	from session.message_store import MessageStore

	inject_store.get_store().clear()
	store = MessageStore()
	ask = "# Ask 模式（background only）\n只读，不得写盘"
	preview = "# 浏览器预览（background only）\nurl: http://localhost:5173"

	def _round(tagged, *, visible):
		token = inject_store.begin_round("w1")
		try:
			return _dedup_round(_aggregate_state_sections(tagged), visible=visible)
		finally:
			inject_store.end_round(token)

	kept = _round([("mode_instructions", ask), ("browser_preview", preview)], visible=None)
	assert [n for n, _ in kept] == [WORLD_STATE_KEY]
	assert kept[0][1] == f"{ask}\n\n{preview}"
	assert persist_pending(store, session_id="w1", carrier=STRATEGY_NOTICE_FRAGMENT) == 1
	visible = frozenset(store.note_fingerprints())
	# 值没变 ⇒ 整段不重发（省的就是"每边界重发同一状态"）
	assert _round([("mode_instructions", ask), ("browser_preview", preview)], visible=visible) == []
	# 用户退出 Ask 模式：只剩预览 ⇒ 整段变了 ⇒ 必须重发
	gone = _round([("browser_preview", preview)], visible=visible)
	assert [t for _n, t in gone] == [preview]
	assert persist_pending(store, session_id="w1", carrier=STRATEGY_NOTICE_FRAGMENT) == 1
	# 投影按维度只留最新版 ⇒ 旧的"Ask 只读"那一版已从模型面前撤走
	projected = str(store.as_api_messages())
	assert "url: http://localhost:5173" in projected
	assert "只读，不得写盘" not in projected


def _has_tool_shape(messages: list[dict[str, Any]]) -> bool:
	for m in messages:
		content = m.get("content")
		if isinstance(content, list) and any(
			isinstance(b, dict) and b.get("type") == "tool_use" for b in content
		):
			return True
	return False


# ────────────────────── 说话人归属：落库的通报留痕不是"用户说的话"


def test_is_notice_message_covers_both_identities():
	"""两级判据：结构化 note_key 优先，投影 dict 只能按包封词法兜底。"""
	from msgtypes.message import notice_note, user_message
	from prompt.notice_channel import is_notice_message, wrap_notice

	assert is_notice_message(
		{"role": "user", "content": wrap_notice("# Goal\n甲", key="goal")}
	) is True
	assert is_notice_message(
		{"role": "user", "note_key": "goal", "content": "# Goal\n甲"}
	) is True
	assert is_notice_message(
		notice_note(wrap_notice("# Goal\n甲", key="goal"), key="goal", fp="f")
	) is True
	assert is_notice_message({"role": "user", "content": "把 loadUser 改成带缓存的"}) is False
	assert is_notice_message(user_message("继续")) is False
	# 宿主原文里夹了片段（legacy 尾插）：整条仍是用户消息，不得误判
	host_and_fragment = "改一下 loadUser\n" + wrap_notice("# Goal\n甲", key="goal")
	assert is_notice_message({"role": "user", "content": host_and_fragment}) is False


def test_session_md_current_is_the_human_not_an_injected_notice():
	"""事故回归：通报片段落成 role=user 后，会话摘要的 goal/current 会写成引擎自己。"""
	from memory.session_md import _extract
	from prompt.notice_channel import wrap_notice

	f = _extract(
		[
			{"role": "user", "content": "把 loadUser 改成带缓存的"},
			{"role": "assistant", "content": "先看现状。"},
			{"role": "user", "content": wrap_notice("# Goal\n目标：发布", key="goal")},
		]
	)
	assert "loadUser" in f["current"]
	assert "system-reminder" not in f["current"]
	assert "目标：发布" not in f["current"]
	assert "loadUser" in f["goal"]


def test_rewind_turn_anchors_skip_notice_rows():
	"""事故回归：每个边界一条 user 形态留痕 ⇒ 平白多出一串可回退的"轮"。"""
	from prompt.notice_channel import wrap_notice
	from rewind.service import _is_user_turn_row

	assert _is_user_turn_row({"role": "user", "id": "m1", "content": "继续"}) is True
	assert (
		_is_user_turn_row(
			{
				"role": "user",
				"id": "n1",
				"content": wrap_notice("# Goal\n甲", key="goal"),
			}
		)
		is False
	)
	assert (
		_is_user_turn_row({"role": "user", "id": "n2", "note_key": "goal", "content": "# Goal\n甲"})
		is False
	)
	assert _is_user_turn_row({"role": "assistant", "id": "a1", "content": "好"}) is False


def test_last_user_text_skips_persisted_notice_tail():
	"""技能直呼读末条 user：尾部的留痕必须跳过（曾无条件读 projected[-1]）。"""
	from prompt.notice_channel import wrap_notice
	from prompt.pre_llm_inject import _last_user_text

	assert (
		_last_user_text(
			[
				{"role": "user", "content": "/pdf 转成 markdown"},
				{"role": "assistant", "content": "好"},
				{"role": "user", "content": wrap_notice("# Continue\n…", key="continue")},
			]
		)
		== "/pdf 转成 markdown"
	)


def test_c2_summary_does_not_charge_notices_to_the_user_pool():
	"""事故回归：留痕算成 user 会抢 C2 摘要的用户子池，把真实用户轮挤成 metadata。"""
	from memory.runtime import _msg_kind, _role_group
	from prompt.notice_channel import wrap_notice

	note = {"role": "user", "content": wrap_notice("# 引擎状态\nurl: x", key="world_state")}
	assert _msg_kind(note) == "notice"
	assert _role_group("notice") == 2  # 0=叙事结论(assistant/user)，2=其它
	assert _role_group(_msg_kind({"role": "user", "content": "把登录页改掉"})) == 0


def test_cadence_user_turns_ignore_persisted_notices():
	"""R 估计按"过了多少用户轮"查表：每边界一条留痕会把 n_user 吹大、推迟折叠。"""
	from memory.simulator.replay import estimate_remaining
	from prompt.notice_channel import wrap_notice

	real = [{"role": "user", "content": f"第{i}问"} for i in range(3)]
	with_notes = [
		*real[:1],
		*[
			{"role": "user", "content": wrap_notice(f"# 状态 {i}", key="world_state")}
			for i in range(8)
		],
		*real[1:],
	]
	assert estimate_remaining(with_notes) == estimate_remaining(real)


def test_replay_counts_exclude_notice_rows():
	"""离线重放同口径：通报行不得算进用户轮/纠偏/反悔。"""
	from memory.simulator.replay import _is_user_text, count_reverts
	from prompt.notice_channel import wrap_notice

	assert _is_user_text({"role": "user", "content": "不对，重来"}) is True
	assert (
		_is_user_text(
			{"role": "user", "content": wrap_notice("# 引擎状态\nx", key="world_state")}
		)
		is False
	)
	msgs = [
		{"role": "user", "content": "把登录页改掉"},
		{"role": "user", "content": wrap_notice("# 引擎状态\n不对，重来", key="world_state")},
	]
	assert count_reverts(msgs) == 0


def test_resume_derived_goal_is_the_human_not_the_state_fragment():
	"""resume 兜底的"上一条用户目标"：尾部状态段不得占掉"最新一条"这个名额。

	该函数刻意跳过最新一条用户消息（那是本轮正在设的目标），取再往前的一条。
	状态段落成 role=user 后，若不过滤：它吃掉"最新"名额 ⇒ 返回的其实是**本轮**
	目标，derived 与 bind 两条路的语义就错位了。
	"""
	from engine.goal_state import _previous_user_goal
	from prompt.notice_channel import wrap_notice

	msgs = [
		{"role": "user", "content": "旧目标：给登录页加校验"},
		{"role": "user", "content": "新目标：把记忆栈改成可回滚"},
		{"role": "assistant", "content": "先看现状"},
		{"role": "user", "content": wrap_notice("# 引擎状态\nurl: x", key="world_state")},
	]
	assert _previous_user_goal(msgs) == "旧目标：给登录页加校验"


def test_ends_with_tool_result_looks_past_persisted_notices():
	"""工具批次后的留痕不是轮边界：走错档就漏 Continue 合同、错挂 MEMORY。"""
	from prompt.notice_channel import wrap_notice
	from prompt.turn_context import ends_with_tool_result

	after_tools = [
		{"role": "user", "content": "跑一下"},
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": "1", "name": "Read"}],
		},
		{"role": "tool", "tool_call_id": "1", "content": "ok"},
	]
	assert ends_with_tool_result(after_tools) is True
	assert (
		ends_with_tool_result(
			[
				*after_tools,
				{"role": "user", "content": wrap_notice("# 引擎状态\nx", key="world_state")},
			]
		)
		is True
	)
	assert ends_with_tool_result([*after_tools, {"role": "user", "content": "新问题"}]) is False


def test_vanishing_state_is_retracted_from_the_projection(monkeypatch):
	"""状态整段变空（聚合差分覆盖不到的那一格）：已作废的那一版必须离开模型投影。"""
	from engine.t_now_notes import persist_pending
	from msgtypes.message import user_message
	from prompt import inject_store
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject
	from prompt.t_now_strategy import STRATEGY_NOTICE_FRAGMENT, set_t_now_strategy
	from session.message_store import MessageStore

	inject_store.get_store().clear()
	set_t_now_strategy(None)
	state = "# 输出精简（background only）\n输出压缩：开"
	monkeypatch.setattr("prompt.pre_llm_inject.compact_block", lambda: state)
	store = MessageStore([user_message("把登录页改掉")])
	projected = [{"role": "user", "content": "把登录页改掉"}]

	def one_round(*, visible) -> list[dict]:
		out = run_pre_llm_inject(
			projected,
			InjectContext(session_id="rz", cwd="", visible_notes=visible),
		)
		persist_pending(store, session_id="rz", carrier=STRATEGY_NOTICE_FRAGMENT)
		return out

	first = one_round(visible=None)
	assert "输出压缩：开" in str(first), "本轮状态要送达模型"
	assert "输出压缩：开" in str(store.as_api_messages()), "那一版已落库进历史"
	# 状态消失：本轮没有任何状态段可发 ⇒ 只能靠撤回，不是靠再发一句话
	monkeypatch.setattr("prompt.pre_llm_inject.compact_block", lambda: "")
	one_round(visible=frozenset(store.note_fingerprints()))
	assert "输出压缩：开" not in str(store.as_api_messages()), "已作废的状态必须离开投影"
	assert inject_store.get_store().stats()["retracted"] >= 1
	# 历史行不删：审计面仍能取出那一版（撤回只影响模型所见）
	assert any(m.note_key == "world_state" for m in store.items)
	# 状态又回来 ⇒ 按新值重注（撤回清过账，不会留"值没变"的死账）
	monkeypatch.setattr("prompt.pre_llm_inject.compact_block", lambda: state)
	back = one_round(visible=frozenset(store.note_fingerprints()))
	assert "输出压缩：开" in str(back)
