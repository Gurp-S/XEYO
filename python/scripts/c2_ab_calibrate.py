"""c2_ab_calibrate — Path A A/B 定参脚本：网格扫描 pressure × save × tail，用探针测量并选优。

零 LLM、零费用：重复驱动 ``project_for_model``（走 `XEYO_C2_*` 公式开关 + env 覆盖），
对比各组合的 C2 行为与「前缀稳定性」代理命中率。

测量项（对每条真录会话）：
  - C2 边界推进次数（= 历史前缀改写次数；越少越好）
  - 单次改写体量（字符；压缩动作的 region 大小）
  - 尾部是否越过 l_hard_send（窗口硬顶；必须不溢出）
  - 前缀稳定性代理命中率 = 保持 STABLE_APPEND 的调用占比（越高越好）

网格（默认）：
  pressure {0.62, 0.70, 0.78, 0.82, 0.90} × save {0.30, 0.40} × tail {12k, 24k, 32k}
  tail 为「保尾预算 token」（XEYO_C2_TAIL_BUDGET_TOKENS / 每轮均 token × 轮数换算）。

并行（--workers N，默认按 CPU 核数）：每个组合 = 独立进程（重建会话 + 驱动 decide），
互不共享状态，天然可并行，加速比 ≈ min(workers, 组合数)。

用法（在 python/ 下）:
  py -3.11 -m scripts.c2_ab_calibrate sess_real_200turn_c2 [session2 ...]
  py -3.11 -m scripts.c2_ab_calibrate sess_real_200turn_c2 --workers 8
  # 只扫特定压力（你给的 0.62/0.70/0.78/0.82/0.90）
  py -3.11 -m scripts.c2_ab_calibrate sess_real_200turn_c2 --pressure 0.62 0.70 0.78 0.82 0.90 --workers 8
  # 精扫单组合
  py -3.11 -m scripts.c2_ab_calibrate sess_real_200turn_c2 --pressure 0.62 --save 0.40 --tail 24000
  # 落 JSON
  ... --json out.json

判定：改写最少 + 尾不溢出 + 前缀命中率最高（并列时取 C2 触发次数适中的组合）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GRID_PRESSURE = (0.62, 0.70, 0.78, 0.82, 0.90)
GRID_SAVE = (0.30, 0.40)
GRID_TAIL = (12_000, 24_000, 32_000)


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


def _run_combo(session_id: str, *, pressure: float, save: float, tail: int, snapshot_env: dict) -> dict:
    """单组合：把公式开关 + env 覆盖写进**本进程**环境，驱动整会话，返回测量汇总。

    每个组合在独立进程里执行（进程内 env / working snapshot 各自隔离），因此并行安全。
    """
    import memory.runtime as rt
    from memory.working import WorkingSnapshot, hydrate

    messages = _load(session_id)

    # 设置环境：开启三个公式开关（一次性 override，不改生产设置）+ 网格覆盖。
    for k, v in snapshot_env.items():
        os.environ[k] = v
    os.environ["XEYO_C2_FORMULA_OVERRIDE"] = (
        "XEYO_C2_PRESSURE_FORMULA:1,XEYO_C2_GAIN_FORMULA:1,XEYO_C2_EXTEND_FORMULA:1"
    )
    os.environ["XEYO_C2_SAVE_RATIO"] = str(save)
    os.environ["XEYO_C2_PRESSURE_RATIO"] = str(pressure)
    os.environ["XEYO_C2_TAIL_BUDGET_TOKENS"] = str(tail)

    # v61 decide 每轮（与 runtime_probe 一致）
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
            print(f"[combo p={pressure} s={save} t={tail}] call {idx} err {exc}")
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
        # 尾部越硬顶：用「实际送模型投影」的 token 长度判定（不是原始消息池）。
        try:
            proj_tok = _region_chars(out) / 4.0
            if proj_tok > l_hard_send:
                tail_overflow_calls += 1
        except Exception:
            pass

    # 还原环境（组合在独立进程，还原只为同进程复用时干净，不污染其他组合）
    for k in ("XEYO_C2_FORMULA_OVERRIDE", "XEYO_C2_SAVE_RATIO", "XEYO_C2_PRESSURE_RATIO",
              "XEYO_C2_TAIL_BUDGET_TOKENS"):
        os.environ.pop(k, None)
    for k in snapshot_env:
        os.environ.pop(k, None)

    total = len(call_idxs)
    stable = append_calls
    return {
        "pressure": pressure,
        "save": save,
        "tail": tail,
        "calls": total,
        "advances": advances,
        "rewrite_calls": rewrite_calls,
        "rewrite_chars": rewrite_chars,
        "tail_overflow_calls": tail_overflow_calls,
        "stable_append": stable,
        "hit_proxy": (stable / total) if total else 0.0,
        "avg_rewrite_chars": (rewrite_chars / advances) if advances else 0.0,
    }


def _worker(args: dict) -> dict:
    """ProcessPoolExecutor 顶层 worker（可 pickle）。"""
    sid = args.pop("_session")
    r = _run_combo(sid, **args)
    r["session"] = sid
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sessions", nargs="+", help="真录会话 id（如 sess_real_200turn_c2）")
    ap.add_argument("--pressure", type=float, nargs="*", default=None)
    ap.add_argument("--save", type=float, nargs="*", default=None)
    ap.add_argument("--tail", type=int, nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=1, help="并行进程数。注意：每组合是单核串行 decide 计算，"
                                                            "进程池并行会抢占核数、无单组合加速；"
                                                            "核数充足(&>=8)才值得开，否则默认 1（串行最稳）")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    pressures = tuple(args.pressure) if args.pressure else GRID_PRESSURE
    saves = tuple(args.save) if args.save else GRID_SAVE
    tails = tuple(args.tail) if args.tail else GRID_TAIL
    p_set = sorted(set(pressures))
    s_set = sorted(set(saves))
    t_set = sorted(set(tails))
    print(f"# 网格 pressure{p_set} × save{s_set} × tail{t_set}")

    # 组合任务列表（每个任务是独立进程）
    job_args: list[dict] = []
    for sid in args.sessions:
        for pressure in p_set:
            for save in s_set:
                for tail in t_set:
                    job_args.append(
                        {
                            "_session": sid,
                            "pressure": pressure,
                            "save": save,
                            "tail": tail,
                            "snapshot_env": {},
                        }
                    )

    workers = args.workers if args.workers and args.workers > 0 else 1
    workers = max(1, min(workers, len(job_args)))
    print(f"# 并行: {workers} workers / {len(job_args)} 组合")

    rows: list[dict] = []
    if workers == 1 or len(job_args) == 1:
        # 串行：每组合完成即打印（可见进度，不卡）
        for idx, ja in enumerate(job_args, 1):
            r = _worker(ja)
            rows.append(r)
            flag = "  <== OA overflow" if r["tail_overflow_calls"] else ""
            print(
                f"  [{idx}/{len(job_args)}] p={r['pressure']:.2f} s={r['save']:.2f} t={r['tail']:>5}  "
                f"adv={r['advances']:>3} rew={r['rewrite_calls']:>3} avgRW={r['avg_rewrite_chars']:>7.0f}c "
                f"hit={r['hit_proxy']*100:.1f}% ovf={r['tail_overflow_calls']}{flag}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_worker, ja): ja for ja in job_args}
            for fut in as_completed(futs):
                ja = futs[fut]
                try:
                    r = fut.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"[combo p={ja['pressure']} s={ja['save']} t={ja['tail']}] FAILED: {exc}")
                    continue
                rows.append(r)

    # 展示（按 pressure 分组排序）：并行路径此前未逐行打印，这里补一次汇总；串行已流式打印则跳过往后重复。
    rows.sort(key=lambda r: (r["pressure"], r["save"], r["tail"]))
    if workers > 1 and len(job_args) > 1:
        for r in rows:
            flag = "  <== OA overflow" if r["tail_overflow_calls"] else ""
            print(
                f"  p={r['pressure']:.2f} s={r['save']:.2f} t={r['tail']:>5}  adv={r['advances']:>3} "
                f"rew={r['rewrite_calls']:>3} avgRW={r['avg_rewrite_chars']:>7.0f}c "
                f"hit={r['hit_proxy']*100:.1f}% ovf={r['tail_overflow_calls']}{flag}"
            )

    # 选优：改写最少 + 尾不溢出 + 命中率最高
    no_ovf = [r for r in rows if r["tail_overflow_calls"] == 0]
    pool = no_ovf or rows
    if pool:
        best = sorted(
            pool,
            key=lambda r: (r["advances"], -r["hit_proxy"], r["rewrite_chars"]),
        )[0]
        print("\n# 最优组合")
        print(f"  session={best['session']} pressure={best['pressure']} save={best['save']} tail={best['tail']}")
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
