"""c2_ab_1m — 1M 窗口下的压力单选优：0.85 / 0.92 / 0.95 哪个最好。

注意：XEYO 的 `window_tokens` 不能靠 env 覆盖（`load_params` 只读 overlay），
所以本脚本 monkeypatch `memory.simulator.params.load_params` 返回 1M 窗口的 Params，
从而让 `project_for_model` / `decide` 都按 1M 窗口跑。**不改生产 overlay，跑完即还原**。

测量项同 c2_ab_calibrate：C2 边界推进 / 改写调用 / 单次改写体量 / 前缀命中率代理 / 尾溢出。

用法（在 python/ 下）:
  py -3.11 -m scripts.c2_ab_1m [session_id ...]  --pressure 0.85 0.92 0.95
  # 默认会话 sess_real_200turn_c2，默认压力 0.85/0.92/0.95
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SESSIONS = ("sess_real_200turn_c2",)
DEFAULT_PRESSURE = (0.85, 0.92, 0.95)
ONEM = 1_000_000


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


def _setup_1m() -> None:
    """monkeypatch load_params：返回 window_tokens=1M 的 Params（带 overlay 的其它字段）。

    不改磁盘 overlay；用 replace 复制默认再覆写 window_tokens。
    """
    import memory.simulator.params as P

    _orig_load = P.load_params  # 先捕获原始，避免递归

    def _lp(path=None, **overrides):
        base = _orig_load(path)
        kw = {"window_tokens": ONEM}
        kw.update(overrides)
        return replace(base, **kw)

    P.load_params = _lp
    # 其它模块可能已按模块名 import 了 load_params 别名，也一并 patch 常见入口
    import memory.runtime as rt
    import memory.simulator.cache_model as cm
    import memory.simulator.decision as dec
    import memory.simulator.projection as proj
    for mod in (rt, cm, dec, proj):
        if hasattr(mod, "load_params"):
            try:
                setattr(mod, "load_params", P.load_params)
            except Exception:  # noqa: BLE001
                pass


def _run_combo(session_id: str, *, pressure: float, save: float, tail: int) -> dict:
    import memory.runtime as rt
    from memory.working import WorkingSnapshot, hydrate

    messages = _load(session_id)
    os.environ["XEYO_C2_FORMULA_OVERRIDE"] = (
        "XEYO_C2_PRESSURE_FORMULA:1,XEYO_C2_GAIN_FORMULA:1,XEYO_C2_EXTEND_FORMULA:1"
    )
    os.environ["XEYO_C2_SAVE_RATIO"] = str(save)
    os.environ["XEYO_C2_PRESSURE_RATIO"] = str(pressure)
    os.environ["XEYO_C2_TAIL_BUDGET_TOKENS"] = str(tail)
    # 1M 窗口下保留轮数多押几个，避免尾预算过小（每轮均 token × 轮数）
    os.environ["XEYO_C2_RETAIN_ROUNDS"] = "3"

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
            print(f"[combo p={pressure}] call {idx} err {exc}")
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

    for k in ("XEYO_C2_FORMULA_OVERRIDE", "XEYO_C2_SAVE_RATIO", "XEYO_C2_PRESSURE_RATIO",
              "XEYO_C2_TAIL_BUDGET_TOKENS", "XEYO_C2_RETAIN_ROUNDS"):
        os.environ.pop(k, None)

    total = len(call_idxs)
    stable = append_calls
    return {
        "pressure": pressure,
        "save": save,
        "tail": tail,
        "window": ONEM,
        "calls": total,
        "advances": advances,
        "rewrite_calls": rewrite_calls,
        "rewrite_chars": rewrite_chars,
        "tail_overflow_calls": tail_overflow_calls,
        "hit_proxy": (stable / total) if total else 0.0,
        "avg_rewrite_chars": (rewrite_chars / advances) if advances else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sessions", nargs="*", default=list(DEFAULT_SESSIONS))
    ap.add_argument("--pressure", type=float, nargs="*", default=None)
    ap.add_argument("--save", type=float, default=0.30)
    ap.add_argument("--tail", type=int, default=12000)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    pressures = tuple(args.pressure) if args.pressure else DEFAULT_PRESSURE
    print(f"# 1M 窗口压力单扫 pressure{sorted(set(pressures))} save={args.save} tail={args.tail}")

    _setup_1m()
    rows: list[dict] = []
    for sid in args.sessions:
        messages = _load(sid)
        print(f"\n## session {sid}  messages={len(messages)}")
        if not messages:
            continue
        for pressure in sorted(set(pressures)):
            r = _run_combo(sid, pressure=pressure, save=args.save, tail=args.tail)
            r["session"] = sid
            rows.append(r)
            flag = "  <== OA overflow" if r["tail_overflow_calls"] else ""
            print(
                f"  p={pressure:.2f}  adv={r['advances']:>3} rew={r['rewrite_calls']:>3} "
                f"avgRW={r['avg_rewrite_chars']:>7.0f}c hit={r['hit_proxy']*100:.1f}% "
                f"ovf={r['tail_overflow_calls']}{flag}",
                flush=True,
            )

    no_ovf = [r for r in rows if r["tail_overflow_calls"] == 0]
    pool = no_ovf or rows
    if pool:
        best = sorted(pool, key=lambda r: (r["advances"], -r["hit_proxy"], r["rewrite_chars"]))[0]
        print("\n# 1M 最优压力")
        print(f"  session={best['session']} pressure={best['pressure']}")
        print(
            f"  C2 边界推进={best['advances']} 改写调用={best['rewrite_calls']} "
            f"单次改写均={best['avg_rewrite_chars']:.0f}c 前缀命中率代理={best['hit_proxy']*100:.1f}% "
            f"尾溢出={best['tail_overflow_calls']}"
        )
    else:
        print("\n# 无组合（无数据）")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[json] 写入 {args.json}（{len(rows)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
