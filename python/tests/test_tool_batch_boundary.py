"""工具批次边界回归（2026-09-20 事故）。

## 事故形态（真实产物：codex_holdout_v1 6 任务 / 838 回合）

Codex / OpenAI 形态把**并行批次拆成连续多条 assistant 消息**（一条消息一个调用）：

```
27 assistant tool_use call_00      <- 声明 A1
28 assistant tool_use call_01      <- 声明 A2（同批）
29 tool     tool_result call_00    <- A1 的结果
30 tool     tool_result call_01    <- A2 的结果
```

旧的配对模型 = 「一条 assistant + 紧随其后的结果」⇒ 得到 ``(27, 28)`` 这种**不含任何
结果**的退化区间 + ``(28, 31)``。于是保尾边界可以落在 27 与 28 之间：A2 的调用留在
尾部、A1 的结果（29）也在尾部，而 A1 的声明（27）已被压进区域 ⇒ 候选序列首个结果
指向「已被压缩掉的调用」= ``orphan_tool_result`` ⇒ 调用方只能整体回退。

产物 `replay_after_dead_transport_v1.json` 里 9 条 ``broken_tool_pair`` 全部是这一形态
（workspace_ui_controls 6 条 + workspace_window_layout 3 条），且 ``audit`` 逐条给出
`unexpected_result_ids` / `pending_ids`，与本模型预测一致。

## 契约

① 并行整批（多条 assistant + 结果）算**一个**区间；
② 保尾切点/配对安全切点永不落在批次中间；
③ XEYO 形态（一条 assistant 带全部调用）行为不变；
④ 切完之后的尾部永远没有「结果先于其调用」。
"""

from __future__ import annotations

import pytest

from engine.compact import keep_tail_cut, tool_pair_ranges
from memory.runtime import pair_safe_cut
from synaptic.textutil import tool_result_blocks, tool_use_blocks


def _use(uid: str) -> dict:
	return {"role": "assistant", "content": [
		{"type": "tool_use", "id": uid, "name": "exec_command", "input": {"cmd": uid}},
	]}


def _result(uid: str) -> dict:
	return {"role": "tool", "content": [
		{"type": "tool_result", "tool_use_id": uid, "content": f"out {uid}"},
	]}


def _text(text: str = "看一下") -> dict:
	return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def _user(text: str = "目标") -> dict:
	return {"role": "user", "content": text}


def codex_shape(rounds: int = 4, per_batch: int = 2) -> list[dict]:
	"""Codex 形态：每批 ``per_batch`` 条 assistant（各一个调用）+ 结果。"""
	msgs = [_user()]
	for r in range(rounds):
		ids = [f"call_{r}_{k}" for k in range(per_batch)]
		msgs.extend(_use(uid) for uid in ids)
		msgs.extend(_result(uid) for uid in ids)
		msgs.append(_text(f"第 {r} 轮"))
	return msgs


def xeyo_shape(rounds: int = 4, per_batch: int = 2) -> list[dict]:
	"""XEYO 形态：一条 assistant 带该批全部调用，结果紧随其后。"""
	msgs = [_user()]
	for r in range(rounds):
		ids = [f"call_{r}_{k}" for k in range(per_batch)]
		msgs.append({"role": "assistant", "content": [
			{"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": uid}} for uid in ids
		]})
		msgs.extend(_result(uid) for uid in ids)
		msgs.append(_text(f"第 {r} 轮"))
	return msgs


def batches(messages: list[dict]) -> list[tuple[int, int]]:
	"""真批次区间（对照实现，独立于被测代码）。"""
	spans: list[tuple[int, int]] = []
	i, n = 0, len(messages)
	while i < n:
		if not tool_use_blocks(messages[i]):
			i += 1
			continue
		j = i + 1
		while j < n and tool_use_blocks(messages[j]) and not tool_result_blocks(messages[j]):
			j += 1
		while j < n and tool_result_blocks(messages[j]):
			j += 1
		spans.append((i, j))
		i = j
	return spans


def orphan_in_tail(messages: list[dict], cut: int) -> list[str]:
	"""尾部（cut 之后）里「结果先于其调用」的 id 列表。"""
	pending: set[str] = set()
	out: list[str] = []
	for msg in messages[cut:]:
		uses = {str(b.get("id")) for b in tool_use_blocks(msg) if b.get("id")}
		results = {
			str(b.get("tool_use_id")) for b in tool_result_blocks(msg) if b.get("tool_use_id")
		}
		out.extend(sorted(results - pending))
		pending.difference_update(results)
		pending.update(uses)
	return out


# ---------------------------------------------------------------------------
# ① 批次算一个区间
# ---------------------------------------------------------------------------


def test_parallel_batch_is_one_range():
	msgs = codex_shape(rounds=2, per_batch=2)
	ranges = tool_pair_ranges(msgs)
	spans = batches(msgs)
	assert ranges == spans, f"并行批次没有被当成一个区间：{ranges} vs {spans}"
	assert len(ranges) == 2, ranges


def test_single_message_batch_unchanged():
	msgs = xeyo_shape(rounds=3, per_batch=3)
	ranges = tool_pair_ranges(msgs)
	assert ranges == batches(msgs)
	# 一条 assistant 带 3 个调用 + 3 条结果 = 一个 4 条消息的区间
	assert all(end - start == 4 for start, end in ranges)


# ---------------------------------------------------------------------------
# ② 切点永不落在批次中间
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder", [codex_shape, xeyo_shape])
def test_keep_tail_cut_never_lands_inside_a_batch(builder):
	msgs = builder(rounds=4, per_batch=2)
	spans = batches(msgs)
	for end in range(8, len(msgs) + 1):
		prefix = msgs[:end]
		cut = keep_tail_cut(prefix)
		for start, stop in spans:
			assert not (start < cut < stop), (
				f"保尾切点 {cut} 落在批次 ({start},{stop}) 内部（prefix={end}）"
			)


@pytest.mark.parametrize("builder", [codex_shape, xeyo_shape])
def test_pair_safe_cut_snaps_to_batch_start(builder):
	msgs = builder(rounds=3, per_batch=2)
	for start, stop in batches(msgs):
		for cut in range(start + 1, stop):
			assert pair_safe_cut(msgs, cut) == start, (
				f"cut={cut} 没有回落到批首 {start}（批次 {start},{stop}）"
			)


def test_reported_oracle_case_is_fixed():
	"""还原 codex_holdout 的失败形态：批次 (1,5)、旧代码的 cut=2。"""
	msgs = [_user(), _use("call_00"), _use("call_01"), _result("call_00"),
		_result("call_01"), _text("继续")]
	assert tool_pair_ranges(msgs) == [(1, 5)]
	assert pair_safe_cut(msgs, 2) == 1, "cut=2 必须回落到批首 1（否则尾部首个结果成孤儿）"
	assert orphan_in_tail(msgs, 2) == ["call_00"], "旧切点确实制造 orphan（复现）"
	assert orphan_in_tail(msgs, pair_safe_cut(msgs, 2)) == [], "修好之后不该有 orphan"


# ---------------------------------------------------------------------------
# ③ 切完的尾部没有孤儿结果
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder", [codex_shape, xeyo_shape])
def test_no_orphan_result_after_cut(builder):
	msgs = builder(rounds=4, per_batch=3)
	spans = batches(msgs)
	for end in range(8, len(msgs) + 1):
		prefix = msgs[:end]
		cut = pair_safe_cut(prefix, keep_tail_cut(prefix))
		assert orphan_in_tail(prefix, cut) == [], (
			f"prefix={end} cut={cut} 之后仍有孤儿结果 {orphan_in_tail(prefix, cut)}"
		)
	assert spans, "用例必须真的含批次"


# ---------------------------------------------------------------------------
# ④ 报告口径：批次数与"工具轮"数一致
# ---------------------------------------------------------------------------


def test_tail_protection_counts_batches_not_messages():
	"""K 轮的语义是 K **批**：Codex 形态下批 = 多条消息，不能按条数保护。"""
	msgs = codex_shape(rounds=4, per_batch=2)
	cut = keep_tail_cut(msgs, tool_rounds=2)
	starts = [start for start, _ in batches(msgs)]
	assert cut == starts[-2], f"应回落到倒数第 2 批的批首 {starts[-2]}，实际 {cut}"
