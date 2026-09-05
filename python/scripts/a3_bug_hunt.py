"""a3_bug_hunt — 深挖 A3 暴露的异常，排查可能 bug。

针对：① glm-5.3-flash 命中率 45% ② C2 计数与命中率关系 ③ by_session 缺 hit/miss。
也复算 A3 聚合是否自洽（sum(by_session)==总 / 分段 hit 是否等于 cache_hit）。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QJSON = ROOT / "memory" / "simulator" / "out" / "quality_validation.json"


def main() -> int:
    d = json.loads(QJSON.read_text(encoding="utf-8"))
    rows = d["rows"]
    for day in ("deploy_project_mode_2026-09-03", "deploy_project_mode_2026-09-04"):
        v = rows.get(day)
        if not v:
            continue
        det = v.get("detail", {}) or {}
        total_hit = int(v.get("cache_hit") or 0)
        total_miss = int(v.get("cache_miss") or 0)
        total_in = int(v.get("input_tokens") or 0)
        print(f"\n=== {day} ===")
        print(f"  总 hit={total_hit} miss={total_miss} sum={total_hit+total_miss} input={total_in} "
              f"sum==input? {total_hit+total_miss==total_in}")
        # by_model 自洽
        bm = det.get("by_model") or []
        m_hit = sum(int(m.get("cache_hit") or 0) for m in bm)
        m_miss = sum(int(m.get("cache_miss") or 0) for m in bm)
        print(f"  by_model sum: hit={m_hit} miss={m_miss} (总 hit={total_hit} miss={total_miss}) "
              f"一致? {m_hit==total_hit and m_miss==total_miss}")
        if bm:
            print("  -- 各模型 --")
            for m in bm:
                h = int(m.get("cache_hit") or 0); mi = int(m.get("cache_miss") or 0)
                hr = m.get("hit_rate")
                print(f"   {m.get('model')[:28]} req={m.get('requests')} hit={h} miss={mi} hr={hr}")
        # by_session hit/miss 是否缺失
        bs = det.get("by_session") or []
        missing = [s for s in bs if s.get("hit") is None or s.get("miss") is None]
        print(f"  by_session count={len(bs)} 缺 hit/miss 的 = {len(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
