"""a3_correct_audit — 字段名修正版：by_session 用 cache_hit/cache_miss。"""

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
        print(f"\n=== {day} ===")
        bs = det.get("by_session") or []
        for s in bs:
            h = s.get("cache_hit") or 0
            mi = s.get("cache_miss") or 0
            hr = s.get("hit_rate")
            print(f"  sess={s.get('session_id','')[:28]:<28} req={s.get('requests')} hit={h} miss={mi} hr={hr} prompt={s.get('prompt_tokens')}")
        # 校验 sum(by_session hit/miss) == 总
        sh = sum(int(s.get("cache_hit") or 0) for s in bs)
        sm = sum(int(s.get("cache_miss") or 0) for s in bs)
        print(f"  by_session 总和: hit={sh} miss={sm} (总 hit={v.get('cache_hit')} miss={v.get('cache_miss')}) "
              f"一致? {sh==int(v.get('cache_hit') or 0) and sm==int(v.get('cache_miss') or 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
