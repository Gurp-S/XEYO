"""批次边界回归（2026-09-20 事故）：并行批次不得被投影边界切开。

## 事故形态（真实产物可复现）

Codex / OpenAI 形态的转写把并行调用写成**连续多条 assistant 消息**（一条消息一个
``tool_use``），结果消息跟在整批之后：

```
27 assistant tool_use call_00_...
28 assistant tool_use call_01_...
29 tool      tool_result call_00_...
30 tool      tool_result call_01_...
```

旧的配对规则按「一条 assistant + 紧随其后的结果」分组，于是得到 ``(27, 28)`` 这种
**不含任何结果**的退化区间和 ``(28, 31)`` —— 边界 ``cut = 28`` 看着落在区间端点上，
实际切进了批次：``call_00`` 的声明进区域、它的结果（29）留在尾部 ⇒ 候选序列出现
``orphan_tool_result`` ⇒ 调用方整体回退。

真实产物证据（`D:\\lea\\XEYO-wsc-task-ab-v1\\_wsc_out\\codex_holdout_v1\\`）：
6 任务 / 838 回合 / 25 次回退，其中 **9 次** ``broken_tool_pair``，逐条复现命中 9/9，
全部落在 ``workspace_ui_controls``（6）与 ``workspace_window_layout``（3）的批次中间。

本文件锁死修好后的四条契约：
1. 批次区间把整批（含跨多条 assistant 的声明）算作一个区间；
2. ``keep_tail_cut`` / ``pair_safe_cut`` 永不落在批次内部；
3. 候选尾部不含「结果先于其调用」的 orphan；
4. XEYO 形态（一条 assistant 带全部调用）区间逐字节不变。
"""

from __future__ import annotations

from engine.compact import keep_tail_cut, tool_pair_ranges
from memory.runtime import pair_safe_cut
from synaptic.textutil import tool_result_blocks, tool_use_blocks


def _use(uid: str) -> dict:
	return {"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": "Bash", "input": {}}]}


def _uses(*uids: str) -> dict:
	return {"role": "assistant", "content": [
		{"type": "tool_use", "id": u, "name": "Bash", "input": {}} for u in uids
	]}


def _res(uid: str) -> dict:
	return {"role": "tool", "content": [
		{"type": "tool_result", "tool_use_id": uid, "content": f"out {uid}"}
	]}


def _batch_split(messages: list[dict], cut: int) -> list[tuple[int, int]]:
	"""cut 落在哪些批次内部（真批次：连续声明 + 随后结果）。"""
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
	return [s for s in spans if s[0] < cut < s[1]]


def _orphan_after(messages: list[dict], cut: int) -> dict:
	"""尾部（cut 起）里「结果先于其调用」的 ids。"""
	pending: set[str] = set()
	for index in range(cut, len(messages)):
		uses = {str(b.get("id")) for b in tool_use_blocks(messages[index]) if b.get("id")}
		results = {str(b.get("tool_use_id")) for b in tool_result_blocks(messages[index]) if b.get("tool_use_id")}
		if results - pending:
			return {"index": index, "unexpected": sorted(results - pending), "pending": sorted(pending)}
		pending.difference_update(results)
		pending.update(uses)
	return {}


def _codex_shape(rounds: int = 5) -> list[dict]:
	"""Codex/OpenAI 形态：并行调用 = 连续两条 assistant（各一个调用）+ 整批结果。"""
	msgs: list[dict] = [{"role": "user", "content": "修 bug"}]
	for r in range(rounds):
		a, b = f"call_{r}a", f"call_{r}b"
		msgs += [_use(a), _use(b), _res(a), _res(b), {"role": "assistant", "content": [{"type": "text", "text": f"第 {r} 轮"}]}]
	return msgs


def _xeyo_shape(rounds: int = 5) -> list[dict]:
	"""XEYO 形态：一条 assistant 带全部调用。"""
	msgs: list[dict] = [{"role": "user", "content": "修 bug"}]
	for r in range(rounds):
		a, b = f"call_{r}a", f"call_{r}b"
		msgs += [_uses(a, b), _res(a), _res(b), {"role": "assistant", "content": [{"type": "text", "text": f"第 {r} 轮"}]}]
	return msgs


# ---------------------------------------------------------------------------
# ① 批次区间
# ---------------------------------------------------------------------------


def test_consecutive_assistant_calls_form_one_range():
	msgs = _codex_shape(rounds=2)
	ranges = tool_pair_ranges(msgs)
	# (1,5) 是第一轮整批（两条声明 + 两条结果）。第二轮的真实起点是 **6**：
	# 索引 5 是上一轮的 assistant 正文，既不是 tool_use 也不该被算进批次。
	# 参照实现 = 本文件 `_batch_split`（它给同一批的第二批算的正是 (6,10)）。
	assert ranges[0] == (1, 5), ranges
	assert ranges[1] == (6, 10), ranges


def test_xeyo_shape_ranges_are_per_batch_not_per_call():
	msgs = _xeyo_shape(rounds=2)
	# 同理：索引 4 是第一轮的正文消息。写成 (4,7) 会与**同文件通过着的**
	# `test_xeyo_shape_rows_pass_through_unchanged`（要求 `tool_pair_ranges ==
	# legacy_ranges`，后者对 XEYO 形态给出 (1,4),(5,8)）互斥。
	assert tool_pair_ranges(msgs) == [(1, 4), (5, 8)]


def test_degenerate_range_without_results_is_gone():
	"""旧规则会产出 (1,2) 这种零结果区间——它是切进批次的入口。"""
	msgs = _codex_shape(rounds=3)
	for start, end in tool_pair_ranges(msgs):
		assert any(tool_result_blocks(m) for m in msgs[start:end]), f"区间 {start, end} 里没有结果"


# ---------------------------------------------------------------------------
# ② 边界永不落在批次内部
# ---------------------------------------------------------------------------


def test_keep_tail_cut_never_lands_inside_a_batch():
	for builder in (_codex_shape, _xeyo_shape):
		msgs = builder(rounds=5)
		cut = keep_tail_cut(msgs)
		assert not _batch_split(msgs, cut), (builder.__name__, cut)


def test_pair_safe_cut_pulls_mid_batch_cut_back_to_batch_start():
	msgs = _codex_shape(rounds=5)
	# 第 3 批的声明在索引 11(a)/12(b)，结果 13/14 —— 12 是"看着像边界"的危险切点
	assert pair_safe_cut(msgs, 12) == 11
	assert pair_safe_cut(msgs, 13) == 11
	# 批次之外的切点不动
	assert pair_safe_cut(msgs, 15) == 15


def test_keep_tail_cut_agrees_with_pair_safe_cut():
	msgs = _codex_shape(rounds=6)
	assert keep_tail_cut(msgs) == pair_safe_cut(msgs, keep_tail_cut(msgs))


# ---------------------------------------------------------------------------
# ③ 尾部无 orphan
# ---------------------------------------------------------------------------


def test_tail_has_no_orphan_tool_result():
	for builder in (_codex_shape, _xeyo_shape):
		msgs = builder(rounds=6)
		cut = keep_tail_cut(msgs)
		assert not _orphan_after(msgs, cut), (builder.__name__, cut, _orphan_after(msgs, cut))


def test_old_rule_mid_batch_cut_is_the_regression_we_fixed():
	"""把切点强行放回事故位置（批次内部）时，orphan 必须复现——证明锁的是真机制。"""
	msgs = _codex_shape(rounds=5)
	bad = _orphan_after(msgs, 12)
	assert bad, "事故切点没有复现 orphan，说明本测试没锁住目标机制"
	assert bad["unexpected"] == ["call_2a"]
	assert bad["pending"] == ["call_2b"]


# ---------------------------------------------------------------------------
# ④ XEYO 形态逐字节不变
# ---------------------------------------------------------------------------


def test_xeyo_shape_boundary_is_unchanged_from_legacy_rule():
	def legacy_ranges(messages: list[dict]) -> list[tuple[int, int]]:
		out: list[tuple[int, int]] = []
		i, n = 0, len(messages)
		while i < n:
			if not tool_use_blocks(messages[i]):
				i += 1
				continue
			j = i + 1
			while j < n and tool_result_blocks(messages[j]):
				j += 1
			out.append((i, j))
			i = j
		return out

	msgs = _xeyo_shape(rounds=4)
	assert tool_pair_ranges(msgs) == legacy_ranges(msgs)


def test_xeyo_shape_legacy_fallback_cut_unchanged():
	"""无工具轮时 `keep_tail_cut` 仍走按条数兜底（行为不动）。"""
	msgs = [{"role": "user", "content": "hi"}] * 10
	assert keep_tail_cut(msgs) == 4
