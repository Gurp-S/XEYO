"""从 wsc_offline_report.json 提取关键指标（只读）。

用法：
    ./.venv/Scripts/python.exe tests/wsc/_report_digest.py <report.json> [<report.json> ...]

为什么需要它：报告 JSON 字段名与直觉不同（是 `hit_rate_wsc` 不是 `hit_rate`、
是 `sessions` 不是 `n_sessions`；`predicted_hit` 存的是 token 数不是比率、
`wsc_tokens` 已含尾部……）。这里把会报的数字按**同一张表**打印，避免跨臂口径漂移。
"""

from __future__ import annotations

import io
import json
import sys

_DIST = ("n", "mean", "median", "p10", "p50", "p90", "p95", "max")


def _fmt(v):
	if isinstance(v, dict):
		parts = [f"{k}={v[k]:.4g}" for k in _DIST if k in v]
		return "{" + ", ".join(parts) + "}"
	return v


def digest(path: str) -> None:
	rep = json.load(io.open(path, encoding="utf-8"))
	print("=" * 78)
	print(f"# {path}")
	print(f"corpus {rep.get('corpus')}  n_files {rep.get('n_files')}  sampling {rep.get('sampling')}")
	print(f"determinism {rep.get('determinism')}")
	print(f"static_checks {rep.get('static_checks')}")

	for r in rep.get("results", []):
		print("-" * 78)
		print(
			f"[{r.get('label')}]  sessions={r.get('sessions')} turns={r.get('turns')} "
			f"skipped={r.get('skipped')} compared={r.get('compared_turns')} "
			f"baseline_missing={r.get('baseline_missing_turns')}"
		)
		if r.get("errors"):
			print(f"  errors: {r['errors']}")

		print(f"  ★ hit_rate_wsc    {_fmt(r.get('hit_rate_wsc'))}")
		print(f"    hit_rate_v61    {_fmt(r.get('hit_rate_v61'))}")
		print(
			f"  ★ hit_rate STEADY（跳各会话首回合，n={r.get('steady_turns')}）\n"
			f"      wsc {_fmt(r.get('hit_rate_wsc_steady'))}\n"
			f"      v61 {_fmt(r.get('hit_rate_v61_steady'))}"
		)
		print(f"    lcp_prev_tokens {_fmt(r.get('lcp_prev_tokens'))}")
		print(f"    base_tokens     {_fmt(r.get('base_tokens'))}")
		print(f"    hot_tokens      {_fmt(r.get('hot_tokens'))}")
		print(f"    wsc_tokens      {_fmt(r.get('wsc_tokens'))}")
		print(f"    v61_tokens      {_fmt(r.get('v61_tokens'))}")
		print(f"    hot_share_of_base {_fmt(r.get('hot_share_of_base'))}")
		print(f"    reduction_vs_base              {_fmt(r.get('reduction_vs_base'))}")
		print(f"    reduction_vs_base_compressed   {_fmt(r.get('reduction_vs_base_compressed_only'))}")
		print(f"    reduction_vs_v61               {_fmt(r.get('reduction_vs_v61'))}")
		print(f"    latency_ms      {_fmt(r.get('latency_ms'))}")
		print(
			f"  ★ cost_wsc_total {r.get('cost_wsc_total'):.4f}  "
			f"cost_v61_total {r.get('cost_v61_total'):.4f}  "
			f"比值 {r.get('cost_wsc_total') / max(1e-9, r.get('cost_v61_total')):.4f}  "
			f"| steady 比值 {r.get('cost_wsc_steady', 0) / max(1e-9, r.get('cost_v61_steady', 1)):.4f}"
		)
		print(
			f"  ★ gain_gate_skip_rate {r.get('gain_gate_skip_rate'):.4f}  "
			f"rebuild_events {r.get('rebuild_events')}  rebuild_rate {r.get('rebuild_rate'):.4f}"
		)
		print(f"  日志布局 {r.get('journal')}")
		print(f"  ★ 用户原话覆盖(节点级) {r.get('user_requests')}")
		ns = r.get("needle_survival") or {}
		print(f"  关键信息针存活(去重口径) { {k: round(v.get('mean_rate', 0), 4) for k, v in ns.items()} }")
		rec = r.get("recoverability") or {}
		print(f"  可恢复性 {rec}")
		print(f"  llm_calls {r.get('llm_calls')}  churn_warn_turns {r.get('churn_warn_turns')}")
		ch = r.get("churn") or {}
		for h, v in ch.items():
			print(
				f"    {h:<16} change_mean {v.get('change_mean'):.3f}  "
				f"front_break_mean {v.get('front_break_mean'):.3f}  turns {v.get('turns')}"
			)
	print()


if __name__ == "__main__":
	for p in sys.argv[1:]:
		digest(p)
