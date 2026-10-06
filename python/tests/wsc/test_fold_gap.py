"""折叠间隔判据：max(回本枪数, 命中率约束枪数) 的逐点行为。

数字全部取自真实 fold_events.jsonl（2026-09-28 记录），不是估计值。
"""

from __future__ import annotations

from synaptic.cadence import (
	FOLD_WATERMARK_RATIO,
	TARGET_HIT_RATE,
	fold_gap_required,
	theta_required,
	watermark_tokens,
)

#: 实测一次真实折叠：region=12649 transition=6234 saved_net=12189
REAL_TRANSITION = 6234
REAL_PAYBACK = 30.0 * REAL_TRANSITION / 12189  # = 15.34，与日志字段逐位一致


def test_watermark_is_half_window() -> None:
	assert FOLD_WATERMARK_RATIO == 0.5
	assert watermark_tokens(128_000) == 64_000
	assert watermark_tokens(0) == 0


def test_theta_unchanged_and_real_payback() -> None:
	# 判据②（token 口径）等价形式：payback = 30 × 重发面 / 净省
	assert theta_required() == 1.0
	assert abs(30 * REAL_TRANSITION / 12189 - REAL_PAYBACK) < 1e-6


def test_payback_dominates_when_prompt_is_at_watermark() -> None:
	# prompt=64k（128k 窗口的水位）：命中率项 6234/640=10 枪 < 回本 16 枪
	assert fold_gap_required(REAL_PAYBACK, REAL_TRANSITION, 64_000) == 16


def test_hit_rate_term_dominates_on_small_prompt() -> None:
	# prompt=19k（实测当枪量级）：命中率项 5175/190=28 枪 > 回本 23 枪
	assert fold_gap_required(22.2, 5175, 19_000) == 28


def test_gap_is_monotone_in_prompt() -> None:
	# (b) 稳态：prompt 越大，命中率允许的间隔越短；永远不低于回本枪数
	gaps = [fold_gap_required(16.0, 5175, p) for p in (19_000, 32_000, 64_000, 128_000)]
	assert gaps == sorted(gaps, reverse=True)
	assert all(g >= 16 for g in gaps)
	assert gaps[-1] == 16


def test_never_below_one_shot() -> None:
	assert fold_gap_required(0.0, 0, 10_000) == 1
