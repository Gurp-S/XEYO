"""ab —— L2 配对 A/B 跑器 + 统计裁决。

设计口径：
  - 同一份任务电池在 A (默认) 和 B (variant) 上各跑 repeats 次；
  - 配对分析：每个 (task, repeat) 是一对 (A 通过?, B 通过?)；
  - 二元结果走 McNemar + Wilson，连续量（成本/字符/耗时）走配对 bootstrap；
  - 跑前**必须**先报价 + 预算门（见 budget.py）；
  - 干跑默认（fake 模型），实跑必须显式 --live 且 --budget。

variant 的表达：用环境变量叠加。`--variant-env KEY=VAL`（可多次）。对 T_now
块消融的常见用法： `--variant-env XEYO_T_NOW_SKIP=wrap_up`。更激进的代码
层 variant 建议在两个独立 checkout 间切，不在 harness 里做（避免动工作树）。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from contextlib import aclosing, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import budget, stats

DEFAULT_BATTERY = Path(__file__).resolve().parent.parent / "task_battery.json"


@dataclass
class CaseResult:
    task_id: str
    arm: str
    repeat: int
    passed: bool
    reply_chars: int
    wall_ms: int
    error: str = ""
    cost_cny: float = 0.0
    out_tokens: int = 0
    miss_tokens: int = 0
    hit_tokens: int = 0


@dataclass
class ABReport:
    started_at: float
    finished_at: float
    live: bool
    variant_env: dict[str, str]
    repeats: int
    n_tasks: int
    cases: list[CaseResult] = field(default_factory=list)
    price_preset: str = ""
    calibration: str = ""
    estimated_total_cny: float = 0.0
    actual_total_cny: float = 0.0
    cost_per_task_run_cny: float = 0.0
    statistical: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S%z", time.localtime(self.started_at)
        )
        d["finished_at_iso"] = time.strftime(
            "%Y-%m-%dT%H:%M:%S%z", time.localtime(self.finished_at)
        )
        return d


# --------------------------------------------------------------------------
# 任务 / 校验
# --------------------------------------------------------------------------


def load_battery(path: Path = DEFAULT_BATTERY) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["cases"]


def _check(case: dict[str, Any], reply: str, cwd: Path) -> tuple[bool, str]:
    chk = case.get("check") or {}
    if "contains_any" in chk:
        return any(s in reply for s in chk["contains_any"]), "contains"
    if "file_contains" in chk:
        fname, needle = chk["file_contains"]
        f = cwd / fname
        if not f.exists():
            return False, "file missing"
        return needle in f.read_text(encoding="utf-8", errors="ignore"), "file"
    return True, "no-check"


def _extract_usage(ev: Any) -> dict[str, int]:
    """从引擎事件里抠出 token 用量（多种可能位置，宽容读取）。"""
    usage = getattr(ev, "usage", None)
    if isinstance(usage, dict):
        return {
            "hit": int(usage.get("cache_hit", usage.get("input_hit", 0)) or 0),
            "miss": int(usage.get("input_miss", usage.get("input", 0)) or 0),
            "out": int(usage.get("output", 0) or 0),
        }
    return {}


# --------------------------------------------------------------------------
# 单次跑（复用 evals/block_ablation 的契约）
# --------------------------------------------------------------------------


async def _run_case(
    case: dict[str, Any],
    *,
    arm: str,
    repeat: int,
    live: bool,
    api_key: str,
    base_url: str,
    model: str,
    variant_env: dict[str, str],
) -> CaseResult:
    from engine.query_engine import build_default_engine

    cwd = Path(tempfile.mkdtemp(prefix=f"xeyo_ab_{arm}_"))
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "session_id": f"ab_{arm}_{case['id']}_{repeat}_{os.getpid()}",
    }
    if live:
        kwargs.update(
            api_key=api_key,
            provider="openai",
            model=model or "deepseek-chat",
            base_url=base_url or "https://api.deepseek.com/v1",
        )
    else:
        kwargs["model_backend"] = "fake"

    # variant_env 只施加给 arm B；arm A 拿原始环境
    saved: dict[str, str] = {}
    if arm == "B":
        for k, v in variant_env.items():
            saved[k] = os.environ.get(k, "")
            os.environ[k] = v

    text_parts: list[str] = []
    cost = 0.0
    hit = miss = outt = 0
    err = ""
    t0 = time.time()
    try:
        engine = build_default_engine(**kwargs)
        async with aclosing(engine.submit(case["task"])) as stream:
            async for ev in stream:
                et = getattr(ev, "type", "") or getattr(ev, "kind", "")
                if et in ("assistant_delta", "text_delta"):
                    text_parts.append(getattr(ev, "text", "") or "")
                elif type(ev).__name__ == "ResultEvent":
                    if getattr(ev, "subtype", "") != "success":
                        err = str(getattr(ev, "subtype", ""))
                    if not text_parts and getattr(ev, "result", ""):
                        text_parts.append(ev.result)
                u = _extract_usage(ev)
                if u:
                    hit += u["hit"]
                    miss += u["miss"]
                    outt += u["out"]
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    finally:
        if arm == "B":
            for k, prev in saved.items():
                if prev == "":
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = prev

    wall_ms = int((time.time() - t0) * 1000)
    reply = "".join(text_parts)
    passed, _how = _check(case, reply, cwd)
    return CaseResult(
        task_id=case["id"],
        arm=arm,
        repeat=repeat,
        passed=passed,
        reply_chars=len(reply),
        wall_ms=wall_ms,
        error=err[:200],
        cost_cny=cost,
        out_tokens=outt,
        miss_tokens=miss,
        hit_tokens=hit,
    )


# --------------------------------------------------------------------------
# 顶层跑
# --------------------------------------------------------------------------


async def _run_all(
    cases: list[dict[str, Any]],
    *,
    repeats: int,
    variant_env: dict[str, str],
    live: bool,
    api_key: str,
    base_url: str,
    model: str,
) -> list[CaseResult]:
    rows: list[CaseResult] = []
    for repeat in range(repeats):
        for case in cases:
            for arm in ("A", "B"):
                row = await _run_case(
                    case,
                    arm=arm,
                    repeat=repeat,
                    live=live,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    variant_env=variant_env,
                )
                rows.append(row)
                tag = "PASS" if row.passed else "FAIL"
                print(
                    f"  [r{repeat}] {arm} {case['id']}: {tag}"
                    f" ({row.reply_chars}ch, {row.wall_ms}ms"
                    f"{' ERR:' + row.error if row.error else ''})"
                )
    return rows


def _summarize(rows: list[CaseResult]) -> dict[str, Any]:
    """配对 + 连续量 双口径裁决。"""
    by_pair: dict[tuple[str, int], dict[str, CaseResult]] = {}
    for r in rows:
        by_pair.setdefault((r.task_id, r.repeat), {})[r.arm] = r
    pairs: list[tuple[bool, bool]] = []
    char_deltas: list[float] = []
    wall_deltas: list[float] = []
    for (tid, rep), arms in by_pair.items():
        a = arms.get("A")
        b = arms.get("B")
        if a is None or b is None:
            continue
        pairs.append((a.passed, b.passed))
        char_deltas.append(b.reply_chars - a.reply_chars)
        wall_deltas.append(b.wall_ms - a.wall_ms)
    pair_stats = stats.summarize_pairs(pairs) if pairs else {"verdict": "no_pairs"}
    char_ci = stats.paired_bootstrap_ci(char_deltas, seed=20260910) if char_deltas else (0, 0, 0)
    wall_ci = stats.paired_bootstrap_ci(wall_deltas, seed=20260910) if wall_deltas else (0, 0, 0)
    return {
        "n_pairs": len(pairs),
        "pass_pair": pair_stats,
        "char_delta_b_minus_a": {
            "point": char_ci[1],
            "ci_lo": char_ci[0],
            "ci_hi": char_ci[2],
            "meaning": "B 比 A 多 / 少多少个字符（正=B 更啰嗦）",
        },
        "wall_ms_delta_b_minus_a": {
            "point": wall_ci[1],
            "ci_lo": wall_ci[0],
            "ci_hi": wall_ci[2],
            "meaning": "B 比 A 慢 / 快多少毫秒（正=B 更慢）",
        },
    }


def run(
    *,
    cases: list[dict[str, Any]] | None = None,
    repeats: int = 1,
    variant_env: dict[str, str] | None = None,
    live: bool = False,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    budget_cny: float | None = None,
    price: budget.Price | None = None,
    calibration: dict[str, Any] | None = None,
    plan_only: bool = False,
) -> ABReport:
    """主入口：跑前报价 → 预算门 → 实跑 → 统计 → 报告。"""
    cases = cases or load_battery()
    variant_env = dict(variant_env or {})
    repeats = max(1, int(repeats))
    price = price or budget.preset()

    plan = budget.plan(
        n_tasks=len(cases), repeats=repeats, arms=2, price=price, calibration=calibration
    )
    gate = budget.check_budget(plan, budget_cny)
    if live and not gate["allowed"]:
        raise budget.BudgetExceeded(gate["reason"])

    report = ABReport(
        started_at=time.time(),
        finished_at=time.time(),
        live=live,
        variant_env=variant_env,
        repeats=repeats,
        n_tasks=len(cases),
        price_preset=price.source,
        calibration=plan["calibration"],
        estimated_total_cny=plan["estimated_total_cny"],
        cost_per_task_run_cny=plan["cost_per_task_run_cny"],
        notes="干跑" if not live else "实跑",
    )

    if plan_only:
        return report

    rows = asyncio.run(
        _run_all(
            cases,
            repeats=repeats,
            variant_env=variant_env,
            live=live,
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=base_url,
            model=model,
        )
    )
    report.cases = rows
    report.actual_total_cny = sum(r.cost_cny for r in rows)
    report.finished_at = time.time()
    report.statistical = _summarize(rows)
    return report


def write_report(report: ABReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(report.started_at))
    json_path = out_dir / f"ab-{ts}.json"
    md_path = out_dir / f"ab-{ts}.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return json_path, md_path


def render_markdown(rep: ABReport) -> str:
    s = rep.statistical.get("pass_pair", {})
    p = rep.statistical.get("char_delta_b_minus_a", {})
    w = rep.statistical.get("wall_ms_delta_b_minus_a", {})
    lines = [
        f"# A/B 报告（{rep.notes}）",
        "",
        f"- 任务数 **{rep.n_tasks}** · 重复 **{rep.repeats}** · variant 环境: `{rep.variant_env or '∅'}`",
        f"- 价表：{rep.price_preset}（标定：{rep.calibration}）",
        f"- 估算 ¥{rep.estimated_total_cny:.2f} · 实算 ¥{rep.actual_total_cny:.2f}",
        f"- 配对样本 **{s.get('n_pairs', 0)}** · 通过率 A {s.get('pass_rate_a', 0):.0%} / B {s.get('pass_rate_b', 0):.0%}",
        f"- 差值 Δ {s.get('delta', 0):+.1%} · p={s.get('p_value', 1):.4f} · 裁决 **{s.get('verdict', '?')}**",
        f"- 不一致率 ψ {s.get('discordant_rate', 0):.1%} · 本次 MDE {s.get('mde', 0):.1%}",
        f"- 字符差（中位 / CI）：{p.get('point', 0):+.0f}  [{p.get('ci_lo', 0):+.0f}, {p.get('ci_hi', 0):+.0f}]",
        f"- 耗时差（ms，中位 / CI）：{w.get('point', 0):+.0f}  [{w.get('ci_lo', 0):+.0f}, {w.get('ci_hi', 0):+.0f}]",
        "",
        s.get("resolution_note", ""),
        "",
        "## 决议",
        "",
        f"> {s.get('verdict', '?')}",
    ]
    return "\n".join(lines) + "\n"
