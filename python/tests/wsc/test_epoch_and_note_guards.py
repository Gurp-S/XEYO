"""本轮两处"分析/回放"修复的契约测试（防幽灵再犯）。

1) census 纪元边界守卫：同 sid 下 `conv` 重置 ⇒ 该枪按「新对话首枪」计（new=p），
   不计任何重发桶。两个方向都必须绿：**带重置**（归新、桶里没有它）与
   **不带重置**（同样的数值必须落进 unexplained_drop）——只测前者证明不了守卫在起作用。
2) 驱动 `--note-policy temporal` 的逐枪时点过滤：旧版在"新版本到来之前"仍可见，
   新版本到来后旧版才从原位消失（这正是生产 `current_context_items` 的时间行为；
   静态全局去重抹掉了这个时间维度，曾使 note A/B 无判别力）。
3) store 侧 `current_context_items` 的"最早匹配"语义（2026-10-05 产品修复）：
   同内容重复追加不得把实例刷新到尾端；可见内容仍为当前版本、可见行数不变。
4) census「其它重发」分档（lcp_intact/prefix_broken）必须按**本枪** LCP 判：
   旧实现用上一枪的 LCP（off-by-one），两侧错位都在此钉死。
"""

from __future__ import annotations

import pytest

from scripts.wsc_fold_watermark_ab import _temporal_note_filter
from scripts.wsc_miss_census import census

SID = "sess_unit_epoch"


def _row(ts: float, prompt: int, hit: int, conv: int, action: str = "keep") -> dict:
	return {
		"session_id": SID, "provider": "deepseek", "model": "m1", "ts": ts,
		"prompt_tokens": prompt, "observed_hit": hit, "LCP": hit,
		"cache_age": 0.0, "action": action, "conversation_length": conv,
	}


def _base_rows() -> list[dict]:
	# 四枪"全命中"的旧纪元（prompt 递增、miss=0，桶必然为空）
	return [_row(i, i * 1000, i * 1000, i) for i in (1, 2, 3, 4)]


def test_epoch_reset_shot_is_counted_as_new_not_resend() -> None:
	rows = _base_rows() + [
		_row(5, 800, 0, 1),      # 新纪元首枪：整段 miss；不守卫会被记成"重发"
		_row(6, 1600, 800, 2),
	]
	per_family, per_sid, extra, _by_fam, _per_key = census(rows, 64_000)
	c = per_sid[SID]
	assert extra["epoch_boundary"] == 1, "纪元边界枪没有被单列"
	assert c["epoch_boundary"] == 1
	# 整段 miss 已按新增计：命中率/天花板分母不受影响，重发桶必须干净
	assert c["other_resend"] == 0 and c["unexplained_drop"] == 0
	assert c["new"] == 800 + 800   # 边界枪 new=p + 其后一枪的增量
	assert c["miss"] == 800 + 800


def test_without_reset_the_same_numbers_must_land_in_a_resend_bucket() -> None:
	"""反向对照：把 conv 续上（无重置），同样的 800 必须进 unexplained_drop。

	如果这条不红而上面那条红/绿任意——说明守卫改的是"判定谓词"而不是数据本身。
	"""
	rows = _base_rows() + [
		_row(5, 800, 0, 5),      # p 下降且非 C2 ⇒ unexplained_drop
		_row(6, 1600, 800, 6),
	]
	_per_family, per_sid, extra, _by_fam, _per_key = census(rows, 64_000)
	c = per_sid[SID]
	assert extra["epoch_boundary"] == 0
	assert c["unexplained_drop"] == 800, f"无重置时该回落应进 unexplained_drop，实际 {dict(c)}"


def test_resend_intact_uses_current_shot_lcp_not_previous() -> None:
	"""off-by-one 回归：分档看**本枪** LCP（当前跃迁），不是上一枪的。

	链设计（两侧错位都能红）：
	- r2 本枪 LCP=1700（≥0.7×2000）；上一枪 r1 的 LCP=1000（<0.7×2000）
	  ⇒ 旧实现会把 r2 的 1400 误记 prefix_broken；
	- r3 本枪 LCP=100（<0.7×2300）；上一枪 r2 的 LCP=1700（≥0.7×2300）
	  ⇒ 旧实现会把 r3 的 2100 误记 lcp_intact。
	"""
	sid = "sess_unit_intact"
	rows = [
		{"session_id": sid, "provider": "deepseek", "model": "m1", "ts": 1.0,
		 "prompt_tokens": 1000, "observed_hit": 0, "LCP": 0, "cache_age": 0.0,
		 "action": "keep", "conversation_length": 1},
		{"session_id": sid, "provider": "deepseek", "model": "m1", "ts": 2.0,
		 "prompt_tokens": 2000, "observed_hit": 1900, "LCP": 1000, "cache_age": 0.0,
		 "action": "keep", "conversation_length": 2},
		{"session_id": sid, "provider": "deepseek", "model": "m1", "ts": 3.0,
		 "prompt_tokens": 2300, "observed_hit": 600, "LCP": 1700, "cache_age": 0.0,
		 "action": "keep", "conversation_length": 3},
		{"session_id": sid, "provider": "deepseek", "model": "m1", "ts": 4.0,
		 "prompt_tokens": 2600, "observed_hit": 200, "LCP": 100, "cache_age": 0.0,
		 "action": "keep", "conversation_length": 4},
	]
	_per_family, per_sid, extra, _by_fam, _per_key = census(rows, 64_000)
	c = per_sid[sid]
	# r2：miss 1700 − new 300 = 1400；r3：miss 2400 − new 300 = 2100
	assert c["other_resend"] == 1400 + 2100
	assert extra["resend_intact"]["lcp_intact"] == 1400
	assert extra["resend_intact"]["prefix_broken"] == 2100


def test_temporal_note_filter_replaces_only_after_the_new_version_arrives() -> None:
	items = [
		{"role": "user", "content": "a"},
		{"role": "user", "content": "v1", "note_key": "world_state", "note_fp": "f1"},
		{"role": "assistant", "content": "b"},
		{"role": "user", "content": "v2", "note_key": "world_state", "note_fp": "f2"},
		{"role": "user", "content": "c"},
	]
	early = _temporal_note_filter(items[:3])   # 新版本还没来：旧版仍在原位
	assert [m["content"] for m in early] == ["a", "v1", "b"]
	late = _temporal_note_filter(items)        # 新版本到来：旧版才从原位抽走
	assert [m["content"] for m in late] == ["a", "b", "v2", "c"]
	# 时间维度是这条策略与"静态全局去重"的全部区别：早枪必须还能看到当时的旧版
	assert not any(m.get("note_fp") == "f2" for m in early)
	assert not any(m.get("note_fp") == "f1" for m in late)


def test_temporal_fixed_makes_duplicate_append_a_noop() -> None:
	"""候选修法：同内容重复追加不得把实例"刷新"到尾部（前缀零改写）。"""
	from scripts.wsc_fold_watermark_ab import _temporal_fixed_filter

	items = [
		{"role": "user", "content": "a"},
		{"role": "user", "content": "v1", "note_key": "world_state", "note_fp": "f1"},
		{"role": "assistant", "content": "b"},
		{"role": "user", "content": "v1", "note_key": "world_state", "note_fp": "f1"},  # 重复追加（同内容）
		{"role": "user", "content": "c"},
		{"role": "user", "content": "v2", "note_key": "world_state", "note_fp": "f2"},  # 真更新
		{"role": "user", "content": "d"},
	]
	# 修法：实例留在**最早**位置，重复追加那行被吸收 ⇒ 与"没有那次追加"逐字节一致
	fixed = _temporal_fixed_filter(items[:5])
	assert [m["content"] for m in fixed] == ["a", "v1", "b", "c"]
	# 生产形态在同一前缀下会把实例刷到重复追加的位置（这就是那笔无谓重写的来源）
	prod = _temporal_note_filter(items[:5])
	assert [m["content"] for m in prod] == ["a", "b", "v1", "c"]
	# 真更新到来：修法保留新版本的**首个**实例（追加点），旧版本仍被移除
	fixed2 = _temporal_fixed_filter(items)
	assert [m["content"] for m in fixed2] == ["a", "b", "c", "v2", "d"]


def test_current_context_items_pins_latest_authoritative() -> None:
	"""产品语义：当前版本取**最新**实例——别顺手改成"保留最早"。

	2026-10-05 实测教训：naive 的"保留最早匹配"会破坏 `evals/wsc_equal_state.py` 与
	`wsc_state_reuse` 的守卫结构（"吸收后必须重注入，哪怕值相同"——更早位置的复用只能
	走**受可见性守卫**的 reuse 通道）。改选择口径前先读那两处意图注释；
	重复追加这类浪费要从**登记侧**（值没变不重注/可见性判定）治理，不在选择侧硬压。
	"""
	from msgtypes.message import Message
	from session.state_projection import current_context_items

	def note(key: str, text: str, fp: str, retracted: bool = False) -> Message:
		return Message(role="user", content=text, note_kind="state",
		               note_key=key, note_fp=fp, note_retracted=retracted)

	items = [
		Message(role="user", content="q1"),
		note("world_state", "v1", "f1"),
		Message(role="assistant", content="a1"),
		note("world_state", "v1", "f1"),            # 同内容重复追加
		note("world_state", "v2", "f2"),            # 真更新
		note("other", "x1", "f9", retracted=True),  # 撤回的 key：整组剔除
	]
	out = current_context_items(items, include_system_notes=True)
	assert [m.content for m in out] == ["q1", "a1", "v2"]
	assert out[-1] is items[4]          # 留下的是**最新**实例（不是最早那个重复）
	assert sum(1 for m in out if m.note_key) == 1


def test_absorbed_note_not_visible_by_design() -> None:
	"""钉**刻意政策**：吸收进冻结头的留痕不判"可见" ⇒ 折叠/恢复后重注=设计行为。

	两守卫文件原话（改前必读）：`evals/wsc_equal_state.py` "Production selection remains
	unchanged: reinjection after a fold may be required even when the value is identical"
	（shadow-only 不改生产）；`evals/wsc_state_reuse.py` "state already absorbed by compression
	always use latest selection"（被拒候选的守卫式复用：无法证明头文本里的字节在场，故不复用）。
	⚠️ 2026-10-05 我一度把这条刻意的边界框成"修复缺口/真 bug"——**已自纠**：它是**优化项**
	（成本=折叠族 dup+逐出舞步；方向=受可见性守卫的 reuse 通道，候选件在 `evals/wsc_state_reuse.py`
	被拒保留），不是修复缺陷。本用例防的是"顺手把吸收态改判可见"那种会破坏守卫的改动。
	"""
	from msgtypes.message import Message
	from session.message_store import MessageStore

	store = MessageStore(
		[
			Message(role="user", content="q1"),
			Message(
				role="user",
				content='<system-reminder key="world_state">v1</system-reminder>',
				note_kind="state",
				note_key="world_state",
				note_fp="f1",
			),
			Message(role="assistant", content="a1"),
		]
	)
	full = store.as_api_messages()  # 未吸收形态：留痕是带元数据的行
	assert ("world_state", "f1") in store.note_fingerprints(projected=full)
	absorbed = [r for r in full if not r.get("note_key")]  # 吸收形态：行并入头文本，仅剩纯文本
	assert ("world_state", "f1") not in store.note_fingerprints(projected=absorbed)  # 政策：吸收⇒不判可见
