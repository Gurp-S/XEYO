"""a3_deep_audit — 读 A3 快照行 + A/B 数据，深入排查 bug。

只读。输出 A3 两天明细 + ab_real_new/old 对比（命中率/保真/成本），供排查。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QJSON = ROOT / "memory" / "simulator" / "out" / "quality_validation.json"


def main() -> int:
    d = json.loads(QJSON.read_text(encoding="utf-8"))
    rows = d["rows"]

    print("# A3 快照行精度")
    for k in sorted(k for k in rows if k.startswith("deploy_project_mode_")):
        v = rows[k]
        det = v.get("detail", {}) or {}
        hr = det.get("hit_rate")
        print(f"\n[{k}]")
        print(f"  source={v.get('source')} input={v.get('input_tokens')} hit={v.get('cache_hit')} "
              f"miss={v.get('cache_miss')} hit_rate={hr}")
        print(f"  requests={det.get('requests')} output={det.get('output')} cost={det.get('cost_cny')} "
              f"c2_count={det.get('c2_count')}")
        # 分段 hits/miss 不一致排查
        by_model = det.get("by_model")
        if isinstance(by_model, list) and by_model:
            print("  by_model:")
            for m in by_model[:6]:
                hr_i = m.get("hit_rate")
                print(f"    {m.get('model')}@{m.get('provider')} req={m.get('requests')} "
                      f"hit={m.get('cache_hit')} miss={m.get('cache_miss')} hr={hr_i}")
        # by_turn 是否有负/超窗
        by_sess = det.get("by_session")
        if isinstance(by_sess, list):
            print(f"  by_session rows = {len(by_sess)}")
            for s in by_sess[:6]:
                print(f"    {s.get('session_id','')[:24]} req={s.get('requests')} hit={s.get('hit')} miss={s.get('miss')} c2={s.get('c2_count')}")

    print("\n# A/B 数据（ab_real_new vs ab_real_old）")
    ab = d.get("ab", {})
    for side, val in (("real", ab.get("real")), ("synth", ab.get("synth"))):
        if not isinstance(val, dict):
            continue
        print(f"\n## {side}")
        for k, v in val.items():
            if not isinstance(v, dict):
                continue
            # 只打保真/成本相关
            keys = [x for x in v.keys() if any(t in x.lower() for t in ("fid", "cost", "stack", "surv", "q", "keep", "c2"))]
            if keys:
                brief = {x: v[x] for x in keys}
                print(f"  {k}: {brief}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
