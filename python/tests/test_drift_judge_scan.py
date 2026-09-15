"""`drift_judge.scan_session` 取数口的形状契约（回归锁）。

背景（2026-09-14 [reasoning] 修复的连带回归）
------------------------------------------------
`msgtypes/message.py::assistant_text_message` 在本次改动后：

    content = blocks if (tool_uses or reasoning) else text

即**纯文本轮只要带 reasoning（DeepSeek thinking 模式下几乎每轮都带）也走
block 数组**。而 `scan_session` 原先的 assistant 判据是

    role == "assistant" and isinstance(content, str) and text.strip()

`text` 本身已能从 block 数组正确抽文本，但 `isinstance(content, str)` 把全部
块形 assistant 行挡掉 ⇒ 漂移判定（六维评测之一，`block_ablation` 也复用其
`regex_judge`）的真实样本近乎归零。

本文件锁死两件事：
1. 工具轮跳过、**文本轮（无论 str 还是块）必须进样本**；
2. 生产端（`message_to_dict(assistant_text_message(...))`）产出的行，消费端
   （`scan_session`）必须认得——两个模块的形状理解绑定在同一条断言上。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.drift_judge import scan_session
from msgtypes.message import ToolUse, assistant_text_message, user_message
from session.record_transcript import message_to_dict

_L404_REPLY = "你贴的这段正是当前挂在我这轮投影尾部的 T_now 注入块，不是你下达的新任务。"


def _write_session(tmp_path: Path, rows: list[dict]) -> Path:
	p = tmp_path / "sess_test.jsonl"
	p.write_text(
		"\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
		encoding="utf-8",
	)
	return p


def _rows(*messages) -> list[dict]:
	"""走生产序列化路径（不是手搓 dict）。"""
	return [message_to_dict(m) for m in messages]


def test_text_only_block_turn_with_reasoning_is_scanned(tmp_path: Path) -> None:
	"""★ 回归本体：带 reasoning 的纯文本轮 → 必须进漂移样本。"""
	rows = _rows(
		user_message("继续"),
		assistant_text_message(_L404_REPLY, None, reasoning="想一下这是注入还是新任务"),
	)
	# 生产形状确认：块数组 + reasoning 块，无 tool_use
	row = rows[1]
	assert isinstance(row["content"], list), "纯文本轮带 reasoning 应为块数组"
	assert any(b.get("type") == "reasoning" for b in row["content"])
	assert not any(b.get("type") == "tool_use" for b in row["content"])

	verdicts = scan_session(_write_session(tmp_path, rows))
	assert len(verdicts) == 1, "该文本轮必须产出 1 个 (user, reply) 对"
	assert verdicts[0].l404 is True, "回复文本必须真的进入正则层（否则等于没扫）"
	assert verdicts[0].user_text == "继续"


def test_plain_str_turn_still_scanned(tmp_path: Path) -> None:
	"""老形状零回归：无 reasoning 的纯文本轮仍是 str，照旧进样本。"""
	rows = _rows(
		user_message("继续"),
		assistant_text_message(_L404_REPLY, None),
	)
	assert isinstance(rows[1]["content"], str), "无 reasoning 的纯文本轮应回落到 str"
	verdicts = scan_session(_write_session(tmp_path, rows))
	assert len(verdicts) == 1
	assert verdicts[0].l404 is True


def test_tool_turn_is_skipped(tmp_path: Path) -> None:
	"""工具轮跳过（原语义保留）：漂移判定只看文本回复。"""
	rows = _rows(
		user_message("继续"),
		assistant_text_message(
			_L404_REPLY,
			[ToolUse(id="c1", name="Read", input={"file_path": "a.py"})],
			reasoning="决定先读文件",
		),
	)
	verdicts = scan_session(_write_session(tmp_path, rows))
	assert verdicts == [], "带 tool_use 的轮不得进样本"


def test_reasoning_only_turn_is_skipped(tmp_path: Path) -> None:
	"""只有思考、没有可见文本的轮：text 为空 → 不进样本（无回复可判）。"""
	rows = _rows(
		user_message("继续"),
		assistant_text_message("", None, reasoning="只想了，没说"),
	)
	verdicts = scan_session(_write_session(tmp_path, rows))
	assert verdicts == []


def test_tool_turn_with_text_but_no_visible_output_still_skipped(tmp_path: Path) -> None:
	"""工具轮即便 thinking 很长也不进样本（判据是 tool_use，不是文本长度）。"""
	rows = _rows(
		user_message("继续"),
		assistant_text_message(
			"",
			[ToolUse(id="c2", name="Bash", input={"command": "ls"})],
			reasoning="x" * 500,
		),
	)
	verdicts = scan_session(_write_session(tmp_path, rows))
	assert verdicts == []


def test_pairs_are_ordered_and_use_latest_user(tmp_path: Path) -> None:
	"""多轮：每轮文本回复配最近一条 user 消息，顺序不变。"""
	rows = _rows(
		user_message("第一问"),
		assistant_text_message("第一答", None, reasoning="r1"),
		user_message("第二问"),
		assistant_text_message(_L404_REPLY, None, reasoning="r2"),
	)
	verdicts = scan_session(_write_session(tmp_path, rows))
	assert [v.user_text for v in verdicts] == ["第一问", "第二问"]
	assert verdicts[0].l404 is False
	assert verdicts[1].l404 is True


def test_unknown_and_malformed_rows_are_ignored(tmp_path: Path) -> None:
	"""坏行 / 未知 role / 无 content 不得打断扫描，也不得造对。"""
	rows = [
		{"role": "user", "content": "问"},
		{"role": "ui_thought", "content": "思考（UI-only，非回复）"},
		{"role": "unknown", "content": "x"},
		{"role": "assistant"},
		{"role": "assistant", "content": {"not": "a list"}},
		{"role": "assistant", "content": _L404_REPLY},
	]
	p = tmp_path / "sess_bad.jsonl"
	p.write_text(
		"\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n{bad json}\n",
		encoding="utf-8",
	)
	verdicts = scan_session(p)
	assert len(verdicts) == 1
	assert verdicts[0].user_text == "问"
	assert verdicts[0].l404 is True
