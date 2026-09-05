"""a3_none_hunt — 深挖 (none) session 桶：9-03 有 558 次请求无 session_id。

从 quality_validation.json 的 detail 看 (none) 桶的模型/turn 构成，定位是哪些
调用路径没设置会话上下文（contextvar）→ 记 usage 时 session_id 为空。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QJSON = ROOT / "memory" / "simulator" / "out" / "quality_validation.json"


def main() -> int:
    d = json.loads(QJSON.read_text(encoding="utf-8"))
    rows = d["rows"]
    v = rows.get("deploy_project_mode_2026-09-03")
    det = (v or {}).get("detail", {}) or {}
    bs = det.get("by_session") or []
    # (none) 桶
    none_bs = [s for s in bs if s.get("session_id") == "(none)"]
    print("(none) 桶:", none_bs)
    # by_turn 里 (none) 的模型分布
    bt = det.get("by_turn") or []
    from collections import Counter
    model_count = Counter()
    none_turns = 0
    for t in bt:
        if t.get("session_id") == "(none)":
            none_turns += 1
            model_count[t.get("model")] += 1
    print(f"\nby_turn (none) 轮数 = {none_turns} / total by_turn = {len(bt)}")
    print("(none) 模型分布:", dict(model_count))
    # 看几个 (none) turn 样例
    print("\n样例 (none) turn:")
    for t in bt[:3]:
        if t.get("session_id") == "(none)":
            print("  ", {k: t.get(k) for k in ("label","model","requests","cache_hit","cache_miss","hit_rate")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
