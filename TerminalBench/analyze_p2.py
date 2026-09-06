# -*- coding: utf-8 -*-
"""P2 终表生成：合并 jobs_p1b + jobs_p2 的全部 trial → 89 题矩阵 + 分类 + 汇总。

用法: py -3.11 analyze_p2.py
输出: 终端表 + p2_results.json（全量持久化）+ p2_report_data.json（报告数据）
"""
from __future__ import annotations

import glob
import json
import statistics as st

P_HIT, P_MISS, P_OUT = 0.05, 1.5, 4.5
INFRA_MARKERS = ("502", "503", "bad gateway", "connection reset", "timed out", "unable to fetch")


def collect() -> dict[str, list[dict]]:
    """task_name -> [trial dicts]（合并 P1b + P2）"""
    by_task: dict[str, list[dict]] = {}
    for rj in sorted(glob.glob("jobs_p1b/*/*/*/result.json") + glob.glob("jobs_p2/*/*/result.json")):
        try:
            d = json.load(open(rj, encoding="utf-8"))
        except Exception:
            continue
        ar = d.get("agent_result") or {}
        task = d.get("task_id", {}).get("name", "?").split("/")[-1]
        vr = ((d.get("verifier_result") or {}).get("rewards") or {})
        it = ar.get("n_input_tokens") or 0
        ct = ar.get("n_cache_tokens") or 0
        ot = ar.get("n_output_tokens") or 0
        hit = (ct / it) if it else 0.0
        cny = (ct / 1e6 * P_HIT) + ((it - ct) / 1e6 * P_MISS) + (ot / 1e6 * P_OUT) if it else 0.0
        # 基建失败取证：verifier 输出含网络/安装错误标记
        vout_path = rj.replace("result.json", "verifier").replace("\\", "/")
        infra = False
        import os
        tsp = os.path.join(os.path.dirname(rj), "verifier", "test-stdout.txt")
        if os.path.exists(tsp):
            txt = open(tsp, encoding="utf-8", errors="ignore").read().lower()
            infra = any(m in txt for m in INFRA_MARKERS)
        rows = by_task.setdefault(task, [])
        rows.append(dict(
            task=task, reward=vr.get("reward"), input=it, cache=ct,
            hit_pct=round(hit * 100, 1), output=ot, cost_usd=ar.get("cost_usd"),
            cost_cny=round(cny, 3), infra_suspect=infra, source=rj.split("/")[1] if "/" in rj else "",
        ))
    return by_task


def main() -> None:
    by_task = collect()
    all_trials = [t for ts in by_task.values() for t in ts]
    if not all_trials:
        print("无数据")
        return

    # 逐 trial 总表
    print(f"{'task':<34}{'rw':>5}{'input':>11}{'hit%':>7}{'output':>9}{'元':>7}  注")
    for task in sorted(by_task):
        for t in by_task[task]:
            note = "infra?" if (t["reward"] == 0 and t["infra_suspect"]) else ""
            print(f"{task:<34}{str(t['reward']):>5}{t['input']:>11,}{t['hit_pct']:>7}{t['output']:>9,}{t['cost_cny']:>7}  {note}")

    # 89 题矩阵
    n_tasks = len(by_task)
    n_trials = len(all_trials)
    solved_trials = sum(1 for t in all_trials if t["reward"] == 1.0)
    task_solved = sum(1 for ts in by_task.values() if any(t["reward"] == 1.0 for t in ts))
    task_all_fail = [k for k, ts in by_task.items() if all(t["reward"] == 0 for t in ts)]
    infra_cnt = sum(1 for t in all_trials if t["reward"] == 0 and t["infra_suspect"])
    real_fail_tasks = [k for k in task_all_fail if not any(t["infra_suspect"] for t in by_task[k])]
    total_cny = sum(t["cost_cny"] for t in all_trials)

    summary = {
        "n_tasks": n_tasks,
        "n_trials": n_trials,
        "trial_accuracy_pct": round(solved_trials / n_trials * 100, 2),
        "task_pass_at_k_pct": round(task_solved / n_tasks * 100, 2),
        "solved_tasks": task_solved,
        "all_fail_tasks": sorted(task_all_fail),
        "real_fail_tasks_no_infra": sorted(real_fail_tasks),
        "infra_suspect_trials": infra_cnt,
        "input_median": st.median([t["input"] for t in all_trials if t["input"]]),
        "output_median": st.median([t["output"] for t in all_trials if t["output"]]),
        "hit_pct_median": round(st.median([t["hit_pct"] for t in all_trials if t["input"]]), 1),
        "cost_cny_total": round(total_cny, 2),
        "by_task": {k: by_task[k] for k in sorted(by_task)},
    }
    json.dump(summary, open("p2_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n== 汇总 ==")
    for k in ("n_tasks", "n_trials", "trial_accuracy_pct", "task_pass_at_k_pct",
              "infra_suspect_trials", "hit_pct_median", "input_median", "output_median", "cost_cny_total"):
        print(f"  {k}: {summary[k]}")
    print("  全败题:", ", ".join(sorted(task_all_fail)))
    print("已写 p2_results.json")


if __name__ == "__main__":
    main()
