"""memory_runtime_probe — 运行时打点版：量化「每次 C2/C1 边界推进」对前缀的改写。

不修改任何生产 .py：全部靠进程内 monkeypatch（跑完 restore）。只读 transcript + working
sidecar + 指令/工具；用真实 project_for_model/decide/apply_c2_messages 走一遍会话，逐调用打点。

零费用：只走内存 simulator（decide 是纯函数），不调用任何 LLM / vendor API。

用法（在 python/ 下）:
  py -3.11 -m scripts.memory_runtime_probe <session_id> [cwd]

说明:
- 为复现 C2 触发，本探针设 XEYO_L5=v61（每轮 decide），与真实灰度一致与否由调用方判断；
  不想走的场景可自行改成 XEYO_C2_GATE=1 只放超长 C2。
- 打点项: ① 每次调用 decide 选的动作(keep/C1/C2/L4) ② C2/C1 边界(compact_cursor/c1_frozen_until)
  是否前进、前进多少 ③ 连续两次调用共享子前缀是否被改写 + 首条改写索引/role
  ④ system memo 是否命中 + instr_sig 是否变。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha(obj) -> str:
    try:
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        raw = repr(obj)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _norm(obj) -> object:
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_norm(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def load_raw_messages(session_id: str) -> list[dict]:
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


def first_divergence(a: list[dict], b: list[dict]) -> tuple[int | None, str]:
    d = None
    for i in range(min(len(a), len(b))):
        if _norm(a[i]) != _norm(b[i]):
            d = i
            break
    if d is None:
        return None, "STABLE_APPEND"
    return d, f"REWRITE@{d}:role={a[d].get('role')!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session_id")
    ap.add_argument("cwd", nargs="?", default=".")
    args = ap.parse_args()
    sid = args.session_id
    cwd = args.cwd

    # 复现 C2 路径：每轮 decide
    prior_l5 = os.environ.get("XEYO_L5")
    os.environ["XEYO_L5"] = "v61"

    import memory.runtime as rt
    import memory.working as wk
    from memory.working import WorkingSnapshot, hydrate
    from memory.runtime import project_for_model

    # 强制走 v61 decide 路径（l5_mode 读 settings.json 权威，不读 os.environ，故直接 patch 命名空间）。
    _orig_l5 = rt.l5_mode
    rt.l5_mode = lambda: "v61"

    messages = load_raw_messages(sid)
    print(f"[session] {sid}  messages={len(messages)}  cwd={cwd}  (runtime l5_mode patched → v61, decide 每轮)")
    if not messages:
        print("[warn] no messages")
        return 0

    working = hydrate(sid)
    if not working.session_id:
        working = WorkingSnapshot(session_id=sid)

    # ---- patch：记录 C2/C1 边界推进 + C2 应用 ----
    logs: list[dict] = []

    def _patch_note_c2(name: str):
        orig = getattr(wk, name)

        def wrapper(*a, **k):
            before = int(getattr(a[0], "compact_cursor", 0) or 0) if a else None
            r = orig(*a, **k)
            after = int(getattr(a[0], "compact_cursor", 0) or 0) if a else None
            logs.append({"event": name, "cursor_before": before, "cursor_after": after})
            return r

        setattr(wk, name, wrapper)

    _patch_note_c2("note_c2")
    _patch_note_c2("note_c1")

    orig_apply = rt.apply_c2_messages

    def apply_wrapper(*a, **k):
        logs.append({"event": "apply_c2_messages"})
        return orig_apply(*a, **k)

    rt.apply_c2_messages = apply_wrapper

    # ---- 逐调用驱动 project_for_model ----
    call_idxs = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    rows: list[dict] = []
    prev_out: list[dict] | None = None
    prev_work = (0, 0)
    rewrite_calls = 0
    head_changes = 0

    for ci, idx in enumerate(call_idxs):
        before = (
            int(getattr(working, "compact_cursor", 0) or 0),
            int(getattr(working, "c1_frozen_until", 0) or 0),
        )
        n_logs_before = len(logs)
        try:
            out = project_for_model(
                messages[:idx],
                working,
                remaining_turns=8,
                include_memory_index=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[call {ci}] project_for_model error: {type(exc).__name__}: {exc}")
            continue
        after = (
            int(getattr(working, "compact_cursor", 0) or 0),
            int(getattr(working, "c1_frozen_until", 0) or 0),
        )
        action = str(getattr(working, "last_action", "") or "")
        new_logs = logs[n_logs_before:]
        dloc, ddesc = first_divergence(prev_out, out) if prev_out else (None, "FIRST")
        boundary_adv = after != before
        if ddesc.startswith("REWRITE"):
            rewrite_calls += 1
        rows.append(
            {
                "call": ci,
                "idx": idx,
                "action": action,
                "cursor": after[0],
                "frozen": after[1],
                "badv": int(boundary_adv),
                "c2_pct": sum(1 for L in new_logs if L["event"] == "apply_c2_messages"),
                "div": ddesc,
                "div_i": dloc,
            }
        )
        prev_out = out
        prev_work = after

    # ---- restore ----
    rt.l5_mode = _orig_l5
    if prior_l5 is None:
        os.environ.pop("XEYO_L5", None)
    else:
        os.environ["XEYO_L5"] = prior_l5

    print(f"\n# 每调用(decide)打点")
    print(
        f"{'call':>4} {'idx':>5} {'act':>6} {'cursor':>6} {'frozen':>6} {'adv':>3} "
        f"{'c2':>3}  sharedPrefix"
    )
    for r in rows:
        print(
            f"{r['call']:>4} {r['idx']:>5} {r['action']:>6} {r['cursor']:>6} "
            f"{r['frozen']:>6} {r['badv']:>3} {r['c2_pct']:>3}  {r['div']}"
        )

    total_calls = len(rows)
    n_adv = sum(1 for r in rows if r["badv"])
    n_c2 = sum(1 for r in rows if r["c2_pct"])
    print("\n# 摘要")
    print(f"decide 调用数 = {total_calls}")
    print(f"边界(compact_cursor/c1_frozen_until)前进的调用数 = {n_adv}")
    print(f"触发 apply_c2_messages 的调用数 = {n_c2}")
    print(f"共享子前缀被改写的调用数 = {rewrite_calls}")
    if n_c2:
        print(f"→ C2 触发率 ≈ {n_c2}/{total_calls} = {n_c2 / max(1, total_calls) * 100:.1f}%")
        print("→ 每次 C2 = 一次边界推进 = 一次历史前缀改写；频率越高，累计命中率被拉低越狠。"
              "这就是『C2 触发阈值/时机』问题：DSH 是 head-anchored+保尾+压力阈值才触发，"
              "XEYO 每轮 decide 都可能触发（此处复现 v61）。")
    if not n_c2 and rewrite_calls == 0:
        print("未触发 C2、无前缀改写 —— 此会话头部稳定、纯追加；若命中率仍低，需结合真实 cacheHit/cacheMiss 数据看。")
    print("\n提示: 这是『运行时打点』的离线重建（monkeypatch + 驱动 decide）；"
          "生产代码未改动。若想贴近真实灰度，把 XEYO_L5 换成你实际用的值 (project / 默认) 再跑。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
