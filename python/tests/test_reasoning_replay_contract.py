"""思考态回放契约测试。

背景（《最终方案-思考态回放》+ S0 取证 + dsh 考据）：
  DeepSeek thinking 模式下，本会话历史里带 `tools` 的请求，assistant 消息的
  `reasoning_content` 需按原文回传；XEYO 侧原先把厂商思考态整段丢弃（只落
  transcript 的 narration，content 数组里无 reasoning 位置），导致多轮工具
  任务里思考态断链。

  三处改动（S1/S2/S3）：
    S1  msgtypes/message.py::assistant_text_message  — reasoning 作为
        content 数组的**首个 block** 留档（{type:"reasoning", text:...}）。
    S2  engine/query_loop.py                          — 当轮流式 reasoning_delta
        拼接入当轮 assistant 消息（与 narration 同点位）。
    S3  model/_openai_common.py::normalize_messages_for_openai
        — assistant 分支把 reasoning block 还原为 `reasoning_content` 字段。

本测试锁定四条结构性约束（不发起网络请求，纯离线）：
  1) 逐字节往返等价：reasoning 原文经 Message → OpenAI 报文后**一字不差**，
     且不做 strip / 截断 / 归一化（思考态是厂商 KV 前缀的一部分）。
  2) 顺序保持：reasoning 必须排在 text / tool_use 之前，且 text 与 tool_use
     的相对顺序不变（打乱即破坏厂商拼接前缀）。
  3) 纯 tool_call 轮 content 恒为 `''`：绝不出现 `null`——`content:null` 且无
     tool_calls 的消息会被 live API 400 拒收，且消息已落盘会砖掉整个会话
     （dsh 注释明确的原话风险，XEYO 必须结构性免疫）。
  4) 老会话零回归：无 reasoning 的历史消息产出与原实现逐字节相同（不发
     `reasoning_content` 字段，不新增空字段）。

以及 hydrate 往返：reasoning block 经 transcript JSONL 序列化/还原后不丢。
"""

from __future__ import annotations

import json
from pathlib import Path

from model._openai_common import normalize_messages_for_openai
from msgtypes.message import Message, ToolUse, assistant_text_message
from session.hydrate import message_from_row
from session.transcript_blobs import resolve_transcript_rows, row_from_message

# ------------------------------------------------------------------ 工具


def _assistant_row(
	reasoning: str = "",
	text: str = "",
	tool_uses: list[ToolUse] | None = None,
) -> dict:
	"""构造一条内部格式的 assistant 行（as_api_messages 的形状）。"""
	msg = assistant_text_message(text, tool_uses, reasoning=reasoning)
	assert isinstance(msg.content, list), "带 tool_uses 时应为 block 数组"
	return {"role": "assistant", "content": msg.content}


def _norm(messages: list[dict]) -> list[dict]:
	return normalize_messages_for_openai(messages)


def _only_assistant(messages: list[dict]) -> dict:
	out = _norm(messages)
	rows = [m for m in out if m.get("role") == "assistant"]
	assert len(rows) == 1, f"expected exactly 1 assistant row, got {rows}"
	return rows[0]


# ---------------------------------------------- 1) 逐字节往返等价


def test_reasoning_roundtrip_is_byte_exact() -> None:
	"""思考态原文必须一字不差地贴回，不做 strip/截断/归一化。

	用「首尾空白 + 换行 + 中文 + 反引号 + 引号 + emoji」的组合文本，
	任何清洗都会立刻暴露。
	"""
	raw = (
		"\n  我需要先看 README。\n"
		'看到 `path/to/file.py`，它是 "core" 模块。\n'
		"结论：先读文件再改。🙂\n\n"
	)
	row = _assistant_row(raw, "读一下", [ToolUse(id="c1", name="Read", input={"p": "a"})])
	assert _only_assistant([row])["reasoning_content"] == raw


def test_reasoning_not_stripped_even_if_whitespace_only_edges() -> None:
	"""首尾为空白但中间有内容 → 原样保留（不做 strip）。"""
	raw = "   \n\t真实思考内容\t\n   "
	row = _assistant_row(raw, "x", [ToolUse(id="c1", name="Bash", input={})])
	assert _only_assistant([row])["reasoning_content"] == raw


def test_empty_reasoning_omits_field() -> None:
	"""无思考 → 不发字段（不是发空串）。空串字段会污染请求且无收益。"""
	for reasoning in ("", None):  # type: ignore[list-item]
		row = _assistant_row(reasoning or "", "写完了", [ToolUse(id="c1", name="Write", input={})])
		assert "reasoning_content" not in _only_assistant([row])


# -------------------------------------------------- 2) 顺序保持


def test_reasoning_block_precedes_text_and_tool_use() -> None:
	"""block 数组顺序 = [reasoning, text, tool_use...]。"""
	msg = assistant_text_message(
		"我来执行",
		[ToolUse(id="c1", name="Bash", input={"cmd": "ls"})],
		reasoning="先想一下",
	)
	assert isinstance(msg.content, list)
	assert [b["type"] for b in msg.content] == ["reasoning", "text", "tool_use"]


def test_missing_text_still_keeps_reasoning_first() -> None:
	"""纯 tool_call 轮（无正文）→ [reasoning, tool_use]，reasoning 仍在最前。"""
	msg = assistant_text_message(
		"", [ToolUse(id="c1", name="Read", input={})], reasoning="先读文件"
	)
	assert isinstance(msg.content, list)
	assert [b["type"] for b in msg.content] == ["reasoning", "tool_use"]


def test_text_and_tool_use_relative_order_preserved() -> None:
	"""多工具时 tool_use 顺序不被 reasoning 插入打乱。"""
	uses = [ToolUse(id=f"c{i}", name="Read", input={"i": i}) for i in range(3)]
	row = _assistant_row("想", "做", uses)
	call_ids = [tc["id"] for tc in _only_assistant([row])["tool_calls"]]
	assert call_ids == ["c0", "c1", "c2"]


# --------------------------- 3) 纯 tool_call 轮 content 恒为 ''（无 null）


def test_pure_tool_call_content_is_empty_string_not_null() -> None:
	"""★ 安全红线：content 恒为空串。

	`content: null` + 无 tool_calls 会被 live API 400 拒收，而消息一旦落盘
	就砖掉后续所有轮（dsh 注释的原话风险）。XEYO 用 `"".join(text_parts)`
	恒定产出 `''`，此处把该不变式钉死。
	"""
	row = _assistant_row("纯工具轮思考", "", [ToolUse(id="c1", name="Bash", input={})])
	out = _only_assistant([row])
	assert out["content"] == ""
	assert out["content"] is not None


def test_tool_call_only_row_content_never_none_across_shapes() -> None:
	"""多种畸形/边界 block 组合下 content 都不得为 None，且不得丢 tool_calls。"""
	cases: list[list[dict]] = [
		[{"type": "reasoning", "text": "r"}, {"type": "tool_use", "id": "a", "name": "T", "input": {}}],
		[{"type": "tool_use", "id": "a", "name": "T", "input": {}}],
		[{"type": "reasoning", "text": "r"}],
		[{"type": "reasoning", "text": "r"}, {"type": "text", "text": ""}],
	]
	for blocks in cases:
		out = _only_assistant([{"role": "assistant", "content": blocks}])
		assert out.get("content") is not None, blocks
		assert isinstance(out["content"], str), blocks


def test_handles_malformed_and_missing_blocks_gracefully() -> None:
	"""非 dict block / 缺 text / 缺 input 不得抛异常，且不产生脏字段。"""
	blocks: list[object] = [
		"not-a-dict",
		{"type": "reasoning"},  # 缺 text
		{"type": "text"},
		{"type": "tool_use", "id": "c1", "name": "T"},  # 缺 input
		{"type": "unknown_future_block", "payload": 1},
	]
	out = _only_assistant([{"role": "assistant", "content": blocks}])
	assert out["content"] == ""
	assert "reasoning_content" not in out  # 缺 text → 空串 → 不发字段
	assert out["tool_calls"][0]["function"]["arguments"] == "{}"


# ------------------------------------------------ 4) 老会话零回归


def test_legacy_assistant_without_reasoning_unchanged() -> None:
	"""无 reasoning 的老会话：产出与加 reasoning 之前逐字节相同。"""
	legacy_blocks = [
		{"type": "text", "text": "我来执行"},
		{"type": "tool_use", "id": "c1", "name": "Bash", "input": {"cmd": "ls"}},
	]
	out = _only_assistant([{"role": "assistant", "content": legacy_blocks}])
	assert out == {
		"role": "assistant",
		"content": "我来执行",
		"tool_calls": [
			{
				"id": "c1",
				"type": "function",
				"function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"}, ensure_ascii=False)},
			}
		],
	}


def test_plain_string_assistant_unchanged() -> None:
	"""role=assistant 且 content 为字符串（无工具轮）→ 走原路径，不加字段。"""
	out = _only_assistant([{"role": "assistant", "content": "好的"}])
	assert out == {"role": "assistant", "content": "好的"}


def test_user_and_tool_rows_unaffected() -> None:
	"""reasoning 改动不得触碰 user / tool / system 分支。

	注：tool 分支原本就不透传 `name`（既有行为，本次未改动），此处锁定
	改动后的实际产出，任何意外漂移都会红。
	"""
	msgs = [
		{"role": "system", "content": "sys"},
		{"role": "user", "content": "你好"},
		{"role": "tool", "tool_call_id": "c1", "name": "Bash", "content": "out"},
	]
	assert _norm(msgs) == [
		{"role": "system", "content": "sys"},
		{"role": "user", "content": "你好"},
		{"role": "tool", "tool_call_id": "c1", "content": "out"},
	]


def test_multiple_reasoning_blocks_concatenated_in_order() -> None:
	"""若历史里意外出现多个 reasoning block，按出现顺序拼接（确定性）。"""
	blocks = [
		{"type": "reasoning", "text": "第一段"},
		{"type": "reasoning", "text": "第二段"},
		{"type": "text", "text": "hi"},
	]
	assert _only_assistant([{"role": "assistant", "content": blocks}])["reasoning_content"] == (
		"第一段第二段"
	)


# ------------------------------------ 5) transcript 往返（落盘不丢）


def test_reasoning_survives_transcript_roundtrip(tmp_path: Path) -> None:
	"""reasoning block 经 JSONL 序列化/还原后逐字节等价。"""
	raw = "思考：\n\t先读 `a.py`。\n"
	uses = [ToolUse(id="c1", name="Read", input={"file_path": "a.py"})]

	msg = assistant_text_message("读一下", uses, narration="旁白", reasoning=raw)
	assert isinstance(msg.content, list)

	row = row_from_message(msg, anchor=tmp_path / "s.jsonl")
	assert row["content"] == msg.content  # 小 payload 走 inline

	restored = message_from_row(row)
	assert restored is not None
	assert restored.content == msg.content
	# 逐字节：从还原的 content 里取出 reasoning 原文再跑一次 normalize
	back = _only_assistant([{"role": "assistant", "content": restored.content}])
	assert back["reasoning_content"] == raw


def test_reasoning_survives_blob_externalization(tmp_path: Path) -> None:
	"""大 payload 走 blob 外置路径时 reasoning 同样不丢（阈值 512 下调）。"""
	import os

	old = os.environ.get("XEYO_TRANSCRIPT_BLOB_THRESHOLD")
	os.environ["XEYO_TRANSCRIPT_BLOB_THRESHOLD"] = "512"
	try:
		raw = "很长的思考。" * 200  # > 512 bytes
		msg = assistant_text_message(
			"x", [ToolUse(id="c1", name="Read", input={})], reasoning=raw
		)
		self_anchor = tmp_path / "s.jsonl"
		row = row_from_message(msg, anchor=self_anchor)
		assert "content_ref" in row, "应触发 blob 外置"

		resolved = resolve_transcript_rows([row], self_anchor)
		restored = message_from_row(resolved[0])
		assert restored is not None
		got = _only_assistant([{"role": "assistant", "content": restored.content}])
		assert got["reasoning_content"] == raw
	finally:
		if old is None:
			os.environ.pop("XEYO_TRANSCRIPT_BLOB_THRESHOLD", None)
		else:
			os.environ["XEYO_TRANSCRIPT_BLOB_THRESHOLD"] = old


def test_text_only_turn_carries_reasoning_block() -> None:
	"""纯文本轮（无工具）带 reasoning → 也落 block 数组（dsh 口径）。

	2026-09-14 按 dsh 改判（serialize.ts:228-233）：官方在非工具轮**忽略**
	reasoning_content（无害），且非工具轮 reasoning 是跨厂商转码恢复签名的
	唯一载体——"协议上无处承载"的旧决策作废。空 reasoning 纯文本轮仍回
	落纯字符串（不发空数组）。
	"""
	msg = assistant_text_message("就一句话", None, reasoning="这段思考现在有处承载")
	assert isinstance(msg.content, list)
	assert msg.content == [
		{"type": "reasoning", "text": "这段思考现在有处承载"},
		{"type": "text", "text": "就一句话"},
	]
	# 空 reasoning + 纯文本 → 旧行为不变（纯字符串，零回归）
	plain = assistant_text_message("就一句话", None, reasoning="")
	assert isinstance(plain.content, str)
	assert plain.content == "就一句话"


def test_text_only_reasoning_replayed_to_wire() -> None:
	"""dsh R2（非工具轮）：text-only 轮的 reasoning 必须回传到 wire。"""
	row = _assistant_row("纯文本轮思考", "答案", None)
	assert isinstance(row["content"], list), "方案1 后 text-only+reasoning 应为 block 数组"
	out = _only_assistant([row])
	assert out["reasoning_content"] == "纯文本轮思考"
	assert out["content"] == "答案"
	assert "tool_calls" not in out


def test_reasoning_only_turn_content_empty_string_with_reasoning() -> None:
	"""★ dsh 红线（serialize.ts:219-227）：reasoning-only 轮 wire 上
	content 必须是 `""` 而非 null——null+无 tool_calls 会被 live API 400
	且砖掉整个会话。
	"""
	out = _only_assistant(
		[{"role": "assistant", "content": [{"type": "reasoning", "text": "只在思考通道作答"}]}]
	)
	assert out["content"] == ""
	assert out["content"] is not None
	assert out["reasoning_content"] == "只在思考通道作答"
	assert "tool_calls" not in out


def test_empty_tool_result_gets_no_output_sentinel() -> None:
	"""dsh R3（serialize.ts:269-271）：空 tool 输出在 wire 上也要有内容，
	统一补结构性哨兵 `(no output)`（部分网关拒收空串 tool 消息）。
	"""
	msgs = [
		{"role": "tool", "tool_call_id": "c1", "content": ""},
		{"role": "tool", "tool_call_id": "c2", "content": [
			{"type": "tool_result", "tool_use_id": "c2", "content": ""}
		]},
		{"role": "tool", "tool_call_id": "c3", "content": "正常输出"},
	]
	out = _norm(msgs)
	by_id = {m["tool_call_id"]: m["content"] for m in out}
	assert by_id["c1"] == "(no output)"
	assert by_id["c2"] == "(no output)"
	assert by_id["c3"] == "正常输出"


def test_message_defaults_unchanged_without_reasoning() -> None:
	"""assistant_text_message 加参数后，原有调用点的产出不变。"""
	uses = [ToolUse(id="c1", name="Bash", input={"cmd": "ls"})]
	msg = assistant_text_message("t", uses)
	assert isinstance(msg.content, list)
	assert msg.content == [
		{"type": "text", "text": "t"},
		{"type": "tool_use", "id": "c1", "name": "Bash", "input": {"cmd": "ls"}},
	]
	assert msg.narration == ""
	assert msg.interrupted is False
	assert msg.role == "assistant"


def test_message_reasoning_kept_without_text() -> None:
	"""reasoning-only（无正文无工具）在 Message 层不炸：仍产出单 block。"""
	# 该形状在引擎里不会出现（assistant_text_message 无 tool_uses 时走字符串
	# 路径），此处只锁 ToolUse 分支的 block 组装不因 text 为空而错位。
	msg = assistant_text_message("", [ToolUse(id="c1", name="Read", input={})], reasoning="r")
	assert isinstance(msg.content, list)
	assert msg.content[0] == {"type": "reasoning", "text": "r"}


def test_tool_result_and_image_blocks_unaffected_by_reasoning_support() -> None:
	"""回归：user 带 tool_result/图片 的路径不受 assistant 分支改动影响。"""
	msgs = [
		{
			"role": "user",
			"content": [
				{"type": "tool_result", "tool_use_id": "c1", "content": "out"},
				{"type": "text", "text": "继续"},
			],
		}
	]
	out = _norm(msgs)
	assert {"role": "tool", "tool_call_id": "c1", "content": "out"} in out
	assert {"role": "user", "content": "继续"} in out
