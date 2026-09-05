"""c2_benefit_probe — 最快速度量化「本次对话所有 Path A 修改」带来的收益。

在**同一真录会话**上，逐配置驱动 `project_for_model`，测量：
  - C2 边界推进次数（= 历史前缀改写次数；越少越好）
  - 单次改写体量（字符）
  - 前缀命中率代理（STABLE_APPEND 占比）
  - 尾溢出（投影 token 是否越 l_hard_send）

配置：
  frozen        公式全关（= 旧基线，未做任何 Path A 修改）
  adaptive      公式开 + 窗口自适应压力（不设 env pressure，走 (l_hard_send−reserve−tail)/window）
  p078         公式开 + pressure=0.78（之前实测的最优拐点附近）
  p090         公式开 + pressure=0.90（晚压、尽量保上下文）

零 LLM、零费用；不改生产设置（env 经 XEYO_C2_FORMULA_OVERRIDE 一次性注入，跑完还原）。
用法（在 python/ 下）:
  py -3.11 -m scripts.c2_benefit_probe [session_id] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SESSION = "sess_real_200turn_c2"
# 配置名 -> (是否开公式, env pressure 覆盖或 None)
CONFIGS: list[tuple[str, bool, float | None]] = [
    ("frozen", False, None),
    ("adaptive", True, None),
    ("p078", True, 0.78),
    ("p090", True, 0.90),
]


def _load(session_id: str) -> list[dict]:
    from session.hydrate import message_from_row
    from session.record_transcript import load_transcript, transcript_read_paths
    from session.persistence import transcript_path

    rows: list[dict] = []
    try:
        for p in transcript_read_paths(transcript_path(session_id)):
            rows.extend(load_transcript(p))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] transcript read: {exc}")
    out: list[dict] = []
    for r in rows:
        m = message_from_row(r)
        if m is not None:
            out.append(m.__dict__)
    return out


def _norm(obj) -> object:
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_norm(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def _first_divergence(a: list[dict], b: list[dict]) -> tuple[int | None, str]:
    for i in range(min(len(a), len(b))):
        if _norm(a[i]) != _norm(b[i]):
            return i, "REWRITE"
    return None, "STABLE_APPEND"


def _region_chars(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict):
                    continue
                t = b.get("content") or b.get("text") or b.get("input")
                if isinstance(t, str):
                    n += len(t)
    return n


def _run_config(session_id: str, messages: list[dict], *, formula_on: bool, pressure: float | None) -> dict:
    import memory.runtime as rt
    from memory.working import WorkingSnapshot, hydrate

    # 公式开则注入 override；关则清空（= 冻结基线）
    if formula_on:
        os.environ["XEYO_C2_FORMULA_OVERRIDE"] = (
            "XEYO_C2_PRESSURE_FORMULA:1,XEYO_C2_GAIN_FORMULA:1,XEYO_C2_EXTEND_FORMULA:1"
        )
    else:
        os.environ.pop("XEYO_C2_FORMULA_OVERRIDE", None)
    if pressure is not None:
        os.environ["XEYO_C2_PRESSURE_RATIO"] = str(pressure)
    else:
        os.environ.pop("XEYO_C2_PRESSURE_RATIO", None)

    rt.l5_mode = lambda: "v61"
    working = hydrate(session_id)
    if not working.session_id:
        working = WorkingSnapshot(session_id=session_id)

    from memory.runtime import project_for_model
    from memory.simulator.params import load_params

    p = load_params()
    l_hard_send = int(p.l_hard_send)

    call_idxs = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    prev_out: list[dict] | None = None
    advances = 0
    rewrite_calls = 0
    append_calls = 0
    rewrite_chars = 0
    tail_overflow_calls = 0
    last_cursor = 0

    for idx in call_idxs:
        before = int(getattr(working, "compact_cursor", 0) or 0)
        try:
            out = project_for_model(
                messages[:idx], working, remaining_turns=8, include_memory_index=False
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{pressure}] call {idx} err {exc}")
            continue
        after = int(getattr(working, "compact_cursor", 0) or 0)
        if after != before:
            advances += 1
            rewrite_chars += _region_chars(messages[before:after])
        if prev_out is not None:
            _, d = _first_divergence(prev_out, out)
            if d == "REWRITE":
                rewrite_calls += 1
            else:
                append_calls += 1
        prev_out = out
        try:
            proj_tok = _region_chars(out) / 4.0
            if proj_tok > l_hard_send:
                tail_overflow_calls += 1
        except Exception:
            pass

    os.environ.pop("XEYO_C2_FORMULA_OVERRIDE", None)
    os.environ.pop("XEYO_C2_PRESSURE_RATIO", None)

    total = len(call_idxs)
    stable = append_calls
    return {
        "advances": advances,
        "rewrite_calls": rewrite_calls,
        "avg_rewrite_chars": (rewrite_chars / advances) if advances else 0.0,
        "hit_proxy": (stable / total) if total else 0.0,
        "tail_overflow_calls": tail_overflow_calls,
        "calls": total,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session_id", nargs="?", default=DEFAULT_SESSION)
    ap.add_argument("--config", nargs="*", default=None,
                    help="只跑指定配置：frozen adaptive p078 p090")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    messages = _load(args.session_id)
    print(f"# 收益对比 session={args.session_id}  messages={len(messages)}\n")
    print(f"{'配置':<10} {'C2边界推进':>8} {'改写调用':>7} {'单次改写均':>10} {'命中率代理':>9} {'尾溢出':>6}")

    selected = args.config if args.config else [c[0] for c in CONFIGS]
    rows: list[dict] = []
    for name, formula_on, pressure in CONFIGS:
        if name not in selected:
            continue
        r = _run_config(args.session_id, messages, formula_on=formula_on, pressure=pressure)
        r["config"] = name
        r["pressure"] = pressure
        rows.append(r)
        print(
            f"{name:<10} {r['advances']:>8} {r['rewrite_calls']:>7} {r['avg_rewrite_chars']:>10.0f}c "
            f"{r['hit_proxy']*100:>8.1f}% {r['tail_overflow_calls']:>6}", flush=True
        )

    # 与 frozen 基线对比收益
    frozen = next((r for r in rows if r["config"] == "frozen"), None)
    if frozen:
        print("\n# 相对冻结基线的收益（改写越少越好）")
        for r in rows:
            if r["config"] == "frozen":
                continue
            d_adv = frozen["advances"] - r["advances"]
            d_hit = (r["hit_proxy"] - frozen["hit_proxy"]) * 100
            print(
                f"  {r['config']:<10} 改写 {frozen['advances']}→{r['advances']} ({d_adv:+d}, "
                f"{d_adv/max(1,frozen['advances'])*100:+.1f}%)  命中率 {frozen['hit_proxy']*100:.1f}%→{r['hit_proxy']*100:.1f}% ({d_hit:+.1f}pp)"
            )

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[json] 写入 {args.json}（{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
