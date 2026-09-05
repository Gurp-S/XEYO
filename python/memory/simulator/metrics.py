"""P2 metrics: cache error, action mix, agent-quality proxies. Not used in J."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Iterable, Sequence


def _pct(xs: Sequence[float], p: float) -> float:
	if not xs:
		return 0.0
	s = sorted(xs)
	if p <= 0:
		return float(s[0])
	if p >= 100:
		return float(s[-1])
	k = (len(s) - 1) * (p / 100.0)
	lo = int(k)
	hi = min(lo + 1, len(s) - 1)
	w = k - lo
	return float(s[lo] * (1 - w) + s[hi] * w)


def summarize_values(xs: Sequence[float]) -> dict[str, float]:
	if not xs:
		return {"n": 0, "mean": 0.0, "median": 0.0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0}
	return {
		"n": float(len(xs)),
		"mean": float(mean(xs)),
		"median": float(median(xs)),
		"p50": _pct(xs, 50),
		"p90": _pct(xs, 90),
		"p95": _pct(xs, 95),
		"max": float(max(xs)),
	}


@dataclass
class HitRecord:
	request_id: str
	provider: str
	cache_age: float
	action: str
	LCP: int
	predicted_hit: float
	observed_hit: float
	prompt_tokens: int
	output_tokens: int
	predicted_cost: float
	actual_cost: float
	context_length: int = 0
	conversation_length: int = 0
	tool_result_size: int = 0


def cache_errors(rows: Sequence[HitRecord]) -> dict[str, Any]:
	if not rows:
		return {"n": 0, "MAE": 0.0, "MAPE": 0.0, "Bias": 0.0, "E_hit": 0.0}
	n = len(rows)
	mae = sum(abs(r.predicted_hit - r.observed_hit) for r in rows) / n
	mape = sum(
		abs(r.predicted_hit - r.observed_hit) / max(r.observed_hit, 1.0) for r in rows
	) / n
	bias = sum(r.predicted_hit - r.observed_hit for r in rows) / n
	e_hit = sum(
		(r.predicted_hit - r.observed_hit) / max(abs(r.prompt_tokens), 1) for r in rows
	) / n
	return {"n": n, "MAE": mae, "MAPE": mape, "Bias": bias, "E_hit": e_hit}


def cache_errors_by_bucket(rows: Sequence[HitRecord]) -> dict[str, dict[str, Any]]:
	buckets: dict[str, list[HitRecord]] = defaultdict(list)
	for r in rows:
		buckets[f"provider={r.provider}"].append(r)
		buckets[f"action={r.action}"].append(r)
		if r.cache_age <= 0:
			age_b = "age=continuous"
		elif r.cache_age <= 300:
			age_b = "age<=5m"
		elif r.cache_age <= 600:
			age_b = "age<=10m"
		elif r.cache_age <= 1800:
			age_b = "age<=30m"
		elif r.cache_age <= 3600:
			age_b = "age<=1h"
		else:
			age_b = "age>1h"
		buckets[age_b].append(r)
		if r.context_length < 4_000:
			buckets["ctx<4k"].append(r)
		elif r.context_length < 32_000:
			buckets["ctx<32k"].append(r)
		else:
			buckets["ctx>=32k"].append(r)
	return {k: cache_errors(v) for k, v in buckets.items()}


def bias_flags(rows: Sequence[HitRecord]) -> list[str]:
	flags = []
	by = cache_errors_by_bucket(rows)
	long_ctx = by.get("ctx>=32k")
	ttl = [by.get("age<=5m"), by.get("age<=10m"), by.get("age>1h")]
	if long_ctx and long_ctx["n"] >= 3 and long_ctx["Bias"] > 0 and long_ctx["MAE"] > 0:
		# systematic overestimate on long context
		if abs(long_ctx["Bias"]) > 0.5 * max(long_ctx["MAE"], 1e-9):
			flags.append("long_context_overestimate" if long_ctx["Bias"] > 0 else "long_context_underestimate")
	edge = by.get("age>1h")
	mid = by.get("age<=5m")
	if edge and mid and edge["n"] >= 1 and mid["n"] >= 1:
		if abs(edge["Bias"]) > abs(mid["Bias"]) * 2 + 1:
			flags.append("ttl_boundary_bias")
	return flags


@dataclass
class ActionCounts:
	total: int = 0
	keep: int = 0
	C1: int = 0
	C2: int = 0
	HardTop: int = 0
	L4: int = 0
	a4: Counter[str] = field(default_factory=Counter)
	a8: Counter[str] = field(default_factory=Counter)
	a16: Counter[str] = field(default_factory=Counter)
	vote: Counter[str] = field(default_factory=Counter)
	by_scene: dict[str, Counter[str]] = field(default_factory=dict)

	def add(self, action: str, *, hardtop: bool, scene: str, a4: str, a8: str, a16: str, vote: str) -> None:
		self.total += 1
		if hardtop:
			self.HardTop += 1
		key = action if action in ("keep", "C1", "C2", "L4") else "other"
		if key == "keep":
			self.keep += 1
		elif key == "C1":
			self.C1 += 1
		elif key == "C2":
			self.C2 += 1
		elif key == "L4":
			self.L4 += 1
		self.a4[a4] += 1
		self.a8[a8] += 1
		self.a16[a16] += 1
		self.vote[vote] += 1
		self.by_scene.setdefault(scene, Counter())[action] += 1

	def anomalies(self) -> list[str]:
		out = []
		if self.total <= 0:
			return out
		if self.keep / self.total >= 0.99:
			out.append("keep_near_100pct")
		if self.C2 / self.total >= 0.40:
			out.append("C2_very_frequent")
		if self.HardTop / self.total >= 0.25:
			out.append("HardTop_high")
		return out

	def as_dict(self) -> dict[str, Any]:
		return {
			"total_decisions": self.total,
			"keep_count": self.keep,
			"C1_count": self.C1,
			"C2_count": self.C2,
			"hardtop_count": self.HardTop,
			"L4_count": self.L4,
			"R4": dict(self.a4),
			"R8": dict(self.a8),
			"R16": dict(self.a16),
			"vote": dict(self.vote),
			"by_scene": {k: dict(v) for k, v in self.by_scene.items()},
			"anomalies": self.anomalies(),
		}


def compact_stats(turns: Iterable[Any]) -> dict[str, float]:
	n = 0
	c1 = c2 = hard = 0
	removed = 0.0
	kept = 0.0
	for t in turns:
		n += 1
		pred = getattr(t, "predicted", None) or getattr(t, "a_star", "")
		if pred == "C1":
			c1 += 1
		elif pred == "C2":
			c2 += 1
		if getattr(t, "hardtop", False):
			hard += 1
		bt = float(getattr(t, "baseline_tokens", 0) or 0)
		vt = float(getattr(t, "v61_tokens", 0) or getattr(t, "L", 0) or 0)
		kept += vt
		removed += max(bt - vt, 0.0)
	ratio = (kept / max(kept + removed, 1.0)) if n else 1.0
	return {
		"compact_total": float(c1 + c2),
		"C1_total": float(c1),
		"C2_total": float(c2),
		"HardTop_total": float(hard),
		"tokens_removed": removed,
		"tokens_kept": kept,
		"average_compression_ratio": ratio,
	}
