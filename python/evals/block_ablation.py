"""T_now 块消融 runner：逐块开关 × 任务电池 → 成功率/漂移/成本矩阵。

用法（在 python/ 下，需真实 key 才有意义）:
  py evals/block_ablation.py --baseline                    # 只跑基线（全块在）
  py evals/block_ablation.py --blocks wrap_up,runtime_budget
  py evals/block_ablation.py --blocks wrap_up --smoke      # fake model 验管道

机制：对每个待测块，设 XEYO_T_NOW_SKIP=<块名>（该块缺席）跑一遍任务电池，
与基线（SKIP 为空）对比：
- pass_rate 差：缺席是否伤任务完成（跌 → 该块有真实收益）
- drift 命中：drift_judge 正则层三维（L404/L475/L543）
- 回复长度：风格/收敛影响
产出矩阵打印 + --out 落 JSON。结论查表，不靠感觉——这是硬准入「有数据
证明收益」的数据来源。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.drift_judge import regex_judge
from prompt.pre_llm_inject import T_NOW_BLOCK_REGISTRY, _SKIP_ENV
from prompt.t_now_strategy import set_t_now_strategy


def _check(case: dict, reply: str, cwd: Path) -> tuple[bool, str]:
    chk = case.get("check", {})
    if "contains_any" in chk:
        hit = any(s in reply for s in chk["contains_any"])
        return hit, "contains"
    if "file_contains" in chk:
        fname, needle = chk["file_contains"]
        f = cwd / fname
        if not f.exists():
            return False, "file missing"
        return needle in f.read_text(encoding="utf-8", errors="ignore"), "file"
    return True, "no-check"


async def _run_case(case: dict, *, api_key: str, base_url: str, model: str,
                    smoke: bool) -> dict:
    from contextlib import aclosing

    from engine.query_engine import build_default_engine

    cwd = Path(tempfile.mkdtemp(prefix="xeyo_ablation_"))
    kwargs: dict = {
        "cwd": str(cwd),
        "session_id": f"ablation_{case['id']}_{os.getpid()}",
    }
    if smoke:
        kwargs["model_backend"] = "fake"  # build_default_engine 内建 FakeModelClient
    else:
        kwargs.update(
            api_key=api_key,
            provider="openai",
            model=model or "deepseek-chat",
            base_url=base_url or "https://api.deepseek.com/v1",
        )
    engine = build_default_engine(**kwargs)
    text_parts: list[str] = []
    error = ""
    try:
        async with aclosing(engine.submit(case["task"])) as stream:
            async for ev in stream:
                # 引擎事件用 .type（assistant_delta），模型 chunk 用 .kind（text_delta）
                etype = getattr(ev, "type", "") or getattr(ev, "kind", "")
                if etype in ("assistant_delta", "text_delta"):
                    text_parts.append(getattr(ev, "text", ""))
                elif type(ev).__name__ == "ResultEvent":
                    if getattr(ev, "subtype", "") != "success":
                        error = str(getattr(ev, "subtype", ""))
                    if not text_parts and getattr(ev, "result", ""):
                        text_parts.append(ev.result)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    reply = "".join(text_parts)
    passed, how = _check(case, reply, cwd)
    drift = regex_judge(case["task"], reply)
    return {
        "id": case["id"],
        "passed": passed,
        "check": how,
        "reply_chars": len(reply),
        "drift_l404": drift.l404,
        "drift_l475": drift.l475,
        "drift_l543": drift.l543,
        "error": error[:200],
    }


async def _run_battery(cases: list[dict], **kw) -> list[dict]:
    results = []
    for case in cases:
        r = await _run_case(case, **kw)
        print(f"    {case['id']}: {'PASS' if r['passed'] else 'FAIL'}"
              f" ({r['reply_chars']}ch, drift={int(r['drift_l404'])+int(r['drift_l475'])+bool(r['drift_l543'])})"
              f"{' ERR:' + r['error'] if r['error'] else ''}")
        results.append(r)
    return results


def _summary(label: str, results: list[dict]) -> dict:
    n = len(results) or 1
    drift_hits = sum(
        int(r["drift_l404"]) + int(r["drift_l475"]) + bool(r["drift_l543"])
        for r in results
    )
    return {
        "label": label,
        "pass_rate": sum(r["passed"] for r in results) / n,
        "drift_hits": drift_hits,
        "avg_reply_chars": sum(r["reply_chars"] for r in results) / n,
        "errors": sum(1 for r in results if r["error"]),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true", help="只跑基线")
    parser.add_argument("--blocks", default="", help="逗号分隔的登记块名")
    parser.add_argument("--cases", default=str(Path(__file__).parent / "task_battery.json"))
    parser.add_argument("--out", default="")
    parser.add_argument("--smoke", action="store_true", help="fake model 验管道")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--strategy",
        default="system_channel",
        choices=["system_channel", "env_channel", "legacy", "skip"],
        help="T_now 声道。默认 system_channel（生产默认）。"
             "注意：本台原先硬编码 env_channel（伪对档，2026-09-15 已废），"
             "在该声道下测出的块间差值是「污染底座上的差值」，不可与生产结论混用；"
             "传 skip 即为「整条管道关闭」的全管道消融。",
    )
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="每个配置重复次数。默认 1——但换 harness 噪声 sd≈5pp、同配置重跑噪声 4-5pp，"
             "单次差 1 题不足以判定；要下结论用 --repeat 3。",
    )
    args = parser.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    blocks = (
        [b.strip() for b in args.blocks.split(",") if b.strip()]
        if not args.baseline
        else []
    )
    for b in blocks:
        if b not in T_NOW_BLOCK_REGISTRY:
            print(f"❌ 块 {b} 不在登记表——先登记再消融")
            sys.exit(2)

    labels: list[str | None] = [None]  # None = 基线
    if not args.baseline:
        labels.extend(blocks)

    # 声道必须显式记录：历史上本台硬编码 env_channel，而那是已被判废的伪对档
    # （模型把注入对当成自己的工具调用，实测单会话 70-89 次）。在污染底座上测
    # 出的块间差值不能代表生产，故打印出来防止跨声道误比。
    set_t_now_strategy(args.strategy)
    repeat = max(1, int(args.repeat))
    print(f"== 声道 strategy={args.strategy}  repeat={repeat}"
          + ("（skip = 整条管道关闭）" if args.strategy == "skip" else ""))
    kw = dict(
        api_key=args.api_key
        or os.environ.get("XEYO_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=args.base_url,
        model=args.model,
        smoke=args.smoke,
    )
    summaries = []
    for label in labels:
        os.environ[_SKIP_ENV] = label or ""
        print(f"== {'基线（全块在）' if label is None else f'跳过 {label}'}")
        runs = [asyncio.run(_run_battery(cases, **kw)) for _ in range(repeat)]
        merged: list[dict] = [r for run in runs for r in run]
        summaries.append(_summary(label or "baseline", merged))
    os.environ.pop(_SKIP_ENV, None)

    print("\n===== 消融矩阵 =====")
    print(f"声道={args.strategy}  repeat={repeat}")
    print(f"{'配置':<24} pass率   drift  平均回复ch  错误")
    for s in summaries:
        print(f"{s['label']:<24} {s['pass_rate']:<7.0%} {s['drift_hits']:<6} "
              f"{s['avg_reply_chars']:<10.0f} {s['errors']}")

    if args.out:
        Path(args.out).write_text(
            json.dumps({"strategy": args.strategy, "repeat": repeat, "arms": summaries},
                       ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写 {args.out}")

    # 三向判定（原实现把「缺席涨分」读成「无伤」，等于只给块发准入证、不发死亡证明）。
    # 阈值：单题粒度下 1 题的差就下结论会被噪声吃掉（同配置重跑噪声 4-5pp），
    # 故 <repeat> 次下要求差值 ≥1 题当量，且提示噪声未消。
    if not args.baseline and summaries:
        base = summaries[0]
        per = len(cases) * repeat
        for s in summaries[1:]:
            delta = s["pass_rate"] - base["pass_rate"]
            if delta < 0:
                verdict = "★ 缺席跌分 → 该块有真实收益（保留）"
            elif delta > 0:
                verdict = "★★ 缺席涨分 → 该块疑似净负（在场有害，考虑退役）"
            else:
                verdict = "缺席无变化 → 无明显收益（可退役，或换更有判别力的用例）"
            print(f"[{s['label']}] 相对基线 pass 差 {delta:+.0%}"
                  f"（≈{delta * per:+.1f} 题 / 共 {per}） → {verdict}")
            if repeat == 1:
                print("      ⚠ repeat=1：差值小于 1 题当量时不可判定，用 --repeat 3 复现。")


if __name__ == "__main__":
    main()
