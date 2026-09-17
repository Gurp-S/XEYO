"""只读分析：把 adopted 口径下的成本拆到「折叠回合 / 非折叠回合」，并归因 miss 体积。

用法：python tests/wsc/_cost_decompose.py <turns_closure.jsonl>
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path


def _agg(rs: list[dict], name: str) -> None:
    if not rs:
        print(f"{name:22} -")
        return
    L = sum(r["wsc_tokens"] for r in rs)
    U = sum(r["wsc_tokens"] * (1 - r["wsc_hit"]) for r in rs)
    with_v = [r for r in rs if r["v61_tokens"] > 0]
    VL = sum(r["v61_tokens"] for r in with_v)
    VU = sum(r["v61_tokens"] * (1 - r["v61_hit"]) for r in with_v)
    print(
        f"{name:22} n={len(rs):>4}  WSC L={L:>9} U={U:>9.0f} ({U / max(1, L):>5.1%})  "
        f"v6.1 L={VL:>9} U={VU:>9.0f} ({VU / max(1, VL):>5.1%})"
    )
    print(
        f"{'':22} 每回合中位  L={st.median([r['wsc_tokens'] for r in rs]):>7.0f}  "
        f"U={st.median([r['wsc_tokens'] * (1 - r['wsc_hit']) for r in rs]):>7.0f}  "
        f"wsc_hit={st.fmean([r['wsc_hit'] for r in rs]):.3f}  "
        f"v61_hit={st.fmean([r['v61_hit'] for r in with_v]):.3f}"
        if with_v
        else ""
    )
    print(
        f"{'':22} 成本 wsc=¥{sum(r['wsc_cost'] for r in rs):.4f}  "
        f"v6.1=¥{sum(r['v61_cost'] for r in rs):.4f}"
    )


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    path = Path(argv[0])
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    act = [r for r in rows if r.get("wsc_active")]
    ev = [r for r in act if r.get("compaction_event")]
    ne = [r for r in act if not r.get("compaction_event")]
    _agg(rows, "ALL")
    _agg(act, "ACTIVE（紧凑态）")
    _agg(ev, "FOLD（折叠回合）")
    _agg(ne, "ACTIVE no-fold")
    print()
    print("折叠回合明细（turn, head_tokens, cursor, cut, L, U, hit）:")
    for r in ev:
        u = r["wsc_tokens"] * (1 - r["wsc_hit"])
        print(
            f"  t{r['turn']:>4}  head={r['head_tokens']:>6}  cursor={r['cursor']:>5}  "
            f"cut={r['cut']:>5}  L={r['wsc_tokens']:>7}  U={u:>8.0f}  hit={r['wsc_hit']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
