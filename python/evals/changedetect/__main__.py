"""命令行入口：python -m evals.changedetect <subcommand> ...

子命令：
  surface check          比对 L0 字节级快照与 golden
  surface update         重写 L0 golden
  surface list           列出当前渲染的全部 artifact
  surface selftest       跑 1 字符灵敏度自测（"完美侦测"的证明）

  trace check / update   L1 决策轨迹层（注入 + 回路）
  trace selftest         跑确定性自测（同样输入两次应得同样 hash）

  power                  显示 MDE / 预算表
  ab plan                跑前报价（不发请求）
  ab dry-run             干跑（fake 模型，验管道 + 出统计）
  ab live                实跑（必须 --budget）
  ab replay              复盘已有 ab 报告

  compliance             扫当前 git diff 的新增行

  check                  提交门：surface + trace + selftest，全绿才放行
  all                    上面所有非 ab 子命令合一
  verdict                合成最终判决书
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ab as ab_mod
from . import budget, compliance, surface, trace, verdict

REPO_ROOT = Path(__file__).resolve().parents[3]


def _setup() -> None:
    """保证 stdout 在 Windows 上不丢字。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------


def cmd_surface_check(args: argparse.Namespace) -> int:
    arts = surface.collect()
    changes = surface.compare(arts)
    print(surface.render_index(arts), end="")
    if not changes:
        print("\n[L0] 无变化。")
        return 0
    print(f"\n[L0] 检测到 {len(changes)} 处变化：")
    for ch in changes[: args.max_show]:
        print(
            f"  - {ch.status:<8} {ch.name}  "
            f"({ch.chars_before}→{ch.chars_after}, "
            f"+{ch.added}/-{ch.removed})"
        )
    if len(changes) > args.max_show:
        print(f"  …（其余 {len(changes) - args.max_show} 处）")
    print("\n提示：用 `python -m evals.changedetect surface update` 重写 golden，"
          "但要清楚你在把什么钉成新基线。")
    return 1 if args.strict else 0


def cmd_surface_update(args: argparse.Namespace) -> int:
    arts = surface.collect()
    path = surface.write_golden(arts)
    print(f"[L0] 已重写 {len(arts)} 个 artifact → {path}")
    return 0


def cmd_surface_list(args: argparse.Namespace) -> int:
    arts = surface.collect()
    for a in arts:
        print(f"{a.group:<8} {a.sha[:12]}  {len(a.canonical):>8}  {a.name}")
    return 0


def cmd_surface_selftest(args: argparse.Namespace) -> int:
    rep = surface.mutation_selftest()
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if rep.get("perfect") else 2


def cmd_trace_check(args: argparse.Namespace) -> int:
    batteries = set(args.batteries.split(",")) if args.batteries else None
    tr = trace.collect(batteries)
    changes = trace.compare(tr)
    for name, text in tr.items():
        head = text[:80].replace("\n", "⏎")
        print(f"  {name:<32} {canon_safe_len(text):>6}ch  {head}")
    if not changes:
        print("\n[L1] 无变化。")
        return 0
    print(f"\n[L1] 检测到 {len(changes)} 处轨迹变化：")
    for ch in changes[: args.max_show]:
        print(
            f"  - {ch['status']:<8} {ch['name']}  "
            f"({ch.get('chars_before', 0)}→{ch.get('chars_after', 0)})"
        )
    return 1 if args.strict else 0


def cmd_trace_update(args: argparse.Namespace) -> int:
    tr = trace.collect()
    p = trace.write_golden(tr)
    print(f"[L1] 已重写 {len(tr)} 条轨迹 → {p}")
    return 0


def cmd_trace_selftest(args: argparse.Namespace) -> int:
    a = trace.collect()
    b = trace.collect()
    a_h = {k: canon_sha(v) for k, v in a.items()}
    b_h = {k: canon_sha(v) for k, v in b.items()}
    same = a_h == b_h
    rep = {"deterministic": same, "scenarios": len(a_h), "mismatched": []}
    for k in a_h:
        if a_h[k] != b_h.get(k):
            rep["mismatched"].append(k)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if same else 2


def cmd_power(args: argparse.Namespace) -> int:
    from . import stats

    table = stats.power_table()
    print("# 配对设计的样本预算法（α=0.05, power=0.8）\n")
    print("| 不一致率 ψ | 想测出的效应 | 所需配对数 |")
    print("| ---: | ---: | ---: |")
    for row in table:
        print(
            f"| {row['discordant_rate']:.0%} | {row['effect']:.0%} | "
            f"{row['required_pairs']:,} |"
        )
    print()
    print("## 同模型不同设计的样本量")
    print(f"- 配对 (McNemar)，ψ=10%, δ=1pp → "
          f"{stats.required_pairs(0.10, 0.01):,} 对")
    print(f"- 配对 (McNemar)，ψ=10%, δ=5pp → "
          f"{stats.required_pairs(0.10, 0.05):,} 对")
    print(f"- 非配对，p=0.7, δ=1pp → "
          f"每臂 {stats.required_unpaired(0.7, 0.01):,}")
    print(f"- 非配对，p=0.7, δ=4.5pp（你们的噪声地板）→ "
          f"每臂 {stats.required_unpaired(0.7, 0.045):,}")
    return 0


def _variant_env(values: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for v in values or ():
        if "=" not in v:
            print(f"❌ --variant-env 必须是 KEY=VAL：{v}", file=sys.stderr)
            sys.exit(2)
        k, _, val = v.partition("=")
        out[k.strip()] = val
    return out


def _parse_price(spec: str | None) -> budget.Price:
    if not spec:
        return budget.preset("official-new")
    if spec in ("official-new", "repo-local"):
        return budget.preset(spec)
    return budget.parse_price(spec)


def cmd_ab_plan(args: argparse.Namespace) -> int:
    price = _parse_price(args.price)
    cases = ab_mod.load_battery()
    plan = budget.plan(
        n_tasks=len(cases) if not args.tasks else len(args.tasks),
        repeats=args.repeats,
        arms=2,
        price=price,
        calibration=None,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def cmd_ab_run(args: argparse.Namespace) -> int:
    price = _parse_price(args.price)
    cases = ab_mod.load_battery()
    if args.tasks:
        wanted = set(args.tasks)
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("❌ --tasks 过滤后没有任务", file=sys.stderr)
        return 2
    try:
        rep = ab_mod.run(
            cases=cases,
            repeats=args.repeats,
            variant_env=_variant_env(args.variant_env),
            live=args.live,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            budget_cny=args.budget,
            price=price,
            plan_only=False,
        )
    except budget.BudgetExceeded as exc:
        print(f"❌ 预算门触发：{exc}", file=sys.stderr)
        return 2
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = REPO_ROOT / "artifacts" / "changedetect"
    jp, mp = ab_mod.write_report(rep, out_dir)
    print(f"\n报告：{jp}\n{md_one_line(mp)}")
    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    rep = compliance.scan_git_diff(args.paths)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 1 if rep.get("has_fail") else 0


def cmd_check(args: argparse.Namespace) -> int:
    """提交门：L0 check + L1 check + L0 selftest + L1 selftest。"""
    fails = 0
    for label, fn in (
        ("L0 selftest", _selftest(surface.mutation_selftest)),
        ("L1 selftest", _selftest(trace_selftest_dict)),
        ("L0 check", _selftest(lambda: _check_to_dict(surface.collect(), surface.compare))),
        ("L1 check", _selftest(lambda: _check_to_dict(trace.collect(), trace.compare))),
        ("Compliance", compliance.scan_git_diff),
    ):
        rep = fn()
        ok = _gate_ok(label, rep)
        if not ok:
            fails += 1
    return 0 if fails == 0 else 1


def cmd_all(args: argparse.Namespace) -> int:
    """L0 + L1 + compliance + verdict。"""
    surf = surface.collect()
    sc = surface.compare(surf)
    tr = trace.collect()
    tc = trace.compare(tr)
    diff_text = _git_diff_text()
    v = verdict.build(
        surface_changes=sc,
        trace_changes=tc,
        diff_text=diff_text,
    )
    print(verdict.render_markdown(v))
    out_dir = REPO_ROOT / "artifacts" / "changedetect"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "verdict.json"
    out_path.write_text(
        json.dumps(v.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n→ {out_path}")
    return 0 if v.overall == "pass" or v.overall == "inconclusive" else 1


def cmd_verdict(args: argparse.Namespace) -> int:
    surf = surface.collect()
    sc = surface.compare(surf)
    tr = trace.collect()
    tc = trace.compare(tr)
    ab_report = None
    if args.ab_report:
        ab_report = json.loads(Path(args.ab_report).read_text(encoding="utf-8"))
    v = verdict.build(
        surface_changes=sc,
        trace_changes=tc,
        ab_report=ab_report,
        diff_text=_git_diff_text(args.ab_report is None),
    )
    print(verdict.render_markdown(v))
    return 0 if v.overall in ("pass", "inconclusive") else 1


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------


def canon_safe_len(s: str) -> int:
    return len(s)


def canon_sha(s: str) -> str:
    from . import canon

    return canon.sha(s)


def _selftest(fn):
    def runner():
        return fn()
    return runner


def trace_selftest_dict() -> dict:
    a = trace.collect()
    b = trace.collect()
    a_h = {k: canon_sha(v) for k, v in a.items()}
    b_h = {k: canon_sha(v) for k, v in b.items()}
    return {"deterministic": a_h == b_h, "scenarios": len(a_h)}


def _check_to_dict(arts, compare_fn) -> dict:
    if compare_fn is surface.compare:
        changes = compare_fn(arts)
        return {"changed": bool(changes), "count": len(changes)}
    changes = compare_fn(arts)
    return {"changed": bool(changes), "count": len(changes)}


def _gate_ok(label: str, rep: dict) -> bool:
    if label.endswith("selftest"):
        if label.startswith("L0"):
            ok = bool(rep.get("perfect"))
        else:
            ok = bool(rep.get("deterministic"))
    elif label == "Compliance":
        ok = not rep.get("has_fail")
    else:
        ok = not rep.get("changed")
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}: {rep}")
    return ok


def _git_diff_text(only_real_diff: bool = True) -> str:
    import subprocess

    cmd = ["git", "-c", "core.quotepath=false", "diff", "--no-color"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        if proc.returncode != 0:
            return ""
        return proc.stdout
    except Exception:
        return ""


def md_one_line(p: Path) -> str:
    """截短 markdown 报告用于控制台。"""
    return f"  {p}"


# --------------------------------------------------------------------------
# argparse
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m evals.changedetect",
        description="XEYO 变更收益侦测器（三层金字塔 + 应试性自动扫描）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("surface", help="L0：模型可见文本面")
    ssub = s.add_subparsers(dest="sub", required=True)
    for name, fn, help_ in (
        ("check", cmd_surface_check, "比对 golden"),
        ("update", cmd_surface_update, "重写 golden"),
        ("list", cmd_surface_list, "列出 artifact"),
        ("selftest", cmd_surface_selftest, "1 字符灵敏度证明"),
    ):
        sp = ssub.add_parser(name, help=help_)
        if fn in (cmd_surface_check,):
            sp.add_argument("--strict", action="store_true", help="有变化就 exit 1")
            sp.add_argument("--max-show", type=int, default=20)

    t = sub.add_parser("trace", help="L1：引擎决策轨迹")
    tsub = t.add_subparsers(dest="sub", required=True)
    for name, fn, help_ in (
        ("check", cmd_trace_check, "比对 golden"),
        ("update", cmd_trace_update, "重写 golden"),
        ("selftest", cmd_trace_selftest, "跑两次验证确定性"),
    ):
        sp = tsub.add_parser(name, help=help_)
        if fn is cmd_trace_check:
            sp.add_argument("--batteries", default="")
            sp.add_argument("--strict", action="store_true")
            sp.add_argument("--max-show", type=int, default=20)

    sub.add_parser("power", help="打印 MDE / 样本预算表")

    a = sub.add_parser("ab", help="L2：配对 A/B 统计层")
    asub = a.add_subparsers(dest="sub", required=True)
    for name, fn in (
        ("plan", cmd_ab_plan),
        ("dry-run", cmd_ab_run),
        ("live", cmd_ab_run),
        ("replay", cmd_ab_run),
    ):
        sp = asub.add_parser(name, help=fn.__doc__ or "")
        sp.add_argument("--repeats", type=int, default=1)
        sp.add_argument("--tasks", nargs="+", default=None)
        sp.add_argument("--variant-env", action="append", default=[],
                        help="KEY=VAL 形式（只施加给 arm B），可多次")
        sp.add_argument("--budget", type=float, default=None,
                        help="人民币上限（live 必填，dry-run 可省）")
        sp.add_argument("--price", default="official-new",
                        help="official-new | repo-local | hit,miss,out")
        sp.add_argument("--api-key", default="")
        sp.add_argument("--base-url", default="")
        sp.add_argument("--model", default="")
        sp.add_argument("--out", default="")
        if name in ("live",):
            sp.set_defaults(live=True)
        else:
            sp.set_defaults(live=False)

    sp = sub.add_parser("compliance", help="扫 git diff 新增行的应试性 R1-R4 命中")
    sp.add_argument("paths", nargs="*", help="限定扫描的文件（默认全树）")

    sp = sub.add_parser("check", help="提交门：L0+L1 selftest + check + 应试")
    sp = sub.add_parser("all", help="L0+L1+合规+verdict 一并跑")
    sp = sub.add_parser("verdict", help="合成最终判决书")
    sp.add_argument("--ab-report", default="", help="可选的 A/B 报告 JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    _setup()
    p = build_parser()
    args = p.parse_args(argv)

    if args.cmd == "surface":
        return {
            "check": cmd_surface_check,
            "update": cmd_surface_update,
            "list": cmd_surface_list,
            "selftest": cmd_surface_selftest,
        }[args.sub](args)
    if args.cmd == "trace":
        return {
            "check": cmd_trace_check,
            "update": cmd_trace_update,
            "selftest": cmd_trace_selftest,
        }[args.sub](args)
    if args.cmd == "power":
        return cmd_power(args)
    if args.cmd == "ab":
        return {
            "plan": cmd_ab_plan,
            "dry-run": cmd_ab_run,
            "live": cmd_ab_run,
            "replay": cmd_ab_run,
        }[args.sub](args)
    if args.cmd == "compliance":
        return cmd_compliance(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "all":
        return cmd_all(args)
    if args.cmd == "verdict":
        return cmd_verdict(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
