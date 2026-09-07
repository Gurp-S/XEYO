"""#8 首轮嗅探 单元测试（纯函数层：装配门 + 有界清单构造）。

判定：仅首轮（无 assistant 历史）注入；side/子代理/开关关 → 空；清单有界、确定。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.first_sniff import (
	_MAX_TEXT_CHARS,
	build_first_sniff_text,
	is_first_engine_turn,
	maybe_first_sniff_text,
)


def test_first_turn_detection():
	assert is_first_engine_turn([{"role": "user", "content": "hi"}])
	assert not is_first_engine_turn(
		[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
	)
	assert is_first_engine_turn([]) is True
	assert is_first_engine_turn(None) is True  # None → 空迭代 → True


def test_build_snapshot_lists_dir_and_cwd(tmp_path):
	(tmp_path / "main.py").write_text("x")
	(tmp_path / "docs").mkdir()
	text = build_first_sniff_text(str(tmp_path))
	assert str(tmp_path.resolve()) in text
	assert "[f] main.py" in text
	assert "[d] docs/" in text


def test_snapshot_bounded_and_deterministic(tmp_path):
	for i in range(200):
		(tmp_path / f"file_{i:03d}.txt").write_text("x")
	text_a = build_first_sniff_text(str(tmp_path))
	assert len(text_a) <= _MAX_TEXT_CHARS + 400
	# 确定性：两次构造逐字节一致
	assert text_a == build_first_sniff_text(str(tmp_path))
	assert "仅列" in text_a  # 有截断说明


def test_snapshot_invalid_cwd_returns_empty():
	assert build_first_sniff_text("") == ""
	assert build_first_sniff_text(str(Path("Z:/definitely-not-exist-xyz"))) == ""


def test_maybe_gating(tmp_path):
	proj_first = [{"role": "user", "content": "do it"}]
	proj_later = [
		{"role": "user", "content": "do it"},
		{"role": "assistant", "content": "ok"},
	]
	cwd = str(tmp_path)
	assert maybe_first_sniff_text(proj_first, cwd) != ""
	assert maybe_first_sniff_text(proj_later, cwd) == ""   # 非首轮
	assert maybe_first_sniff_text(proj_first, cwd, side=True) == ""   # side
	assert maybe_first_sniff_text(proj_first, cwd, subagent=True) == ""  # 子代理
	assert maybe_first_sniff_text(proj_first, "") == ""   # 无 cwd
