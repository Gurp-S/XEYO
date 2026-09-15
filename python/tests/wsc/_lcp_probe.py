"""只读探针：定位 WSC 热层的逐轮前缀失稳来源。

回答两个问题：
1. 热层前缀每轮失稳多少（LCP / 热层长度）、首个失配点落在哪一段？
2. 各段自身的逐轮变动率与前缀失稳率分别是多少？

这是「命中率崩塌」的根因工具，也是规则 1/2 修完后的复测工具。
结论与数据见 `docs/synaptic-compression.md` §11.8 / §11.9。

零写入、零 LLM、不触碰生产链。非 pytest 用例（文件名无 test_ 前缀，不会被收集）。

用法：
    cd python
    ./.venv/Scripts/python.exe tests/wsc/_lcp_probe.py [closure|append_only] [会话数]
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "python" / "synaptic").is_dir():
            return parent
    raise RuntimeError("找不到仓库根（含 python/synaptic 的目录）")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "python"))

from engine.compact import keep_tail_cut, project as c0_project  # noqa: E402
from synaptic.project import project  # noqa: E402
from synaptic.replay import (  # noqa: E402
    _as_api_message,
    _region_raw_tokens,
    load_jsonl,
    user_turn_starts,
)
from synaptic.types import WscParams  # noqa: E402

HEADERS = [
    "[CONSTRAINTS]",
    "[UNRESOLVED]",
    "[TODO]",
    "[WORKING SET]",
    "[MAIN]",
    "[DECISIONS]",
    "[PRUNED]",
    "[NEXT]",
]


def lcp_len(a: str, b: str) -> int:
    n = 0
    m = min(len(a), len(b))
    while n < m and a[n] == b[n]:
        n += 1
    return n


def where(text: str, off: int) -> str:
    """offset 落在哪一段（按段头的首次出现位置切分）。"""
    spans: list[tuple[str, int]] = []
    for h in HEADERS:
        i = text.find(h)
        if i >= 0:
            spans.append((h, i))
    if not spans:
        return "(空)"
    spans.sort(key=lambda x: x[1])
    cur = spans[0][0]
    for name, pos in spans:
        if pos <= off:
            cur = name
        else:
            break
    return cur


def med(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[len(s) // 2]


def probe(path: Path, level: str = "Medium+", mode: str = "closure") -> None:
    rows = load_jsonl(path)
    api = [_as_api_message(r) for r in rows]
    starts = user_turn_starts(api)
    pset = WscParams(level=level, mode=mode).for_level(level)

    prev_state = None
    prev_hot = ""
    ratios: list[float] = []
    toks: list[int] = []
    diverge_hist: Counter[str] = Counter()
    seg_chg: dict[str, list[float]] = defaultdict(list)
    seg_front: dict[str, list[float]] = defaultdict(list)
    order_hist: Counter[tuple[str, ...]] = Counter()
    # 失配性质：n == len(prev_hot) ⇒ 上一轮是本轮的严格前缀（纯追加，无害）；
    # 否则是**串中改写**（真失稳）。
    append_only_turns = 0
    mid_rewrite_turns = 0
    samples: list[tuple[int, str, str, str]] = []

    for t in range(len(starts)):
        end = starts[t + 1] if t + 1 < len(starts) else len(api)
        prefix = api[:end]
        if len(prefix) < 8:
            continue
        region_end = keep_tail_cut(prefix)
        if region_end <= 1:
            continue
        proj = project(
            prefix,
            region_end=region_end,
            params=pset,
            prev=prev_state,
            session=path.stem,
            region_baseline_tokens=_region_raw_tokens(c0_project(prefix[:region_end])),
        )
        hot = proj.text

        # 收益门拒绝的回合：本轮未产生压缩态，不参与前缀连续性统计
        if not proj.result.compressed:
            prev_hot = hot
            continue

        if prev_hot:
            n = lcp_len(hot, prev_hot)
            ratios.append(n / max(1, len(hot)))
            toks.append(int(len(hot[:n].encode("utf-8")) / 4))
            diverge_hist[where(hot, n)] += 1
            if n >= len(prev_hot):
                append_only_turns += 1
            else:
                mid_rewrite_turns += 1
                if len(samples) < 6:
                    samples.append((n, where(hot, n), prev_hot[max(0, n - 60) : n + 60], hot[max(0, n - 60) : n + 60]))
        for h, r in proj.result.churn.items():
            seg_chg[h].append(r)
        for h, r in proj.result.front_break.items():
            seg_front[h].append(r)
        order_hist[tuple(proj.state.seg_order)] += 1

        prev_state = proj.state
        prev_hot = hot

    n_r = max(1, len(ratios))
    print(f"会话 {path.stem}  消息 {len(api)}  回合 {len(ratios)}  模式 {mode}")
    print(
        f"  前缀连续性 mean {sum(ratios) / n_r:.1%}  median {med(ratios):.1%}  "
        f"中位 lcp_tok {med([float(x) for x in toks]):.0f}"
    )
    print(
        f"  失配性质：纯追加（上轮是本轮前缀）{append_only_turns} 轮 / "
        f"串中改写 {mid_rewrite_turns} 轮"
    )
    print("  首个失配点所在段分布：")
    for sec, c in diverge_hist.most_common():
        print(f"    {sec:<16} {c}")
    if samples:
        print("  串中改写样本（失配点前后 60 字符）：")
        for off, sec, a, b in samples:
            print(f"    @{off} [{sec}]")
            print(f"      prev… {a!r}")
            print(f"      new … {b!r}")
    print("  各段逐轮变动率 / 前缀失稳率（末轮累计口径）：")
    for h in HEADERS:
        if h not in seg_chg:
            continue
        print(
            f"    {h:<16} 变动 {med(seg_chg[h]):.0%}  前缀失稳 {med(seg_front[h]):.0%}"
        )
    print("  采用的段落次序（次数）：")
    for o, c in order_hist.most_common(3):
        print(f"    {c:>4} × {' → '.join(o)}")


def main() -> None:
    sess_dir = Path.home() / ".xeyo" / "sessions"
    files = sorted(sess_dir.glob("*.jsonl"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        print("no sessions")
        return
    mode = sys.argv[1] if len(sys.argv) > 1 else "closure"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for p in files[:count]:
        probe(p, mode=mode)
        print()


if __name__ == "__main__":
    main()
