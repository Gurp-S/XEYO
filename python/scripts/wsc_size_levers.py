"""尺寸侧杠杆普查（**只读转录，零 API**）：三档策略下工具结果的发射量。

要回答的问题：把每枪"必须 miss 的新内容"压下来，能压多少、压在哪。

三档（都以 C0 为基线，全部是**投影层**变换，转录一字节不动）：

| 档 | 阈值 | 可见头/尾 | 说明 |
|---|---|---|---|
| `c0`（现状） | 8192 字符 | 4096 / 1024 | 超阈值截断，**没有取回入口** |
| `tight` | 8192 字符 | 1024 / 256 | 同阈值、可见量收紧（约 −73%） |
| `aggr` | 2048 字符 | 512 / 128 | 连中等结果也收（更激进） |

`tight`/`aggr` 两档按 `memory/wsc_size_prune.maybe_prune_with_archive` 的形态估算
（头 + 标记 + 尾 + `Read` 句柄 ≈ +90 字符），**原文一律归档、可回**。

口径与边界：
- 只读 `sess_*.jsonl`（生产家族；bench/ablation/测试残渣不计）；
- 结果按 `role=tool` 的 `tool_result.content` 取，与 `memory/observe._tool_result_chars` 同源；
- 输出的"每枪均值"= Σ削减 / 会话枪数（枪数取自 calibration 账本，取不到则不算该会话）。

用法::

    py -3.11 python/scripts/wsc_size_levers.py [--since 2026-09-25]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

MARKER = "\n\n[... tool result middle pruned ...]\n\n"
ENTRY = 92  # " | 全文: Read(file_path='…', offset=1, limit=N)" 的量级
TIERS = {
    # 名: (阈值, 头, 尾, 是否带取回句柄)
    "c0": (8192, 4096, 1024, False),
    "tight": (8192, 1024, 256, True),
    "aggr": (2048, 512, 128, True),
}


def emitted(text: str, tier: str) -> int:
    thr, head, tail, has_entry = TIERS[tier]
    n = len(text)
    if n <= thr:
        return n
    keep = text[:head] + MARKER + (text[n - tail:] if n - tail > head else "")
    return len(keep) + (ENTRY if has_entry else 0)


def sessions_dir() -> Path:
    import os

    override = (os.environ.get("XEYO_SESSIONS_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    home = (os.environ.get("XEYO_HOME") or "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".xeyo"
    return base / "sessions"


def shots_per_session() -> Counter:
    """每会话的真实枪数（calibration 账本，prompt>0）。"""
    import os

    override = (os.environ.get("XEYO_USAGE_DIR") or "").strip()
    home = (os.environ.get("XEYO_HOME") or "").strip()
    base = Path(override).expanduser() if override else (
        Path(home).expanduser() / "usage" if home else Path.home() / ".xeyo" / "usage")
    p = base / "calibration_events.jsonl"
    out: Counter = Counter()
    if not p.is_file():
        return out
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                r = json.loads(raw)
            except Exception:
                continue
            if int(r.get("prompt_tokens") or 0) > 0:
                out[str(r.get("session_id") or "")] += 1
    return out


def results_of(path: Path) -> list[str]:
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if str(row.get("role")) != "tool":
                continue
            c = row.get("content")
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        s = b.get("content")
                        if isinstance(s, str) and s:
                            out.append(s)
            elif isinstance(c, str) and c:
                out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="工具结果尺寸侧三档杠杆普查（只读）")
    ap.add_argument("--since", default=None, help="只统计 mtime >= 该日期的转录（YYYY-MM-DD）")
    args = ap.parse_args()

    import datetime as dt

    cutoff = (dt.datetime.fromisoformat(args.since).timestamp() if args.since else 0.0)
    shots = shots_per_session()
    sd = sessions_dir()
    files = sorted(sd.glob("sess_*.jsonl"))
    sizes: list[int] = []
    per_sess: dict[str, Counter] = {}
    for f in files:
        if f.stat().st_mtime < cutoff:
            continue
        rs = results_of(f)
        if not rs:
            continue
        c = per_sess.setdefault(f.stem, Counter())
        for s in rs:
            n = len(s)
            sizes.append(n)
            c["results"] += 1
            for tier in TIERS:
                c[tier] += emitted(s, tier)
            c["raw"] += n
        c["shots"] = shots.get(f.stem, 0)

    if not sizes:
        print("没有可用转录")
        return 0
    tot = Counter()
    for c in per_sess.values():
        tot.update(c)
    sizes.sort()

    def pct(q: float) -> int:
        return sizes[min(len(sizes) - 1, int(q * (len(sizes) - 1) + 0.5))]

    print(f"# 尺寸侧杠杆  since={args.since or 'ALL'}  会话={len(per_sess)}  工具结果={len(sizes)}")
    print(f"结果尺寸（字符）：p50={pct(.5):,} p90={pct(.9):,} p99={pct(.99):,} max={sizes[-1]:,}")
    over8k = [x for x in sizes if x > 8192]
    over2k = [x for x in sizes if x > 2048]
    print(f"  >8192 的 {len(over8k)} 条（{len(over8k)/len(sizes):.1%}）合计 {sum(over8k):,} 字符")
    print(f"  >2048 的 {len(over2k)} 条（{len(over2k)/len(sizes):.1%}）合计 {sum(over2k):,} 字符")
    print()
    print(f"{'档':>6s} {'Σ发射(字符)':>14s} {'/现状':>7s} {'相对现状削减':>12s} {'每枪削减(字符)':>14s}")
    base = tot["c0"]
    nshots = sum(c["shots"] for c in per_sess.values() if c["shots"])
    for tier in ("c0", "tight", "aggr"):
        v = tot[tier]
        d = base - v
        print(f"{tier:>6s} {v:>14,} {v/base:>7.3f} {d:>12,} "
              f"{(d/nshots if nshots else 0):>14,.0f}")
    print()
    print(f"（每枪均值按 {nshots} 枪计；token ≈ 字符/4 ⇒ 每枪削减 "
          f"{(base - tot['aggr'])/max(1,nshots)/4:,.0f} tok(aggr) / "
          f"{(base - tot['tight'])/max(1,nshots)/4:,.0f} tok(tight)）")
    top = sorted(per_sess.items(), key=lambda kv: -(kv[1]["c0"] - kv[1]["aggr"]))[:6]
    print()
    print("## 削减最多的会话")
    print(f"{'session':30s} {'结果数':>6s} {'raw字符':>12s} {'c0':>12s} {'tight':>12s} {'aggr':>12s} {'枪':>5s}")
    for sid, c in top:
        print(f"{sid[:30]:30s} {c['results']:>6d} {c['raw']:>12,} {c['c0']:>12,} "
              f"{c['tight']:>12,} {c['aggr']:>12,} {c['shots']:>5d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
