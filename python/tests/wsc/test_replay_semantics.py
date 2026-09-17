"""锁死 adopted（收养后生产语义）口径 —— 2026-09-16 新增。

## 为什么必须有这个文件

`legacy` 档在「未过闸 / 收益门拒绝」时**发整段原文**（`replay.py` 的 raw-prefix 分支），
而生产一旦压过就**每轮都发紧凑投影**，与 decide 动作无关：

  - `memory/runtime.py:1063-1096` `apply_c2_messages` = `[system: 摘要] + project_c0c1(右段)`
  - `memory/runtime.py:1643-1645` `send()`：`if action == "C2" or compact_cursor > 0:` → 走它
  - 水位基准 = **上一枪实际发送的 prompt tokens**（vendor usage）：
    `engine/query_loop.py:1382` → `memory/runtime.py:1910-1914`（`last_prompt_tokens`）

口径错了会把 WSC 的成本**系统性高估**：同一个 200 回合会话实测
legacy 生产口径 cost ratio 1.29（「不能替换 C2」）→ adopted 0.99。所以这三条必须
被机器锁住，而不是靠文档提醒：

  ① 压过之后，未过闸的回合**仍是紧凑态**（`wsc_active=True`），绝不回退整段原文；
  ② 水位基准是**上一轮实际发送**的 token（`sent_tokens`），不是原始前缀估算；
  ③ `legacy` 档逐项行为不变（不许为了新档改动旧档）。
"""

from __future__ import annotations

import json
from pathlib import Path

from synaptic.replay import TurnRecord, run_session
from synaptic.report import Aggregate
from synaptic.types import MODE_CLOSURE, WscParams
from wsc._fixtures import synth_session

_LEVEL = "Medium+"


def _session_file(tmp_path: Path, msgs: list[dict]) -> Path:
	p = tmp_path / "s.jsonl"
	with p.open("w", encoding="utf-8") as fh:
		for m in msgs:
			fh.write(json.dumps(m, ensure_ascii=False) + "\n")
	return p


def _run(tmp_path: Path, msgs: list[dict], **kw):
	path = _session_file(tmp_path, msgs)
	pset = WscParams(mode=MODE_CLOSURE).for_level(_LEVEL)
	return run_session(path, level=_LEVEL, mode=MODE_CLOSURE, params=pset, **kw)


def _folding_session(turns: int = 24) -> list[dict]:
	"""够长、且带工具轮 ⇒ `keep_tail_cut` 能切出非空区域。"""
	return synth_session(turns=turns, error_turn=6, user_every=5)


#: 水位故意压低（合成会话很小）：mark=2000 ⇒ 首压之后每轮都还要再折叠一次。
_FOLD_OFTEN = dict(trigger_ratio=0.5, context_limit_tokens=4000, compact_model="adopted")
#: mark=4000 ⇒ 首压后送出的紧凑投影（~2.5k）**没**越线 ⇒ 存在「未折叠但仍是紧凑态」的回合。
_SPARSE = dict(trigger_ratio=0.5, context_limit_tokens=8000, compact_model="adopted")
#: 水位高到永不触发（legacy 档的判据是原始前缀估算，只有抬高水位才能造出未过闸回合）。
_NEVER = dict(trigger_ratio=0.5, context_limit_tokens=60000, compact_model="legacy")


# ---------------------------------------------------------------------------
# ① 压过之后不许回退整段原文
# ---------------------------------------------------------------------------

def test_adopted_keeps_compact_projection_after_first_fold(tmp_path):
	rec = _run(tmp_path, _folding_session(), **_FOLD_OFTEN)
	events = [i for i, t in enumerate(rec.turns) if t.compaction_event]
	assert events, "低水位下应至少折叠一次（否则本测试没有覆盖到目标分支）"

	after = rec.turns[events[0] + 1 :]
	assert after, "需要至少一个「折叠之后」的回合"
	for t in after:
		assert t.wsc_active is True, f"turn {t.turn}: 压过之后必须一直是紧凑态"
		# 紧凑态 ⇒ 送出的 token 必须显著小于整段原文（不是 raw-prefix 回退）。
		assert t.wsc_tokens < t.base_tokens, f"turn {t.turn}: 紧凑投影应小于整段原文"
		# 非折叠回合：头必须原样携带（不是空头）。
		if not t.compaction_event:
			assert t.hot_tokens > 0, f"turn {t.turn}: 未折叠回合的头不得为空"


def test_legacy_still_falls_back_to_raw_prefix(tmp_path):
	"""legacy 档必须保持历史行为：未过闸 ⇒ 整段原文。"""
	rec = _run(
		tmp_path,
		_folding_session(),
		**_NEVER,
	)
	skipped = [t for t in rec.turns if t.trigger_skipped]
	assert skipped, "低水位下应仍有未过闸回合"
	for t in skipped:
		assert t.wsc_active is False
		assert t.wsc_tokens == t.base_tokens, "legacy 未过闸回合必须发整段原文"


# ---------------------------------------------------------------------------
# ② 水位基准 = 上一枪实际发送的 token
# ---------------------------------------------------------------------------

def test_adopted_watermark_uses_last_sent_tokens(tmp_path):
	rec = _run(tmp_path, _folding_session(), **_FOLD_OFTEN)
	limit = _FOLD_OFTEN["context_limit_tokens"]
	mark = int(_FOLD_OFTEN["trigger_ratio"] * limit)
	for i, t in enumerate(rec.turns):
		if t.compaction_event and i > 0:
			prev = rec.turns[i - 1]
			assert prev.sent_tokens >= mark, (
				f"turn {t.turn}: 折叠只能发生在上一枪 sent_tokens({prev.sent_tokens}) "
				f"越过水位({mark})之后"
			)


def test_adopted_does_not_fold_on_raw_prefix_size(tmp_path):
	"""原始前缀越水位**不等于**该折叠：基准是发出去的那一枪。

    合成会话很短：`base_tokens`（整段原文）可以远大于水位，而实际发送的紧凑投影
    没有越线 ⇒ 不许折叠。这正是 legacy 档的单调判据会误判的地方。
    """
	rec = _run(tmp_path, _folding_session(turns=30), **_SPARSE)
	extra = [
		t
		for t in rec.turns
		if not t.compaction_event and t.wsc_active and t.base_tokens > t.sent_tokens
	]
	assert extra, "需要至少一个「原文很大、但送出去的是紧凑投影」的回合（未折叠的紧凑态回合）"
	for t in extra:
		assert t.sent_tokens == t.wsc_tokens


# ---------------------------------------------------------------------------
# ③ 报告口径：紧凑态回合 / 折叠事件 / 同批回合成本比
# ---------------------------------------------------------------------------

def _turn(session: str, turn: int, *, active: bool, event: bool, base: int, wsc: int,
          wsc_cost: float, v61_cost: float, v61: int) -> TurnRecord:
	return TurnRecord(
		session=session,
		turn=turn,
		mode="closure",
		level=_LEVEL,
		region_end=100,
		n_messages=120,
		base_tokens=base,
		region_raw_tokens=base,
		v61_tokens=v61,
		wsc_tokens=wsc,
		v61_cost=v61_cost,
		wsc_cost=wsc_cost,
		v61_hit=0.5,
		wsc_hit=0.5,
		hot_tokens=wsc,
		tail_tokens=0,
		kept=1,
		pruned=0,
		cards=0,
		rebuilt=False,
		lcp_prev=0,
		latency_ms=1.0,
		wsc_active=active,
		compaction_event=event,
	)


def test_report_reports_active_turns_and_same_turn_cost_ratio():
	agg = Aggregate(label="t", level=_LEVEL, mode=MODE_CLOSURE, n_sessions=1, n_turns=3)
	agg.turns = [
		# 未压过：原文直发（不计入紧凑态口径）
		_turn("s", 0, active=False, event=False, base=1000, wsc=1000, wsc_cost=1.0,
		      v61_cost=1.0, v61=1000),
		# 折叠事件 + 紧凑态
		_turn("s", 1, active=True, event=True, base=1000, wsc=200, wsc_cost=2.0,
		      v61_cost=4.0, v61=1000),
		# 未折叠但仍是紧凑态（adopted 的核心：不算 event，但算 active）
		_turn("s", 2, active=True, event=False, base=1200, wsc=250, wsc_cost=2.0,
		      v61_cost=4.0, v61=1200),
	]
	s = agg.summary()
	assert s["wsc_active_turns"] == 2
	assert s["wsc_active_rate"] == 2 / 3
	assert s["compaction_events"] == 1
	assert s["cost_ratio_wsc_v61_active"] == 4.0 / 8.0
	assert s["cost_ratio_wsc_v61_active_n"] == 2
	# 紧凑态口径的压缩率只统计 active 回合：(1 - 200/1000) 与 (1 - 250/1200)
	red = s["reduction_vs_base_active_only"]
	assert abs(red["mean"] - ((0.8 + (1 - 250 / 1200)) / 2)) < 1e-9
