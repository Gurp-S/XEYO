"""prof_stats — 旁路(P0):阶段耗时统计纯函数。

无 IO、无引擎依赖;供 ``turn.stage_timing`` 审计消费方与报告脚本共用。
分位数采用 nearest-rank(常见约定):p50=中位,p99 取第 ceil(0.99n) 个。
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import ceil
from typing import Any


def percentile(sorted_values: Sequence[float], p: float) -> float:
	"""nearest-rank 百分位。入参须已升序;空序列返回 0.0。p∈(0,100]。"""
	n = len(sorted_values)
	if n == 0:
		return 0.0
	if p <= 0:
		return sorted_values[0]
	rank = ceil(p / 100.0 * n) - 1
	rank = max(0, min(n - 1, rank))
	return sorted_values[rank]


def summarize(values: Iterable[float]) -> dict[str, float]:
	"""单组耗时统计:{count,min,mean,p50,p90,p95,p99,max}。"""
	vals = sorted(float(v) for v in values)
	if not vals:
		return {
			"count": 0.0,
			"min": 0.0,
			"mean": 0.0,
			"p50": 0.0,
			"p90": 0.0,
			"p95": 0.0,
			"p99": 0.0,
			"max": 0.0,
		}
	n = len(vals)
	return {
		"count": float(n),
		"min": vals[0],
		"mean": sum(vals) / n,
		"p50": percentile(vals, 50),
		"p90": percentile(vals, 90),
		"p95": percentile(vals, 95),
		"p99": percentile(vals, 99),
		"max": vals[-1],
	}


def group_records(
	records: Iterable[dict[str, Any]],
	*,
	label_key: str,
	value_key: str,
) -> dict[str, list[float]]:
	"""把事件记录按 label 分组取数值列(仅收集可转 float 的值)。"""
	out: dict[str, list[float]] = {}
	for rec in records:
		label = str(rec.get(label_key) or "")
		if not label:
			continue
		try:
			v = float(rec.get(value_key))  # type: ignore[arg-type]
		except (TypeError, ValueError):
			continue
		out.setdefault(label, []).append(v)
	return out


def format_table(
	rows: Iterable[tuple[str, dict[str, float]]],
	*,
	decimals: int = 1,
) -> str:
	"""渲染摘要表(每行=(label, summarize 输出))。"""
	order = ("count", "min", "mean", "p50", "p90", "p95", "p99", "max")
	header = f"{'label':<24} " + " ".join(f"{h:>8}" for h in order)
	lines = [header, "-" * len(header)]
	for label, s in rows:
		cells = " ".join(f"{s.get(h, 0.0):>{8}.{decimals}f}" for h in order)
		lines.append(f"{label:<24} {cells}")
	return "\n".join(lines)


def summarize_grouped(
	grouped: dict[str, list[float]],
) -> list[tuple[str, dict[str, float]]]:
	"""分组字典 → 有序 label 行列表。"""
	return [(label, summarize(v)) for label, v in grouped.items()]
