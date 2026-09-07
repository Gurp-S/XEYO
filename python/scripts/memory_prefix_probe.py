"""memory_prefix_probe — 只读诊断：定位「append 会话命中率低/下降」的前缀破坏点。

不修改任何生产文件；只读 transcript + working sidecar + c2 事件 + 工作区指令/工具，
复算每个「模型调用」应发送的头部签名与投影消息哈希，逐调用对比，报告哪一处先分叉。

用法（在 python/ 下）:
  py -3.11 -m scripts.memory_prefix_probe <session_id> [cwd]

输出: 每调用一行 (idx / instr_sig / tools 数量+hash / mode / projected hash / 变化标记)
末了给出「最初分叉点 + 最可能元凶」摘要。

口径说明（诚实标注）:
- 用 WORKING 的 c1_frozen_until 作为全会话冻结边界（近似）；C2 触发点另从
  usage/c2_events.jsonl 读取，二者共同解释「何时改写了历史前缀」。
- projected 用 engine.compact.project（确定性、copy-on-write），不含 T_now 注入
  （注入加在尾部，属次要；此处主要探查头部 system/tools/mode 与投影历史）。
- instr_sig 由 memory.instruction.instruction_cache_signature 计算（即 PromptAssembler
  memo 键里会触发 system 重建的项）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# 保证可 import 工程模块
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha(obj) -> str:
    """对任意 JSON 可序列化对象做确定性 sha1（前 12 位）。"""
    try:
        raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        raw = reprobj(obj)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def reprobj(obj) -> str:
    try:
        return repr(obj)
    except Exception:  # noqa: BLE001
        return str(obj)


def _norm(obj) -> object:
    """JSON 归一：给 dict 排序键、筛掉不可序列化字段，保证跨轮可比。"""
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_norm(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def load_raw_messages(session_id: str) -> list[dict]:
    """从 transcript（含轮转归档）读原始行，过滤为可投影的消息 dict。"""
    from session.hydrate import load_session_messages, message_from_row
    from session.record_transcript import load_transcript, transcript_read_paths
    from session.persistence import transcript_path

    rows: list[dict] = []
    try:
        for p in transcript_read_paths(transcript_path(session_id)):
            rows.extend(load_transcript(p))
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] read transcript failed: {exc}")
    return [message_from_row(r).__dict__ for r in rows if message_from_row(r) is not None]


def instr_sig(cwd: str) -> str:
    try:
        from memory.instruction import instruction_cache_signature

        return _sha(instruction_cache_signature(cwd, cwd))
    except Exception as exc:  # noqa: BLE001
        return f"<err:{type(exc).__name__}>"


def tools_hash(cwd: str) -> tuple[int, str]:
    """工具 schema 的数量与签名哈希（字典序；mode 追加 ExitPlanMode 只在 query_loop 层，此处不含）。"""
    try:
        from tools.catalog import build_default_registry

        reg = build_default_registry(cwd=cwd)
        schemas = list(reg.schemas()) if hasattr(reg, "schemas") else []
        return (len(schemas), _sha([_norm(s) for s in schemas]))
    except Exception as exc:  # noqa: BLE001
        return (0, f"<err:{type(exc).__name__}>")




def mode() -> str:
    try:
        from permissions.policy import agent_mode

        return str(agent_mode() or "agent")
    except Exception:  # noqa: BLE001
        return "?"


def c2_cursor_at(session_id: str) -> tuple[int, list[dict]]:
    """读 working compact_cursor + c2 事件列表。"""
    cursor = 0
    try:
        from memory.working import hydrate

        snap = hydrate(session_id)
        cursor = int(getattr(snap, "compact_cursor", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    evs: list[dict] = []
    try:
        from usage.ledger import c2_events_path, read_c2_events

        p = c2_events_path()
        if p.is_file():
            evs = read_c2_events(p) if hasattr(read_c2_events, "__call__") else []
    except Exception:  # noqa: BLE001
        pass
    return cursor, evs


def projected_list(messages: list[dict], frozen_until: int, idx: int) -> list[dict]:
    """对到第 idx 条消息为止的前缀投影（不做哈希，返回列表用于逐条对比）。"""
    from engine.compact import project

    try:
        return list(project(messages[:idx], frozen_until=min(len(messages[:idx]), max(0, int(frozen_until)))))
    except Exception:  # noqa: BLE001
        return []


def first_divergence(a: list[dict], b: list[dict]) -> tuple[int | None, str]:
    """返回 (首条不同索引, 描述)；相等返回 (None, 'STABLE_APPEND')。
    a/b 为同一边界下的投影列表，b 更长（前一调用 vs 当前调用）。"""
    d = None
    for i in range(min(len(a), len(b))):
        if _norm(a[i]) != _norm(b[i]):
            d = i
            break
    if d is None:
        return None, "STABLE_APPEND(共享前缀字节一致)"
    return d, f"REWRITE@{d}:role={a[d].get('role')!r}"


def transform_count(messages: list[dict], frozen_until: int, idx: int) -> tuple[int, list[int]]:
    """被投影改写(≠原文)的消息数与索引列表：C0 截断 / C1 占位 / C2 摘要落地。"""
    from engine.compact import project

    raw = messages[:idx]
    proj = project(raw, frozen_until=min(len(raw), max(0, int(frozen_until))))
    idxs = [i for i, m in enumerate(proj) if _norm(m) != _norm(raw[i] if i < len(raw) else m)]
    return len(idxs), idxs


def c2_state(session_id: str) -> tuple[int, int, int]:
    """读 working 的 compact_cursor / c2_summary_chars + c2 事件数。"""
    cursor = 0
    chars = 0
    nev = 0
    try:
        from memory.working import hydrate

        snap = hydrate(session_id)
        cursor = int(getattr(snap, "compact_cursor", 0) or 0)
        chars = int(
            getattr(snap, "c2_summary_text", "") and len(snap.c2_summary_text) or 0
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from usage.ledger import c2_events_path

        p = c2_events_path()
        if p and p.is_file():
            nev = sum(1 for _ in p.read_text(encoding="utf-8").splitlines() if _.strip())
    except Exception:  # noqa: BLE001
        pass
    return cursor, chars, nev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session_id")
    ap.add_argument("cwd", nargs="?", default=".")
    args = ap.parse_args()
    sid = args.session_id
    cwd = args.cwd

    messages = load_raw_messages(sid)
    print(f"[session] {sid}  messages={len(messages)}  cwd={cwd}")
    if not messages:
        print("[warn] no messages; nothing to compare")
        return 0

    frozen_until, c2_events = c2_cursor_at(sid)
    compact_turns = {int(e.get("cursor", -1)) for e in c2_events if isinstance(e, dict)}
    print(f"[state] c1_frozen_until≈{frozen_until}  c2_events={len(c2_events)}")

    # 每个「assistant 消息」= 一次模型调用；它之前的全部消息 = 该请求的前缀。
    call_idxs = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    print(f"[calls] assistant(模型调用) 数 = {len(call_idxs)}")

    prev: dict[str, object] = {}
    rows: list[dict] = []
    first_kind: tuple[int, str] | None = None  # (idx, 分叉类别)
    base = _sha("probe")
    prev_proj: list[dict] | None = None
    prev_head: dict[str, object] = {}
    rows: list[dict] = []
    first_kind: tuple[int, str] | None = None
    rewritten_calls = 0

    for ci, idx in enumerate(call_idxs):
        isig = instr_sig(cwd)
        tn, thash = tools_hash(cwd)
        m = mode()
        proj = projected_list(messages, frozen_until, idx)
        tr_n, tr_idxs = transform_count(messages, frozen_until, idx)
        dloc, ddesc = first_divergence(prev_proj, proj) if prev_proj else (None, "FIRST_CALL")
        if ddesc.startswith("REWRITE"):
            rewritten_calls += 1
        head_chg = [
            kk
            for kk, val in (
                ("instr", isig),
                ("tools", thash),
                ("mode", m),
            )
            if kk in prev_head and prev_head[kk] != val
        ]
        rows.append(
            {
                "call": ci,
                "idx": idx,
                "instr": isig,
                "tools_n": tn,
                "toolsH": thash,
                "mode": m,
                "proj_len": len(proj),
                "tr_n": tr_n,
                "head_chg": "+".join(head_chg),
                "div": ddesc.split(":", 1)[0],
                "div_i": dloc,
            }
        )
        prev_proj = proj
        prev_head = {"instr": isig, "tools": thash, "mode": m}
        if head_chg and first_kind is None:
            first_kind = (idx, "HEAD:" + ",".join(head_chg))

    print("\n# 每调用：头部签名 + 投影改写面 + 共享前缀是否被重写")
    print(
        f"{'call':>4} {'idx':>5} {'instr':>12} {'tN':>3} {'toolsH':>12} {'mode':>5} "
        f"{'projLen':>7} {'tRw':>4} {'headChg':>16} {'sharedPrefix'}"
    )
    for r in rows:
        print(
            f"{r['call']:>4} {r['idx']:>5} {r['instr']:>12} {r['tools_n']:>3} "
            f"{r['toolsH']:>12} {r['mode']:>5} {r['proj_len']:>7} {r['tr_n']:>4} "
            f"{r['head_chg']:>16}  {r['div']}@{r['div_i'] if r['div_i'] is not None else '-'}"
        )

    cursor, schars, nev = c2_state(sid)
    print("\n# 摘要")
    print(f"调用数 = {len(rows)}")
    print(f"头部(instr_sig/tools/mode)发生变化的调用数 = {sum(1 for r in rows if r['head_chg'])}")
    if rewritten_calls:
        print(f"共享子前缀被改写的调用数 = {rewritten_calls}  ← 这些调用会与前一次前缀不匹配(缓存断裂)")
        first_rw = next(r for r in rows if r["div"].startswith("REWRITE"))
        print(f"首次改写发生在 call={first_rw['call']} idx={first_rw['idx']} 处")
    else:
        print("共享子前缀在各调用间字节一致(在当前冻结边界下) —— 若命中率仍低，"
              "多半是【冻结边界推进(C1/C2)】或【头部变化】或【注入尾段】所致，需结合真实 C2 会话与逐轮边界推进看。")
    print(f"[working] compact_cursor={cursor}  c2_summary_chars={schars}  c2_events={nev}")
    print(f"[projection 改写面] 每调用 tr_n=投影≠原文的消息数(即 C0 截断/C1占位/C2摘要生效的量)；"
          f"末调用 tr_n={rows[-1]['tr_n'] if rows else '-'}，趋势见上表 trRw 列")
    if first_kind:
        print(f"首次头部变化: {first_kind}")
    print("\n提示: 头部不在本会话变 → 问题多半是【C1/C2 冻结边界推进改写历史】(压缩阈值/时机)。"
          "同类实现也 head-anchored+保尾+压力阈值才触发；XEYO 每轮 decide 就可能在更高频边界改写。"
          "请到真实活跃 C2 会话(working.compat_cursor>0 或 c2_events>0)上再跑本探针，会显现 REWRITE@i。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
