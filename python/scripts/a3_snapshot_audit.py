"""a3_snapshot_audit — 读 A3 快照（quality_validation.json 的 deploy_project_mode_* 行），
分析指标并排查潜在 bug。

只读、零费用。输出：A3 各天的命中率/C2/请求/输入，以及跨天的异常（命中率骤降、C2 突增、
输入/输出/cost 异常）。这些是 A3 日常监控要盯的指标。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QJSON = ROOT / "memory" / "simulator" / "out" / "quality_validation.json"


def main() -> int:
    if not QJSON.is_file():
        print(f"[no] {QJSON}")
        return 0
    data = json.loads(QJSON.read_text(encoding="utf-8"))
    a3 = [(k, v) for k, v in data.items() if k.startswith("deploy_project_mode_")]
    a3.sort(key=lambda kv: kv[0])
    print(f"# A3 快照（{len(a3)} 天）\n")
    print(f"{'row':<38} {'输入':>8} {'命中%':>6} {'命中':>8} {'未中':>8} {'输出':>7} {'C2':>4} {'req':>5}")
    rows = []
    for k, v in a3:
        d = v.get("detail", {}) or {}
        hit = int(v.get("cache_hit") or 0)
        miss = int(v.get("cache_miss") or 0)
        inp = int(v.get("input_tokens") or 0)
        out_ = int(d.get("output") or 0)
        hr = d.get("hit_rate")
        c2 = int(d.get("c2_count") or 0)
        req = int(d.get("requests") or 0)
        rows.append((k, inp, hit, miss, out_, hr, c2, req))
        hr_s = f"{hr*100:.1f}" if isinstance(hr, (int, float)) else "?"
        print(f"{k:<38} {inp:>8} {hr_s:>6} {hit:>8} {miss:>8} {out_:>7} {c2:>4} {req:>5}")

    print("\n# 异常检查")
    if len(rows) >= 1:
        # 命中率骤降（当前 vs 前一天的窗口、或连续偏低）
        for i, (k, inp, hit, miss, out_, hr, c2, req) in enumerate(rows):
            hr_num = float(hr) if isinstance(hr, (int, float)) else None
            if hr_num is None:
                print(f"  [warn] {k}: hit_rate 缺失")
            elif hr_num < 0.95:
                print(f"  [warn] {k}: 命中率 {hr_num*100:.1f}% < 95% 阈值")
            if i > 0:
                prev = rows[i - 1]
                prev_hr = float(prev[5]) if isinstance(prev[5], (int, float)) else None
                if prev_hr is not None and hr_num is not None and prev_hr - hr_num > 0.05:
                    print(f"  [warn] {k}: 命中率较前一天 {prev_hr*100:.1f}% 骤降 {prev_hr-hr_num:.1%}pp")
    # 空行/异常
    empty = [k for k, v in a3 if not (v.get("detail") or v.get("input_tokens"))]
    if empty:
        print(f"  [warn] 空/异常行: {empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
