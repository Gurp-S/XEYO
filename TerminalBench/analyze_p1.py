# -*- coding: utf-8 -*-
"""P1 校准结果提取：jobs_p1*/<task>/<job>/<trial>/result.json → 汇总表 + 成本模型回填。

用法: py -3.11 analyze_p1.py [glob ...]   # 默认扫 jobs_p1 与 jobs_p1b
输出: 终端表格 + p1_calibration.json
"""
from __future__ import annotations

import glob
import json
import statistics as st
import sys

# 定价（off-peak 元/百万 tok）——与 cost_model_tb21.py 一致
P_HIT, P_MISS, P_OUT = 0.05, 1.5, 4.5


def analyze() -> None:
    pats = sys.argv[1:] or ["jobs_p1/*/*/*/result.json", "jobs_p1b/*/*/*/result.json"]
    rows = []
    seen = set()
    for pat in pats:
        for rj in sorted(glob.glob(pat)):
            if rj in seen:
                continue
            seen.add(rj)
            try:
                d = json.load(open(rj, encoding="utf-8"))
            except Exception:
                continue
            ar = d.get("agent_result") or {}
            if not ar.get("n_input_tokens"):
                continue  # 跳过空壳（tmux 失败等异常 trial）
            task = d.get("task_id", {}).get("name", "?").split("/")[-1]
            vr = ((d.get("verifier_result") or {}).get("rewards") or {})
            ex = d.get("exception_info")
            rows.append(dict(
                task=task,
                reward=vr.get("reward"),
                it=ar.get("n_input_tokens") or 0,
                ct=ar.get("n_cache_tokens") or 0,
                ot=ar.get("n_output_tokens") or 0,
                cost_usd=ar.get("cost_usd"),
                err=ex.get("exception_type") if isinstance(ex, dict) else None,
            ))

    if not rows:
        print("尚无完成的 trial")
        return

    print(f"{'task':<24}{'reward':>7}{'input':>10}{'cache':>10}{'output':>9}{'cost_usd':>10}  note")
    for r in rows:
        note = f"EXC:{r['err']}" if r["err"] else ""
        print(f"{r['task']:<24}{str(r['reward']):>7}{r['it']:>10,}{r['ct']:>10,}{r['ot']:>9,}{str(r['cost_usd']):>10}  {note}")

    its = [r["it"] for r in rows if r["it"]]
    ots = [r["ot"] for r in rows if r["ot"]]
    cts = [r["ct"] for r in rows if r["ct"]]
    hits = [c / i for i, c in zip(its, cts) if i]
    per = []
    for r in rows:
        if r["it"]:
            miss = r["it"] - r["ct"]
            per.append((r["ct"] / 1e6 * P_HIT) + (miss / 1e6 * P_MISS) + (r["ot"] / 1e6 * P_OUT))
    summary = {
        "n_trials": len(rows),
        "solved": sum(1 for r in rows if r["reward"] == 1.0),
        "input_tokens_median": st.median(its) if its else 0,
        "output_tokens_median": st.median(ots) if ots else 0,
        "cache_hit_ratio_median": round(st.median(hits), 3) if hits else 0,
        "cost_usd_sum": round(sum(r["cost_usd"] or 0 for r in rows), 4),
        "cny_per_trial_offpeak_median": round(st.median(per), 3) if per else 0,
        "cny_per_trial_offpeak_mean": round(st.mean(per), 3) if per else 0,
        "rows": rows,
    }
    json.dump(summary, open("p1_calibration.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n== 汇总 ==")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=1))
    print("已写 p1_calibration.json（供 cost_model_tb21.py 回填）")


if __name__ == "__main__":
    analyze()
