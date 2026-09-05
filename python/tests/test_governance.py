"""L4 governance 纯函数。"""

from __future__ import annotations

import pytest

from memory.governance import (
    MemoryCandidate,
    MemorySchemaError,
    can_promote,
    forget,
    may_resurrect,
    parse_and_validate,
    resolve_conflict,
)


def _note(**kwargs):
	base = {
		"id": "mem_a",
		"type": "feedback",
		"source": {"kind": "user", "session_id": "s", "message_id": "m"},
		"confidence": 1.0,
		"status": "active",
		"scope": "workspace",
		"applies_to": [],
		"created_at": "2026-08-17",
		"updated_at": "2026-08-17",
		"last_confirmed_at": "2026-08-17",
	}
	base.update(kwargs)
	return parse_and_validate(base, kwargs.get("content", "测试必须打真库"))


def test_missing_source_rejected():
	with pytest.raises(MemorySchemaError):
		parse_and_validate(
			{"type": "feedback", "confidence": 1.0, "status": "active"},
			"x",
		)


def test_missing_confidence_rejected():
	with pytest.raises(MemorySchemaError):
		parse_and_validate(
			{
				"type": "feedback",
				"source": {"kind": "user"},
				"status": "active",
			},
			"x",
		)


def test_untyped_not_indexable():
	note = parse_and_validate(
		{
			"type": "diary",
			"source": {"kind": "user"},
			"confidence": 1.0,
			"status": "active",
			"scope": "workspace",
		},
		"hello",
	)
	assert note.type == "untyped"
	assert note.indexable is False


def test_conflict_different_applies_to_coexist():
	a = _note(applies_to=[{"path": "tests/**"}])
	b = _note(id="mem_b", applies_to=[{"path": "src/**"}], content="other")
	assert resolve_conflict(a, b) == "coexist"


def test_inference_cannot_override_user():
	old = _note()
	new = _note(
		id="mem_b",
		source={"kind": "inference", "session_id": "", "message_id": ""},
		confidence=0.4,
		content="maybe mock is ok",
	)
	assert resolve_conflict(old, new) == "keep_old"


def test_same_topic_supersede():
	# 同 type+title 视为同一主题的更新 → 替换
	old = _note(confidence=0.6, source={"kind": "agent"}, title="测试必须打真库")
	new = _note(id="mem_b", content="updated", title="测试必须打真库")
	assert resolve_conflict(old, new) == "supersede"


def test_different_type_same_scope_coexist():
	# 不同主题（type 或 title 不同）共存，不再互相吞掉
	a = _note(title="真实DB", content="测试必须打真库")
	b = _note(id="mem_b", type="user", title="语言偏好", content="评测偏好用中文")
	assert resolve_conflict(a, b) == "coexist"


def test_different_title_same_type_coexist():
	a = _note(title="真实DB", content="测试必须打真库")
	b = _note(id="mem_b", title="另一个主题", content="其它事实")
	assert resolve_conflict(a, b) == "coexist"


def test_explicit_supersedes_across_topics():
	# 显式 supersedes 旧 id 时跨主题也替换
	a = _note(title="真实DB", content="测试必须打真库")
	b = _note(id="mem_b", type="user", title="语言偏好", supersedes="mem_a", content="x")
	assert resolve_conflict(a, b) == "supersede"


def test_forget_never_resurrect():
	stone = forget("mem_a")
	assert stone.id == "mem_a"
	assert may_resurrect("mem_a", [stone]) is False


def test_can_promote_rejects_repeat_only():
	cand = MemoryCandidate(
		content="x",
		source={"kind": "agent"},
		evidence=["repeat", "repeat:2"],
	)
	assert can_promote(cand) is False
	ok = MemoryCandidate(
		content="x",
		source={"kind": "user"},
		evidence=[],
	)
	assert can_promote(ok) is True


def test_can_promote_agent_harvest_capped():
	from memory.governance import promotion_confidence

	cand = MemoryCandidate(
		content="prefer pytest for this repo",
		source={"kind": "agent"},
		evidence=["subagent_marker"],
	)
	assert can_promote(cand) is True
	assert promotion_confidence(cand) == 0.6
	main = MemoryCandidate(
		content="请记住我们用 pnpm",
		source={"kind": "agent", "agent_id": "main"},
		evidence=["main_harvest"],
	)
	assert can_promote(main) is True
	assert promotion_confidence(main) == 0.6


def test_can_promote_diff_verified_channel():
	"""P3：verified_by_diff 是合法证据通道（仅 NightShift 对照真实改动打标后生效），
	置信度 0.85；未打标（仅 repeat）保持拒绝 —— 门禁不放宽。"""
	from memory.governance import promotion_confidence

	diff_cand = MemoryCandidate(
		content="src/run.py 改用 v2 逻辑",
		source={"kind": "agent"},
		evidence=["verified_by_diff"],
	)
	assert can_promote(diff_cand) is True
	assert promotion_confidence(diff_cand) == 0.85
	# 未打标：仅 repeat 仍不得晋升（红线①：不改既有门禁）
	repeat_only = MemoryCandidate(
		content="src/run.py 改用 v2 逻辑",
		source={"kind": "agent"},
		evidence=["repeat", "repeat:2"],
	)
	assert can_promote(repeat_only) is False
