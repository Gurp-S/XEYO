"""确定性的离线比例统计，不依赖模型或第三方统计包。"""

from __future__ import annotations

import math
from typing import Sequence


def wilson_interval(successes: int, total: int, *, z: float = 1.959963984540054) -> dict[str, float | int | None]:
	"""返回比例与 Wilson 置信区间；无分母时明确返回 ``None``。"""
	if total < 0 or successes < 0 or successes > total:
		raise ValueError("successes/total must satisfy 0 <= successes <= total")
	if total == 0:
		return {"successes": successes, "total": total, "rate": None, "low": None, "high": None}
	p = successes / total
	den = 1.0 + z * z / total
	center = (p + z * z / (2.0 * total)) / den
	half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / den
	low = max(0.0, center - half)
	high = min(1.0, center + half)
	if successes == 0:
		low = 0.0
	if successes == total:
		high = 1.0
	return {
		"successes": successes,
		"total": total,
		"rate": p,
		"low": low,
		"high": high,
	}


def paired_delta(baseline: Sequence[bool], candidate: Sequence[bool]) -> dict[str, float | int | None]:
	"""按同一题目配对计算候选相对基线的成功率差。"""
	if len(baseline) != len(candidate):
		raise ValueError("paired samples must have equal length")
	n = len(baseline)
	if n == 0:
		return {"n": 0, "baseline_rate": None, "candidate_rate": None, "delta": None,
		        "candidate_wins": 0, "baseline_wins": 0}
	b = sum(bool(x) for x in baseline)
	c = sum(bool(x) for x in candidate)
	return {
		"n": n,
		"baseline_rate": b / n,
		"candidate_rate": c / n,
		"delta": (c - b) / n,
		"candidate_wins": sum((not x) and y for x, y in zip(baseline, candidate)),
		"baseline_wins": sum(x and (not y) for x, y in zip(baseline, candidate)),
	}
