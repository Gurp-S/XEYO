"""只读探针：拆开 hit_rate 的每一步，回答三个归因问题 + 抽样伪影。

背景：报告里 `append_only` 重建率 14.0% 却只有 0.092 命中率。若 append_only 真是
「字节冻结 + 只追加」，上一轮投影就该原封不动成为本轮前缀，命中率该接近 1。
这个表观矛盾必须先拆开，否则后续所有优化都在错误靶子上。

三问：
  Q1  rho_hat 的输入变量是什么？age=0 时它是否只是常数？
  Q2  分母是 total_tokens 还是 cacheable_prefix_tokens？
  Q3  手算连续两轮投影的逐字节 LCP，除以「上一轮去尾长度」——真实前缀连续性是多少？

做法：monkeypatch `synaptic.replay._measure` 与 `synaptic.replay.project`，
把每轮真实的 (proj.text, pr.x, cache.x_prev, spl) 抓下来，不改任何生产代码。
每回合恰好各调一次 project / _measure（收益门分支两者也都调），故两个日志按下标配对。

用法：
  python tests/wsc/_hitrate_probe.py <session.jsonl> [mode] [max_turns] [sample_turns]
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from memory.simulator.cache_model import CacheState, rho_hat  # noqa: E402
from memory.simulator.params import load_params  # noqa: E402
from memory.simulator.projection import common_prefix, lcp_tokens  # noqa: E402
from memory.simulator.state_model import token_len  # noqa: E402
from synaptic.types import MODE_APPEND_ONLY  # noqa: E402


def _f(x: float, n: int = 4) -> str:
    return f"{x:.{n}f}"


def diagnose_rho() -> list[str]:
    p = load_params()
    lines = [
        "== Q1  rho_hat 输入变量 ==",
        f"  alpha_hit={p.alpha_hit}  g(块对齐)={p.g}",
        f"  rho_age_table={p.rho_age_table}",
    ]
    for age in (0.0, 30.0, 300.0, 600.0, 1800.0, 3600.0, 7200.0, 100000.0):
        lines.append(f"  age={age:>9.0f}s -> rho_hat={_f(rho_hat(CacheState(age_seconds=age), p))}")
    lines.append("  结论：rho_hat 只依赖 age_seconds（乘 alpha_hit）。它不看 LCP、不看长度。")
    lines.append("        age=0 时 rho_hat=1.0 ⇒ H = ⌊lcp/g⌋·g，命中率数值上就是「量化 LCP / L」。")
    return lines


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else MODE_APPEND_ONLY
    max_turns = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    sample_turns = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    growth = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    no_journal = len(sys.argv) > 6 and sys.argv[6] == "nojournal"

    out: list[str] = []
    out.extend(diagnose_rho())
    out.append("")
    out.append(
        f"== {path.name}  mode={mode}  sample_turns={sample_turns}  "
        f"journal={'off' if no_journal else 'on'}  growth={growth or 'default'} =="
    )

    import synaptic.replay as rp
    from synaptic.types import WscParams as _WP

    pset = None
    if growth or no_journal:
        kw = {}
        if growth:
            kw["journal_growth_tokens"] = growth
        if no_journal:
            kw["journal_layout"] = False
        pset = _WP(mode=mode, **kw).for_level("Medium+")

    proj_log: list[dict] = []
    meas_log: list[dict] = []
    real_measure = rp._measure
    real_project = rp.project

    def wrap_measure(state, cache, sp):
        pr, spl, biz = real_measure(state, cache, sp)
        meas_log.append(
            {
                "x": pr.x,
                "L": int(pr.length),
                "x_prev": cache.x_prev,
                "lcp": int(spl.lcp),
                "H": float(spl.H),
                "rho": float(spl.rho),
            }
        )
        return pr, spl, biz

    def wrap_project(*a, **kw):
        proj = real_project(*a, **kw)
        proj_log.append(
            {
                "hot": proj.text,
                "hot_tok": token_len(proj.text),
                "rebuilt": bool(proj.result.rebuilt),
                "compressed": bool(proj.result.compressed),
            }
        )
        return proj

    rp._measure = wrap_measure
    rp.project = wrap_project
    try:
        rec = rp.run_session(path, mode=mode, sample_turns=sample_turns, params=pset)
    finally:
        rp._measure = real_measure
        rp.project = real_project

    n = min(len(proj_log), len(meas_log))
    if n == 0:
        out.append("(无回合)")
        print("\n".join(out))
        return 0

    cmp_turns = {t.turn: t for t in rec.turns}
    rows = []
    for i in range(n):
        pj, ms = proj_log[i], meas_log[i]
        turn = rec.turns[i].turn if i < len(rec.turns) else -1
        rows.append((turn, pj, ms))
    if max_turns:
        rows = rows[:max_turns]

    out.append(
        "  turn |    L   | hot_tok | tail_tok | lcp模型 |   H    | H/L    | "
        "hot_prev/L | region_lcp/L | rb | vz"
    )
    prev_hot = None
    prev_turn = None
    agg: dict[str, list[float]] = {
        k: [] for k in ("hit", "ceil", "region", "tail_frac", "hot_frac")
    }
    tot_L = tot_hot = tot_tail = 0
    n_rebuild = n_void = 0
    max_ok = True

    for turn, pj, ms in rows:
        L = max(1, ms["L"])
        hot = pj["hot_tok"]
        tail = max(0, L - hot)
        prev_hot_tok = token_len(prev_hot) if prev_hot is not None else 0
        region_lcp = (
            token_len(common_prefix(pj["hot"], prev_hot)) if prev_hot is not None else 0
        )
        hit = ms["H"] / L
        void = ms["lcp"] <= ms["lcp"] * 0 + 4 and prev_turn is not None  # lcp≈0 ⇒ 全 miss
        if ms["lcp"] < 8 and prev_turn is not None:
            n_void += 1
        if pj["rebuilt"]:
            n_rebuild += 1
        # 交叉验证：模型 lcp 是否等于原始字符串 LCP
        recheck = lcp_tokens(ms["x"], ms["x_prev"]) if ms["x_prev"] else 0
        if recheck != ms["lcp"]:
            max_ok = False
        out.append(
            f"  {turn:>4} | {L:>6} | {hot:>7} | {tail:>8} | {ms['lcp']:>7} | "
            f"{ms['H']:>6.0f} | {_f(hit)} | "
            f"{_f(prev_hot_tok / L) if prev_hot is not None else '   —'} | "
            f"{_f(region_lcp / L) if prev_hot is not None else '   —'} | "
            f"{'Y' if pj['rebuilt'] else '.'}  | {int(ms['lcp'] < 8 and prev_turn is not None)}"
        )
        if prev_hot is not None:
            agg["hit"].append(hit)
            agg["ceil"].append(prev_hot_tok / L)
            agg["region"].append(region_lcp / L)
            agg["tail_frac"].append(tail / L)
            agg["hot_frac"].append(hot / L)
        tot_L += L
        tot_hot += hot
        tot_tail += tail
        prev_hot = pj["hot"]
        prev_turn = turn

    def mean(xs: list[float]) -> float:
        return sum(xs) / max(1, len(xs))

    sum_h = sum(m["H"] for _t, _p, m in rows)
    sum_l = sum(m["L"] for _t, _p, m in rows)
    sum_u = sum_l - sum_h
    out.append("")
    out.append("== 汇总 ==")
    out.append(f"  回合数 {len(rows)}   ΣL={sum_l}  ΣH={sum_h:.0f}  ΣU(未命中)={sum_u:.0f}")
    out.append(f"  每回合投影 mean {sum_l / max(1, len(rows)):.0f} tok")
    out.append(f"  模型 lcp 与原始字符串 LCP 一致：{'是' if max_ok else '否'}")
    out.append(f"  整层重建回合 {n_rebuild}（{n_rebuild / max(1, len(rows)):.1%}）")
    out.append(f"  hot 占投影 {_f(tot_hot / max(1, tot_L))}   tail 占投影 {_f(tot_tail / max(1, tot_L))}")
    out.append(f"  ★ 模型命中率 H/L        均值 {_f(mean(agg['hit']))}   （token 加权 {_f(sum_h / max(1.0, sum_l))}）")
    out.append(f"    （跳首轮）hot_prev/L  均值 {_f(mean(agg['ceil']))}")
    out.append(f"    （跳首轮）region_lcp/L 均值 {_f(mean(agg['region']))}")
    # 成本指数：DeepSeek miss/hit 价差 ≈30× ⇒ 成本 ∝ H + 30·U = 30·L − 29·H
    out.append(f"  成本指数（∝ H+30U，越小越好）：{30 * sum_l - 29 * sum_h:.0f}")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
