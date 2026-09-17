"""只读：折叠回合按「重冻结 / 纯追加」拆开，看前缀失稳到底来自哪个动作。

用法：python tests/wsc/_fold_anatomy.py <turns_closure.jsonl>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    rows = [
        json.loads(line) for line in Path(argv[0]).open(encoding="utf-8") if line.strip()
    ]
    ev = [r for r in rows if r.get("compaction_event")]
    print(f"fold turns: {len(ev)}")
    print(f"{'turn':>5} {'refroze':>7} {'appends':>7} {'hot':>6} {'L':>8} {'U':>8} {'hit':>6} {'lcp_prev':>8}")
    for r in ev:
        print(
            f"{r['turn']:>5} {int(bool(r.get('journal_refroze'))):>7} "
            f"{int(r.get('journal_appends', 0)):>7} {r['hot_tokens']:>6} {r['wsc_tokens']:>8} "
            f"{r['wsc_tokens'] * (1 - r['wsc_hit']):>8.0f} {r['wsc_hit']:>6.3f} {r['lcp_prev']:>8}"
        )
    for name, g in (
        ("重冻结", [r for r in ev if r.get("journal_refroze")]),
        ("纯追加折叠", [r for r in ev if not r.get("journal_refroze")]),
    ):
        if not g:
            continue
        n = len(g)
        print(
            f"{name}: n={n}  meanU={sum(r['wsc_tokens'] * (1 - r['wsc_hit']) for r in g) / n:.0f}  "
            f"mean_hit={sum(r['wsc_hit'] for r in g) / n:.3f}  "
            f"meanL={sum(r['wsc_tokens'] for r in g) / n:.0f}  "
            f"mean_hot={sum(r['hot_tokens'] for r in g) / n:.0f}  "
            f"mean_appends={sum(int(r.get('journal_appends', 0)) for r in g) / n:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
