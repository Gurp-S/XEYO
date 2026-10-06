"""折叠水位 A/B：在真实转录上**驱动生产入口** ``memory.runtime.project_for_model`` 逐轮回放。

为什么不用现成的判官（``evals/wsc_failure_judge._project_prefix``）：它直接调 WSC 投影，
**不含 C2 触发链**（decide → cooling → try_extend_c2 的水位/冷却/钱门）。要回答
"水位抬到 W 会怎样"，必须让真实的触发链跑起来。

两臂（同一份转录、同一份状态机、只换一个 env）：

- ``baseline``：与生产一致（水位关）。
- ``watermark<W>``：``XEYO_WSC_SOFT_WATERMARK=<W>`` ⇒ 普通扩展折叠在 prompt < W 时一律不折
  （首压不受它管，见 ``memory/wsc_watermark`` 的适用范围）。

口径（**两臂同口径，差额才是结论**）：
- ``prompt`` = 本枪发射投影的 canonical JSON 的 token（生产 ``token_len``，utf-8/4）；
- ``lcp``   = 与上一枪发射投影的公共前缀（与 ``memory/observe.observe_shot`` 同函数）；
- ``miss_proxy`` = prompt − lcp（引擎自己的未命中代理；厂商侧还有 system/tools 不在投影里，
  所以它**不是**厂商命中，只用于臂间比较）；
- ``new`` = 相对上一枪的 prompt 增量（必须 miss 的新内容，不可回收）；
- 折叠计数 = ``snap.last_action == "C2"``。

隔离（缺一即污染真实数据根）：XEYO_HOME / XEYO_OFFLOAD_DIR / XEYO_SESSIONS_DIR /
XEYO_USAGE_DIR / XEYO_AUDIT_LOG / XEYO_WSC_OFFLINE 全部指向临时根，跑前打印并断言。

用法::

    py -3.11 python/scripts/wsc_fold_watermark_ab.py --session sess_xxx --arms baseline
    py -3.11 python/scripts/wsc_fold_watermark_ab.py --session sess_xxx --arms baseline watermark200000 watermark500000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

REPO_PY = Path(__file__).resolve().parents[1]
if str(REPO_PY) not in sys.path:
    sys.path.insert(0, str(REPO_PY))


def _isolate(tmp: Path) -> dict[str, str]:
    """四根 + 审计 + 离线档全部钉到临时目录；返回实际写入的点位供打印自证。"""
    roots = {
        "XEYO_HOME": tmp / "home",
        "XEYO_OFFLOAD_DIR": tmp / "offload",
        "XEYO_SESSIONS_DIR": tmp / "sessions",
        "XEYO_USAGE_DIR": tmp / "usage",
        "XEYO_AUDIT_LOG": tmp / "audit.jsonl",
        "XEYO_WSC_OFFLINE": "1",
    }
    for k, v in roots.items():
        os.environ[k] = str(v)
        if k != "XEYO_WSC_OFFLINE":
            Path(v).parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("XEYO_WSC", "1")
    os.environ.setdefault("XEYO_L5", "v61")
    return roots


def _temporal_note_filter(items: list[dict]) -> list[dict]:
    """生产形态的**逐枪时点**过滤：此刻每个 note_key 只留「已出现的最新版」，旧版从原位抽走。

    与静态版的区别在时间维度：断点只在"新版本到来的那一枪"出现，早枪仍能看到当时的旧版。
    """
    last: dict[str, int] = {}
    for i, m in enumerate(items):
        if m.get("note_key"):
            last[m["note_key"]] = i
    return [m for i, m in enumerate(items)
            if not m.get("note_key") or last[m["note_key"]] == i]


def _temporal_fixed_filter(items: list[dict]) -> list[dict]:
    """候选修法的逐枪时点过滤：每个 key 保留**内容等于当前版本**的**最早**实例。

    与 `temporal` 的唯一区别：同内容的重复追加不再把实例"刷新"到尾部——重复追加
    成为纯 no-op（前缀零改写）；内容真变化时，旧版才被移除、新版的**首个**实例
    （就在其追加点）承接。语义与 `temporal` 等价（可见内容都是当前版本；
    实例位置只差"内容没变时不动"这一条）。
    """
    current: dict[str, object] = {}
    for m in items:
        k = m.get("note_key")
        if k:
            current[k] = m.get("content")
    first: dict[str, int] = {}
    for i, m in enumerate(items):
        k = m.get("note_key")
        if k and m.get("content") == current.get(k):
            first.setdefault(k, i)
    return [m for i, m in enumerate(items)
            if not m.get("note_key") or first.get(m["note_key"]) == i]


def run_arm(session_path: Path, sid: str, *, watermark: int | None, limit_turns: int,
            note_policy: str = "dedup", state_policy: str = "persist",
            size_policy: str = "none", long_at: int = 64_000,
            needles: bool = False, sizes: bool = False, args_geom: str = "") -> dict:
    """跑一臂；返回逐枪记录与汇总。"""
    from memory.simulator.replay import _user_turn_indices
    from memory.simulator.projection import lcp_tokens
    from memory.token import token_len
    from memory.working import WorkingSnapshot
    from memory.runtime import project_for_model
    from synaptic.replay import load_jsonl

    if watermark:
        os.environ["XEYO_WSC_SOFT_WATERMARK"] = str(watermark)
    else:
        os.environ.pop("XEYO_WSC_SOFT_WATERMARK", None)
    # 每臂独立会话状态：水位是软模块的进程内账，臂间必须清
    try:
        from memory import wsc_watermark as _wm

        _wm.reset_session(sid)
    except Exception:
        pass

    _restore: list[tuple[object, str, object]] = []
    if size_policy == "custom":
        os.environ["XEYO_PRUNE_GEOM"] = args_geom
    if size_policy != "none":
        # 只改接线点的行为：① 打开尺寸档旗标；② 把可见头/尾收紧；③ aggr 再把阈值降到 2048。
        # ⚠️ 必须可复原：同一进程跑第二臂时若再包一层，会重复传 head_chars ⇒ TypeError
        # （这正是登记表里那次"第 2 枪中断、未复现"的真因——多臂 + 尺寸补丁叠加）。
        os.environ["XEYO_WSC_SIZE_PRUNE"] = "1"
        import memory.wsc_size_prune as _sp

        _orig = _sp.maybe_prune_with_archive

        import re as _re
        _ERR = _re.compile(r"(Traceback|Error|Exception|FAILED|failed|exit(?:ed)?\s*(?:with\s*)?code\s*[1-9]|panicked)", _re.I)

        def _forced(raw, **kw):
            kw.pop("threshold_chars", None)
            kw.pop("head_chars", None)
            kw.pop("tail_chars", None)
            if size_policy == "errc0":
                # J 变体：带错误样式的结果**退回 C0**（4096 头 + 1024 尾），其余走 aggr
                from prompt.fence import truncate_tool_content_preserving_fence as _c0
                from engine.compact import MAX_TOOL_RESULT_CHARS as _cap, TRUNCATE_SUFFIX as _sfx
                if _ERR.search(str(raw or "")[:4000]):
                    _mk = chr(10) + "…[truncated]…" + chr(10)
                    return _c0(str(raw), max_chars=_cap, marker=_mk, fallback_suffix=_sfx), None
                return _orig(raw, threshold_chars=2048, head_chars=1024, tail_chars=256, **kw)
            if size_policy == "custom":
                h, t, th = (int(x) for x in (os.environ.get("XEYO_PRUNE_GEOM") or "1024,256,2048").split(","))
                return _orig(raw, threshold_chars=th, head_chars=h, tail_chars=t, **kw)
            return _orig(raw, threshold_chars=(2048 if size_policy == "aggr" else 8192),
                         head_chars=1024, tail_chars=256, **kw)

        _sp.maybe_prune_with_archive = _forced
        _restore.append((_sp, "maybe_prune_with_archive", _orig))
        if size_policy in ("aggr", "errc0", "custom"):
            import engine.compact as _ec

            # 接线条件读的是 SIZE_PRUNE_THRESHOLD_CHARS（最终档落地后不再是 MAX_TOOL_RESULT_CHARS）；
            # 这里同口径替换并在臂末复原，保证各档在"落地前后"行为逐位一致、可复跑。
            _restore.append((_ec, "SIZE_PRUNE_THRESHOLD_CHARS", _ec.SIZE_PRUNE_THRESHOLD_CHARS))
            if size_policy == "custom":
                _th = int((os.environ.get("XEYO_PRUNE_GEOM") or "1024,256,2048").split(",")[2])
            else:
                _th = 2048
            _ec.SIZE_PRUNE_THRESHOLD_CHARS = _th
    else:
        os.environ.pop("XEYO_WSC_SIZE_PRUNE", None)

    rows = load_jsonl(session_path)
    if not rows:
        return {"error": "empty transcript"}
    msgs = []
    for r in rows:
        role = str(r.get("role") or "")
        # 只收真正会进请求的行：`ui_thought` 是 GUI 专用、`surface_op`(rewind) 是带外事件
        # （实测某会话 151 条 ui_thought + 1 条 surface_op；收进来会把切点与投影都算错）
        if role not in ("user", "assistant", "tool"):
            continue
        content = r.get("content")
        if role == "tool":
            m = {"role": "user", "content": content, "name": r.get("name")}
            if r.get("tool_call_id"):
                m["tool_call_id"] = r["tool_call_id"]
            if r.get("note_key"):
                m["note_key"] = r["note_key"]
            msgs.append(m)
        else:
            m = {"role": role, "content": content}
            if r.get("name"):
                m["name"] = r["name"]
            if role == "assistant" and isinstance(r.get("tool_calls"), list) and r["tool_calls"]:
                m["tool_calls"] = r["tool_calls"]
            if r.get("note_key"):
                m["note_key"] = r["note_key"]
            msgs.append(m)

    if note_policy == "dedup":
        # ⚠️ 口径更正（10-04 深夜）：这是**静态全局去重**——把整段会话按"最终最新版"一次性压平。
        # 生产实际是**逐枪时点**过滤（`session/state_projection.current_context_items` 每枪用
        # "此刻已存在的版本"选最新版；旧版在新版本到来时才从原位抽走 ⇒ 断点发生在时间上）。
        # 静态版产生不了时间维度的断点（还会让早枪连当时的旧版都看不见）⇒ 用它做过 note A/B
        # 是无效实验，也复现不出生产的中途重发尖峰。要生产形态用 `temporal`；本值只保留给
        # 历史批次的连续性。
        latest: dict[str, int] = {}
        for i, m in enumerate(msgs):
            if m.get("note_key"):
                latest[m["note_key"]] = i
        msgs = [m for i, m in enumerate(msgs)
                if not m.get("note_key") or latest[m["note_key"]] == i]

    # 每枪的上下文 = 「该条 assistant 回复之前」的全部消息（一条 assistant = 一次模型调用；
    # 实测 68 条 assistant ⇔ 账本 68 枪）。按"用户轮"切只有 5 个点，会漏掉回合内所有折叠。
    bounds = [i for i, m in enumerate(msgs) if m["role"] == "assistant"]
    if not bounds:
        return {"error": "no assistant turns"}

    snap = WorkingSnapshot(session_id=sid)
    cwd = os.environ["XEYO_OFFLOAD_DIR"]
    prev_canon = ""
    recs = []
    nd = Counter()
    sz = Counter()
    for t, end in enumerate(bounds[: max(1, limit_turns)]):
        if state_policy == "lost":
            from memory import wsc_projection as _wp

            _wp._STATE.pop(_wp._state_key(sid, cwd), None)
        ctx = msgs[:end]
        if note_policy == "temporal":
            ctx = _temporal_note_filter(ctx)
        elif note_policy == "temporal-fixed":
            ctx = _temporal_fixed_filter(ctx)
        try:
            emitted = project_for_model(
                ctx, snap, remaining_turns=16, context_limit=1_000_000,
                provider="deepseek", model_name="deepseek-v4.1-flash-expires-on-0910",
                cwd=cwd,
            )
        except Exception as exc:  # noqa: BLE001
            recs.append({"turn": t, "error": f"{type(exc).__name__}: {exc}"})
            break
        canon = json.dumps(emitted, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if sizes:
            # 尺寸记账（两侧同一抽取器 message_text 的纯文本口径）：
            # Σ原始上下文 = 本枪未做任何投影时消息流的文本量；Σ发射投影 = 实际送模型的消息文本量。
            from synaptic.textutil import message_text as _mt

            sz["raw_chars"] += sum(len(_mt(_m)) for _m in ctx)
            sz["emit_chars"] += sum(len(_mt(_m)) for _m in emitted)
        if needles:
            # 端到端：针从**历史**收割（前 8k 字符窗口，与建图同口径），查是否出现在本枪发射投影里。
            # 注意这是"投影全文"口径（含 [PATHS]/[WORKING SET]/卡面），比"工具结果正文内"更接近模型实际可见面。
            from synaptic.textutil import extract_error_sig, extract_paths
            from synaptic.textutil import message_text as _mt
            seen = set()
            for m in ctx:
                t = _mt(m)[:8000]
                for x in extract_paths(t, limit=12):
                    if x and x in t:          # ⚠️ 针必须先在原文里逐字存在，否则"存活率"量的是抽取器
                        seen.add(("path", x))
                sig = extract_error_sig(t)
                if sig and sig in t:           # 同上：`extract_error_sig` 会合成（如给裸退出码加前缀）
                    seen.add(("err", sig))
            # ⚠️ 对**纯文本**匹配，不对 canonical JSON 匹配：JSON 会把换行/引号转义
            # （错误签名常含换行 ⇒ 在 canon 里永远匹配不上；实测 read 0/11 全是这个 bug）。
            _blob_parts = []
            for _m in emitted:
                _c = _m.get("content")
                if isinstance(_c, str):
                    _blob_parts.append(_c)
                elif isinstance(_c, list):
                    for _b in _c:
                        if isinstance(_b, dict):
                            for _v in _b.values():
                                if isinstance(_v, str):
                                    _blob_parts.append(_v)
            _blob = chr(10).join(_blob_parts)   # 避开转义：chr(10) 就是换行
            for kind, x in seen:
                nd[f"{kind}_total"] += 1
                if x in _blob:
                    nd[f"{kind}_alive"] += 1
        prompt = token_len(canon)
        lcp = lcp_tokens(canon, prev_canon) if prev_canon else 0
        new = prompt if not prev_canon else max(0, prompt - recs[-1]["prompt"])
        recs.append({
            "turn": t, "prompt": prompt, "lcp": lcp, "new": new,
            "miss_proxy": max(0, prompt - lcp), "action": str(snap.last_action),
            "cursor": int(snap.compact_cursor or 0),
        })
        prev_canon = canon
        # 生产顺序：厂商返回后 `note_shot` 记命中/长度并把 turns_since_c2 +1。
        # ⚠️ 漏掉它 ⇒ turns_since_c2 恒 0 ⇒ `cooling`（<min_middle_edit_gap=4）恒真
        # ⇒ decide 点出的 C2 全被降级成 keep，回放会"一次都不折"（我第一版就是这样）。
        from datetime import datetime

        from memory.working import note_shot

        note_shot(snap, hit=lcp, prompt=prompt, at=datetime.now())

    ok = [r for r in recs if "prompt" in r]
    agg = Counter()
    for r in ok:
        if r["prompt"] >= long_at:
            agg["long_shots"] += 1
            agg["long_prompt"] += r["prompt"]
            agg["long_hit"] += r["prompt"] - r["miss_proxy"]
            agg["long_miss"] += r["miss_proxy"]
            agg["long_new"] += r["new"]
    for r in ok:
        agg["shots"] += 1
        agg["prompt"] += r["prompt"]
        agg["lcp"] += r["lcp"]
        agg["new"] += r["new"]
        agg["miss_proxy"] += r["miss_proxy"]
        agg["folds"] += int(r["action"] == "C2")
    agg["peak"] = max((r["prompt"] for r in ok), default=0)
    # R8 复验（在**单纪元真序**上）：keep 枪的断前缀是否都紧跟折叠
    last_fold = None
    brk = Counter()
    for i, r in enumerate(ok):
        if r["action"] == "C2":
            last_fold = i
            continue
        prev = ok[i - 1] if i else None
        if prev is None:
            continue
        lcp = r["lcp"]
        if lcp < 0.7 * max(1, prev["prompt"]) and r["miss_proxy"] > 4096:
            d = "∞" if last_fold is None else str(i - last_fold)
            brk[d if d == "∞" or int(d) <= 5 else ">5"] += 1
    agg["breaks_by_dist"] = dict(sorted(
        brk.items(), key=lambda kv: (kv[0] == "∞", kv[0] == ">5", int(kv[0]) if kv[0].isdigit() else 0)))
    agg["hit_proxy"] = 1 - agg["miss_proxy"] / max(1, agg["prompt"])
    agg["ceiling"] = 1 - agg["new"] / max(1, agg["prompt"])
    if sizes:
        agg.update(sz)
        agg["compression"] = 1 - sz["emit_chars"] / max(1, sz["raw_chars"])
    for mod, attr, old in _restore:   # 复原补丁，保证多臂同进程互不污染
        setattr(mod, attr, old)
    agg.update(nd)
    return {"recs": recs, "agg": dict(agg), "errors": [r for r in recs if "error" in r]}


def main() -> int:
    ap = argparse.ArgumentParser(description="折叠水位 A/B（驱动生产入口，零 API）")
    ap.add_argument("--session", required=True, help="会话 id（sess_xxx）或 .jsonl 全路径")
    ap.add_argument("--arms", nargs="+", default=["baseline"],
                    help="baseline / watermark<W>，如 watermark200000")
    ap.add_argument("--turns", type=int, default=10**9, help="最多回放多少回合")
    ap.add_argument("--long", type=int, default=64_000, help="长对话段阈值（prompt ≥ 该值的枪单独汇总）")
    ap.add_argument("--needles", action="store_true",
                    help="端到端针存活：从历史收割路径/错误签名，查是否出现在**本枪发射投影**里")
    ap.add_argument("--sizes", action="store_true",
                    help="尺寸记账：Σ原始上下文/Σ发射投影（message_text 纯文本口径）与发射压缩率")
    ap.add_argument("--dump", action="store_true", help="打印逐枪表")
    ap.add_argument("--state-policy", default="persist", choices=("persist", "lost"),
                    help="WSC 进程内状态：persist=正常；lost=每枪前清空 _STATE（模拟重启/槽位顶掉），"
                         "用于验证『头重建 ⇒ keep 枪也断前缀』这个机制假设")
    ap.add_argument("--prune-geom", default="", help="自定义修剪几何 HEAD,TAIL,THRESH（配合 --size-policy custom）")
    ap.add_argument("--size-policy", default="none", choices=("none", "tight", "aggr", "errc0", "custom"),
                    help="尺寸侧：none=现状；tight=超 8192 的结果换『头1024+尾256+Read句柄』；"
                         "aggr=tight 且阈值降到 2048（连中等结果也收）。该臂只在驱动内 patch 接线点，"
                         "不改产品代码")
    ap.add_argument("--note-policy", default="temporal", choices=("dedup", "keep-all", "temporal", "temporal-fixed"),
                    help="留痕版本策略（默认 temporal=生产形态）："
                         "temporal=逐枪时点只留最新版，旧版从原位抽走 ⇒ 尖峰可复现；"
                         "dedup=静态全局去重（历史口径，**非生产形态**，仅给旧批次续用）；"
                         "temporal-fixed=候选修法（保留当前版本的最早实例 ⇒ 重复追加成 no-op）；"
                         "keep-all=对照（全部版本原位保留，前缀零改写）")
    args = ap.parse_args()

    p = Path(args.session)
    if not p.is_file():
        home = Path(os.environ.get("XEYO_REAL_SESSIONS") or (Path.home() / ".xeyo" / "sessions"))
        p = home / f"{args.session}.jsonl"
    if not p.is_file():
        print(f"找不到转录: {args.session}")
        return 2
    sid = p.stem

    tmp = Path(tempfile.mkdtemp(prefix=f"wsc_ab_{sid[:12]}_"))
    roots = _isolate(tmp)
    print("# 折叠水位 A/B（生产入口回放）")
    print(f"转录={p}  字节={p.stat().st_size:,}  会话={sid}  回合上限={args.turns}  留痕策略={args.note_policy}")
    print("隔离根（断言全部在 tmp 下）:")
    for k, v in roots.items():
        if k != "XEYO_WSC_OFFLINE":  # 开关值不是路径
            assert str(tmp) in str(v), f"{k} 未隔离: {v}"
        print(f"  {k}={v}")
    print()

    for arm in args.arms:
        wm = None
        if arm.startswith("watermark"):
            wm = int(arm[len("watermark"):])
        res = run_arm(p, sid, watermark=wm, limit_turns=args.turns, note_policy=args.note_policy,
                      state_policy=args.state_policy, size_policy=args.size_policy,
                      long_at=args.long, needles=args.needles, sizes=args.sizes,
                      args_geom=args.prune_geom)
        a = res.get("agg") or {}
        print(f"## 臂 {arm}  (note={args.note_policy}, state={args.state_policy}, size={args.size_policy})")
        for e in res.get("errors", [])[:3]:
            print(f"  ⚠️ 中断于第 {e.get('turn')} 枪：{e.get('error')}")
        if not a:
            print(f"  失败：{res.get('error') or res.get('errors')}")
            continue
        print(f"  枪={a['shots']}  Σprompt={a['prompt']:,}  Σnew={a['new']:,}  "
              f"Σmiss_proxy={a['miss_proxy']:,}")
        print(f"  命中代理={a['hit_proxy']:.4f}  天花板={a['ceiling']:.4f}  "
              f"折叠={a['folds']} 次  峰值={a['peak']:,}  ΣLCP={a['lcp']:,}")
        if args.needles and a.get("path_total"):
            _pt, _pa = a.get("path_total", 0), a.get("path_alive", 0)
            _et, _ea = a.get("err_total", 0), a.get("err_alive", 0)
            print(f"  端到端针存活：路径 {_pa}/{_pt}={_pa/max(1,_pt):.1%}  "
                  f"错误签名 {_ea}/{_et}={_ea/max(1,_et):.1%}（缺键按 0 显示，不代表 0 存活）")
        if a.get("breaks_by_dist"):
            print(f"  断前缀（keep 枪，距上次折叠几枪）: {a['breaks_by_dist']}")
        if a.get("long_shots"):
            lp = a["long_prompt"]
            print(f"  长段(≥{args.long:,}): 枪={a['long_shots']} 命中={a['long_hit']/lp:.4f} "
                  f"miss={a['long_miss']:,} 新增={a['long_new']:,} 天花板={1-a['long_new']/lp:.4f}")
        if a.get("raw_chars"):
            print(f"  尺寸记账（纯文本字符）：Σ原始上下文={a['raw_chars']:,}  "
                  f"Σ发射投影={a['emit_chars']:,}  发射压缩率={a['compression']:.2%}")
        if args.dump:
            for r in res["recs"]:
                if "prompt" in r:
                    print(f"    t={r['turn']:3d} act={r['action']:5s} cur={r['cursor']:>5d} "
                          f"prompt={r['prompt']:>8,} lcp={r['lcp']:>8,} new={r['new']:>7,} "
                          f"miss={r['miss_proxy']:>8,}")
        print()
    print(f"（临时根 {tmp}；跑完可整目录删除）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
