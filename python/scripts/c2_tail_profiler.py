"""c2_tail_profiler — 真录会话的「尾区每轮均 token/字符」测量 + C2 触发压力现状。

只读、零 LLM、零费用：从转录 JSONL 重建消息，逐 assistant 调用用 v61 默认公式
驱动 project_for_model，统计：
  - 每轮(assistant→tool 成对区)均字符与均 token
  - 当前默认(alpha_win=0.55 / l_max=70400 / l_hard_send=125952)下边界推进次数与触发压力
  - 尾区(KEEP_TAIL)的字符/token 体量，供「保尾 = 每轮均 token × 保留轮数」定参

用法（在 python/ 下）:
  py -3.11 -m scripts.c2_tail_profiler <session_id> [cwd]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _chars(messages: list[dict]) -> int:
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


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("session_id")
    ap.add_argument("cwd", nargs="?", default=".")
    args = ap.parse_args()

    import memory.runtime as rt
    from engine.compact import tool_pair_ranges
    from memory.working import WorkingSnapshot, hydrate

    messages = _load(args.session_id)
    print(f"[session] {args.session_id}  messages={len(messages)}")
    if not messages:
        return 0

    # 逐 assistant 调用驱动 v61（与 runtime_probe 同 patch，仅统计边界推进）
    rt.l5_mode = lambda: "v61"
    working = hydrate(args.session_id)
    if not working.session_id:
        working = WorkingSnapshot(session_id=args.session_id)

    from memory.runtime import project_for_model
    from memory.simulator.params import load_params

    p = load_params()
    call_idxs = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    advances = 0
    last_cursor = 0
    # 尾区（最后 3 个 tool 轮）字符统计
    pairs = tool_pair_ranges(messages)
    tail_cut = messages[-3]["start"] if False else None
    # 直接用 keep_tail_cut
    from engine.compact import keep_tail_cut

    tc = keep_tail_cut(messages)
    tail_msgs = messages[tc:]
    tail_chars = _chars(tail_msgs)

    # 每轮均字符：用成对区间
    pair_chars = []
    for (start, end) in pairs:
        pair_chars.append(_chars(messages[start:end]))
    avg_pair_chars = sum(pair_chars) / max(1, len(pair_chars))
    avg_pair_tok = avg_pair_chars / 4.0

    for idx in call_idxs:
        try:
            project_for_model(
                messages[:idx], working, remaining_turns=8, include_memory_index=False
            )
        except Exception:  # noqa: BLE001
            continue
        if int(working.compact_cursor or 0) != last_cursor:
            advances += 1
            last_cursor = int(working.compact_cursor or 0)

    print("\n# 统计")
    print(f"assistant 调用数        = {len(call_idxs)}")
    print(f"成对(assistant+tool)区间 = {len(pairs)}")
    print(f"每轮均字符              = {avg_pair_chars:.0f}  (≈{avg_pair_tok:.0f} tok)")
    print(f"每轮均 token(字符/4)     = {avg_pair_tok:.0f}")
    print(f"尾区起点(keep_tail_cut)  = {tc} / {len(messages)}")
    print(f"尾区字符                = {tail_chars} (≈{tail_chars/4:.0f} tok)")
    print(f"C2 边界推进次数(v61 默认)= {advances}")
    print(f"\nparams: alpha_win={p.alpha_win} window={p.window_tokens} reserve={p.reserve_tokens} "
          f"l_max={p.l_max} l_hard_send={p.l_hard_send}")
    print(f"l_max/window 压力比      = {p.l_max / p.window_tokens:.3f}")
    print(f"l_hard_send/window      = {p.l_hard_send / p.window_tokens:.3f}")
    print(f"→ 若保尾=每轮均token×3轮：{avg_pair_tok * 3:.0f} tok（当前硬编码 KEEP_TAIL_TOOL_ROUNDS=3）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
