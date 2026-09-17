"""只读探针：WSC 头 vs 生产 C2 头，**同节奏、同切点、同尾部**对撞。

## 为什么必须重建这个台子（先读，否则重复第七/八轮的口径错误）

1. **生产压过之后每一轮都发紧凑投影**，与 decide 的动作无关：
   `memory/runtime.py:1063-1096` `apply_c2_messages` = `[system: 摘要] + project_c0c1(右段)`；
   `runtime.py:1643-1645` `send()`：`if action == "C2" or working.compact_cursor > 0:` → 走它。
   而 `synaptic/replay.py:291-292` 在未过闸/收益门拒绝时发**整段原文** —— 那是口径伪影。
2. **水位基准是上一枪实际发送的 prompt tokens**（vendor usage）：
   `engine/query_loop.py:1382` `note_shot(... prompt=hit+miss)` → `runtime.py:1910-1914`
   读 `last_prompt_tokens` → `runtime.py:1896` `prompt >= limit*thr`（默认 0.8）。
   而 `synaptic/replay.py:263` 用的是**原始前缀**估算且单调增 ⇒ 一旦越过就每轮都压。
3. **「WSC 能不能替换 C2」必须同节奏对撞**：两臂在**同一批回合**、用**同一个切点**
   （生产 `c2_cut_index`）、发**同一种尾部**（C0 投影），只是**头**的生成器不同
   （WSC 热层日志 vs 生产确定性摘要）。否则比的是节奏差异，不是算法差异。

本探针就做这件事：每个会话逐用户回合跑 N 个臂，每臂自带 cursor/头/x_prev，
共用同一套触发判据与切点。

## 口径（跨表不可直接相减）

- 尾部：两臂都按 **C0 投影**（`engine.compact.project`），不含 C1 老化占位 ⇒ 比生产
  略悲观，但**两臂对称**。刻意选择。
- 头：两臂都以 `state_from_messages(tail, cursor=0, system=head)` 注入（p_s 位置），
  与 `synaptic/replay.py` 既有口径一致；生产实际是把摘要作为第一条 system 消息，位置相同。
- 命中：`H` 来自 `memory.simulator` 的 ρ̂(age=0) 模型，`hit = H/L`。
- 成本：`c_biz_yuan`，价目 `usage/pricing.py`（命中 0.05 / 未命中 1.5 元每百万）。
- 头/尾 token 用 `Projected.p_end` 切分（p_s+p_c = 头），不再用 JSON 体积（两个空间不可混）。

零 API 花费、零生产改动、只读。

## 用法

    ./.venv/Scripts/python.exe tests/wsc/_duel_probe.py <session.jsonl|dir> [选项]

选项：
    --arms wsc,c2,v61          默认 wsc,c2
    --cadence wm80|wm50|every  默认 wm80（生产水位 0.8×limit）
    --limit 131072             上下文窗口（token）
    --mode closure|append_only --level Medium+
    --sessions N               目录模式只跑前 N 个会话
    --turns N                  单会话只打印前 N 回合
    --dump out.jsonl           逐回合落盘（跨臂按同一批回合对齐用）
    --handle-style expand|read 默认 expand。`read` = **生产形态**
                               （`Read(file_path=…, offset=…, limit=…)`，需 --view-dir）。
                               ⚠️ 两形态的头 token 不同 ⇒ 成本比不可跨形态相减；
                               `expand` 在生产里**没有解析器**（专用工具已删），
                               故只有 `read` 档的比例是「真换上 WSC」的比例。
    --view-dir DIR             `read` 档的取回视图目录（每会话一份）
    --view-ref-base DIR        引用渲染基准（给了就渲染工作区相对路径）

## 形态（2026-09-16 补）

`expand(node://N)` 只是**离线记号**：生产侧没有任何工具解析它（`offload_read` 已随
「取回面统一到 `Read`」删除）⇒ 只有 `--handle-style read` 的比例才代表「真的换上 WSC」。
形态影响头 token（相对引用 < 绝对引用 < `expand`），所以 `label` 行里打印 `handles=`，
跨形态的 ΣL/Σcost 一律不可相减。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from synaptic.replay import (  # noqa: E402
    _SYSTEM_STANDIN,
    _as_api_message,
    _cache,
    _measure,
    _region_raw_tokens,
    load_jsonl,
    user_turn_starts,
)
from synaptic.types import MODE_CLOSURE, WscParams  # noqa: E402

_MIN_PREFIX_MESSAGES = 8
#: 生产 try_extend_c2 的经济闸参（simulator/params.py 同值）
_EXT_MARGIN = 2.0
_EXT_PRICE_RATIO = 30.0
_MIN_GAIN_CHARS = 4000


# ---------------------------------------------------------------------------
# 臂：一个压缩头的生成器（WSC 热层 / 生产 C2 确定性摘要）
# ---------------------------------------------------------------------------

@dataclass
class Arm:
    name: str
    cursor: int = 0  # 冻结边界（0 = 从未压过）
    head: str = ""  # 冻结头正文
    wsc_state: Any = None  # WSC AssemblyState（跨事件携带日志）
    #: WSC 冷层（**必须与 `wsc_state` 一起跨轮携带**）：头是 append-only 的，
    #: 里面老引用指向的行号只有在视图**只增不改**时才一直有效。每轮新建冷层
    #: 会让视图只含当轮被剪节点 ⇒ 老引用静默指向别的节点
    #: （实测见 `_wsc_out/_stale_ref_probe.py` 与 `ColdStore.write_text_view` 的注释）。
    wsc_cold: Any = None
    x_prev: str = ""  # 上一轮**实际发送**的投影序列化文本
    basis: float = 0.0  # 水位基准 = 上一轮实际发送的 L（生产：vendor last_prompt_tokens）
    events: int = 0
    refreezes: int = 0
    #: 候选头（经济闸要先造后判）：None 表示本回合没有候选
    cand: str | None = None
    cand_state: Any = None
    cand_cold: Any = None
    cand_refroze: bool = False

    @property
    def active(self) -> bool:
        return self.cursor > 0 and bool(self.head)


def _needles_for(prefix: list[dict], region_end: int) -> dict:
    """从**原始历史**收割针（不是头的产物）——「被折叠掉的信息还在不在头里」。

    两侧同一套针集合：图从 `prefix[:region_end]` 建，`region_end` 取该臂自己的
    冻结边界。这样「WSC 头」与「C2 摘要头」面对的是**同一批信息**，可比。
    """
    from synaptic.filestate import build_file_states
    from synaptic.graph import build_graph
    from synaptic.seeds import harvest_needles

    region = prefix[:region_end]
    if not region:
        return {}
    graph = build_graph(region)
    states = build_file_states(graph, region)
    return harvest_needles(graph, states, region_end=region_end)


def _survival(head: str, needles: dict) -> dict:
    from synaptic.metrics import needle_survival

    if not head or not needles:
        return {}
    return needle_survival(head, needles)


def _mk_wsc_candidate(
    arm: Arm,
    prefix: list[dict],
    cut: int,
    *,
    pset: WscParams,
    session: str,
    view_dir: str = "",
    view_ref_base: str = "",
):
    """造 WSC 候选头（不落状态；经济闸拒绝时整份丢弃）。"""
    from engine.compact import project as c0_project
    from synaptic.project import project as wsc_project

    # 生产形态（`handle_style="read"`）：句柄渲染成
    # `Read(file_path=…, offset=…, limit=…)` ⇒ 必须落盘取回视图、并给出引用路径。
    # 引用路径形态会改变头 token（相对 < 绝对 < `expand`），故**形态必须跟着数一起报**。
    view_path = ""
    view_ref = ""
    if str(getattr(pset, "handle_style", "expand")) == "read" and view_dir:
        from pathlib import Path as _Path

        p = _Path(view_dir) / f"{session}.txt"
        view_path = str(p)
        if view_ref_base:
            from memory.offload import ref_path_for

            view_ref = ref_path_for(p, view_ref_base)
        else:
            view_ref = str(p)

    proj = wsc_project(
        prefix,
        region_end=cut,
        params=pset,
        prev=arm.wsc_state,
        cold=arm.wsc_cold,
        session=session,
        region_baseline_tokens=_region_raw_tokens(c0_project(prefix[:cut])),
        view_path=(view_path or None),
        view_ref=view_ref,
    )
    if not proj.result.compressed:
        return False
    arm.cand = proj.text
    arm.cand_state = proj.state
    arm.cand_cold = proj.cold
    arm.cand_refroze = bool(proj.result.journal_refroze)
    return True


def _mk_c2_candidate(arm: Arm, prefix: list[dict], cut: int, *, session: str) -> bool:
    """造生产 C2 候选头：首压=确定性摘要+逃生舱；已压=append-only 扩展（四闸）。"""
    import memory.runtime as rt

    if arm.cursor <= 0:
        head = rt.deterministic_c2_summary(prefix[:cut])
        try:
            hatch = rt.c2_escape_hatch_block(prefix[:cut])
        except Exception:  # noqa: BLE001
            hatch = ""
        if hatch:
            head = head.rstrip() + "\n\n" + hatch
        arm.cand = head
        return True
    w = SimpleNamespace(
        compact_cursor=arm.cursor,
        c2_summary_text=arm.head,
        c1_frozen_until=arm.cursor,
        turns_since_c2=0,
        session_id=session,
    )
    try:
        ok = bool(rt.try_extend_c2(w, prefix, cut, _ext_params(), 16))
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        return False
    arm.cand = w.c2_summary_text
    return True


def _ext_params():
    """try_extend_c2 用的 params（取 simulator 冻结常量，不引生产开关）。"""
    from memory.simulator.params import load_params

    return load_params()


def _region_chars(msgs: list[dict]) -> int:
    from memory.runtime import _region_chars as f

    return f(msgs)


def _region_tokens(msgs: list[dict]) -> int:
    from memory.runtime import _region_tokens as f

    return f(msgs)


# ---------------------------------------------------------------------------
# 触发判据（两个臂共用，保证同节奏）
# ---------------------------------------------------------------------------

def should_fire(
    arm: Arm,
    prefix: list[dict],
    cut: int,
    *,
    cadence: str,
    ratio: float,
    limit: int,
    turn: int = 0,
) -> bool:
    """是否在本回合尝试折叠（= 生产「压一次」）。"""
    if cut <= arm.cursor:
        return False
    if cadence in ("wm80", "wm50", "wm", "watermark"):
        if ratio <= 0 or limit <= 0:
            return False
        return arm.basis >= ratio * limit
    if cadence == "every":
        return True
    if cadence.startswith("everyk:"):
        k = max(1, int(cadence.split(":", 1)[1]))
        return True if arm.events == 0 else (turn % k == 0)
    raise ValueError(f"unknown cadence: {cadence}")


def _cadence_ratio(cadence: str, ratio: float) -> float:
    if cadence == "wm50":
        return 0.5
    return ratio


#: 价格（元/百万 token，`usage/pricing.py` deepseek-v4-flash offpeak）。
#: 折叠的经济学就在这里：省下的是**命中价**（0.05），付出的是**未命中价**（1.5）的一次性代价。
_P_HIT = 0.05
_P_MISS = 1.5


def _tail_project(prefix: list[dict], cursor: int, *, tail_policy: str):
    """尾部投影：两臂**必须同策**，否则比的是尾部政策而不是头。

    - ``c0``：只做 C0（截断/offload）。这是生产**压缩态**的实际形态：
      `memory/runtime.py:223-233` `maybe_advance_aging_boundary` 在
      `compact_cursor > 0` 时**直接 return False**（避免与 C2 同轮抢推边界、
      制造双 miss）⇒ 压缩态的右段基本没有 C1 老化。
    - ``c0c1``：额外把「最后 6 条消息之前」的 tool_result 全部占位
      （与 `memory/simulator/replay.py:422` 的 `c1_frozen = end - KEEP_TAIL_MESSAGES`
      同策，也与 harness 里 v6.1 基线的口径对齐）。

    ⚠️ 两臂不同策时，官方 harness 的 v6.1 列会系统性优于 WSC 臂——那是口径差，
    不是算法差。要回答「换头值不值」必须同策跑。
    """
    from engine.compact import KEEP_TAIL_MESSAGES
    from engine.compact import project as c0_project

    seg = prefix[cursor:]
    if tail_policy != "c0c1":
        return c0_project(seg)
    rel = max(0, (len(prefix) - KEEP_TAIL_MESSAGES) - cursor)
    return c0_project(seg, frozen_until=rel)


def _make_candidate(
    arm: Arm,
    prefix: list[dict],
    cut: int,
    *,
    pset: WscParams,
    session: str,
    view_dir: str = "",
    view_ref_base: str = "",
) -> bool:
    if arm.name == "wsc":
        return _mk_wsc_candidate(
            arm,
            prefix,
            cut,
            pset=pset,
            session=session,
            view_dir=view_dir,
            view_ref_base=view_ref_base,
        )
    if arm.name == "c2":
        return _mk_c2_candidate(arm, prefix, cut, session=session)
    return False


def econ_gate(
    arm: Arm,
    prefix: list[dict],
    cut: int,
    *,
    margin: float = 1.0,
) -> tuple[bool, dict]:
    """折叠的经济闸：**这次折叠摊得平吗？**

    模型（口径写清，别拿结论当推导）：

    - 不折叠：被折叠区以**命中价**每轮继续送（缓存命中 0.05 元/M）⇒ 每轮省 `saved × P_HIT`；
    - 折叠：本轮一次性 miss ≈ 新写进头的行 + 折叠后仍逐字保留的尾部，
      按 `P_MISS`（1.5 元/M）计费一次；
    - 剩余轮次 `R`（`memory.simulator.replay.estimate_remaining`，封顶 24、下限 4）。

    ⇒ 折叠当且仅当 `R × saved × P_HIT ≥ margin × transition × P_MISS`
    （等价于 `R × saved ≥ (P_MISS/P_HIT) × margin × transition = 30·margin·transition`）。

    这与生产 `try_extend_c2` 的第 4 条闸**同源**，但那一版把
    `margin × price_ratio = 60` 直接乘在 transition 上，且 transition 只算
    `新摘要 + 剩余尾部`（不含"被折叠区整段退出前缀"的代价）——两处都偏保守，
    实测表现为 200 回合里只扩展 12 次。本闸按上式重算，`margin` 可扫。
    """
    region_tok = _region_tokens(prefix[arm.cursor : cut]) if cut > arm.cursor else 0
    from synaptic.textutil import node_token_len

    head_delta = max(0, node_token_len(arm.cand or "") - node_token_len(arm.head))
    tail_small = _region_tokens(prefix[cut:])
    saved = max(0, region_tok - head_delta)
    transition = head_delta + tail_small
    from memory.simulator.replay import estimate_remaining

    remaining = estimate_remaining(prefix)
    ok = remaining * saved * _P_HIT >= margin * transition * _P_MISS and region_tok > 0
    return ok, {
        "econ_saved": saved,
        "econ_transition": transition,
        "econ_remaining": remaining,
        "econ_lhs": remaining * saved * _P_HIT,
        "econ_rhs": margin * transition * _P_MISS,
    }


# ---------------------------------------------------------------------------
# 单会话回放
# ---------------------------------------------------------------------------

def replay_duel(
    path: Path,
    *,
    level: str = "Medium+",
    mode: str = MODE_CLOSURE,
    params: WscParams | None = None,
    arms_in: tuple[str, ...] = ("wsc", "c2"),
    cadence: str = "wm80",
    limit: int = 131_072,
    ratio: float = 0.8,
    econ_margin: float = 1.0,
    tail_policy: str = "c0",
    view_dir: str = "",
    view_ref_base: str = "",
) -> tuple[list[dict], str]:
    from memory.simulator.params import load_params
    from memory.simulator.scenarios import state_from_messages
    from memory.runtime import c2_cut_index

    api = [_as_api_message(r) for r in load_jsonl(path)]
    if len(api) < _MIN_PREFIX_MESSAGES:
        return [], "too_short"
    starts = user_turn_starts(api)
    if not starts:
        return [], "no_turns"

    sp = load_params()
    pset = params or WscParams(mode=mode).for_level(level)
    arms = [Arm(name=n) for n in arms_in]
    thr_ratio = _cadence_ratio(cadence, ratio)

    rows: list[dict] = []
    v61 = _v61_rows(api, path.stem, sp)

    for t, start in enumerate(starts):
        end = starts[t + 1] if t + 1 < len(starts) else len(api)
        prefix = api[:end]
        if len(prefix) < _MIN_PREFIX_MESSAGES:
            continue
        cut = c2_cut_index(prefix, None)
        if cut <= 1:
            continue

        needle_cache: dict[int, dict] = {}
        for arm in arms:
            fired = False
            refroze = False
            econ: dict = {}
            attempt = cut > arm.cursor and (
                cadence == "econ"
                or should_fire(
                    arm, prefix, cut, cadence=cadence, ratio=thr_ratio, limit=limit, turn=t
                )
            )
            if attempt:
                arm.cand = None
                arm.cand_state = None
                arm.cand_cold = None
                arm.cand_refroze = False
                made = _make_candidate(
                    arm,
                    prefix,
                    cut,
                    pset=pset,
                    session=path.stem,
                    view_dir=view_dir,
                    view_ref_base=view_ref_base,
                )
                if made and cadence == "econ":
                    ok, econ = econ_gate(arm, prefix, cut, margin=float(econ_margin))
                    made = ok
                if made:
                    arm.cursor = cut
                    arm.head = arm.cand or arm.head
                    if arm.name == "wsc":
                        arm.wsc_state = arm.cand_state
                        arm.wsc_cold = arm.cand_cold
                    arm.events += 1
                    refroze = bool(arm.cand_refroze)
                    arm.refreezes += int(refroze)
                    fired = True

            if arm.active:
                tail = _tail_project(prefix, arm.cursor, tail_policy=tail_policy)
                sim_state = state_from_messages(tail, cursor=0, system=arm.head)
            else:
                sim_state = state_from_messages(
                    _tail_project(prefix, 0, tail_policy=tail_policy),
                    cursor=0,
                    system=_SYSTEM_STANDIN,
                )
            pr, spl, cost = _measure(sim_state, _cache(sp, arm.x_prev), sp)
            arm.basis = float(pr.length)
            arm.x_prev = pr.x
            surv: dict = {}
            if arm.active:
                if arm.cursor not in needle_cache:
                    needle_cache[arm.cursor] = _needles_for(prefix, arm.cursor)
                surv = _survival(arm.head, needle_cache[arm.cursor])
            rows.append(
                {
                    "session": path.stem,
                    "turn": t,
                    "arm": arm.name,
                    "n_messages": len(prefix),
                    "cut": cut,
                    "cursor": arm.cursor,
                    "active": bool(arm.active),
                    "fired": fired,
                    "refroze": refroze,
                    "L": int(pr.length),
                    "H": float(spl.H),
                    "hit": float(spl.H) / max(1.0, float(pr.length)),
                    "head_tokens": int(pr.p_end),
                    "lcp": int(spl.lcp),
                    "cost": float(cost),
                    "needle": surv,
                    **econ,
                    "v61_tokens": int(v61[t]["L"]) if t < len(v61) else 0,
                    "v61_hit": float(v61[t]["hit"]) if t < len(v61) else 0.0,
                    "v61_cost": float(v61[t]["cost"]) if t < len(v61) else 0.0,
                }
            )
    return rows, ""


def _v61_rows(api: list[dict], stem: str, sp) -> list[dict]:
    """生产 v6.1 基线（simulator 自决节奏），只作参考臂。"""
    from memory.simulator.replay import replay_messages

    try:
        turns = list(replay_messages(api, session_id=stem, params=sp).turns)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for bt in turns:
        l = max(1.0, float(bt.v61_tokens))
        out.append(
            {
                "L": int(bt.v61_tokens),
                "hit": float(bt.predicted_hit) / l,
                "cost": float(bt.simulated_cost),
            }
        )
    return out


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def _f(x: float, n: int = 4) -> str:
    return f"{x:.{n}f}"


def summarize(rows: list[dict], label: str) -> list[str]:
    if not rows:
        return [f"{label}: (无回合)"]
    arms = sorted({r["arm"] for r in rows})
    by_arm: dict[str, list[dict]] = {a: [r for r in rows if r["arm"] == a] for a in arms}
    out = [f"== {label} ==", f"  回合 {len(by_arm[arms[0]])}（每臂）"]
    stats: dict[str, tuple[int, int, float, float, int, int]] = {}
    for a in arms:
        rs = by_arm[a]
        sl = sum(r["L"] for r in rs)
        sh = sum(r["H"] for r in rs)
        sc = sum(r["cost"] for r in rs)
        ev = sum(1 for r in rs if r["fired"])
        act = sum(1 for r in rs if r["active"])
        stats[a] = (sl, sh, sc, ev, act, 0)
        out.append(
            f"  {a:<4} ΣL={sl:>9}  ΣH={sh:>9.0f}  hit={_f(sh / max(1.0, sl))}  "
            f"Σcost=¥{sc:.4f}  事件={ev}  紧凑态回合={act}（{act / len(rs):.1%}）"
        )
    if "wsc" in stats and "c2" in stats:
        w, c = stats["wsc"], stats["c2"]
        out.append(
            f"  ⇒ **cost ratio WSC/C2 = {_f(w[2] / c[2] if c[2] else float('nan'))}**   "
            f"L 比 {_f(w[0] / c[0] if c[0] else float('nan'))}   "
            f"hit 差 {_f(w[1] / max(1, w[0]) - c[1] / max(1, c[0]))}"
        )
        out.append(
            f"  成本指数（∝30L−29H）：WSC {30 * w[0] - 29 * w[1]:.0f}   "
            f"C2 {30 * c[0] - 29 * c[1]:.0f}"
        )
    # 信息针：**汇总池化**（Σhit/Σn），不取「有样本回合」的均值——避免分母伪影
    cats = sorted({c for r in rows for c in (r.get("needle") or {})})
    if cats:
        out.append("  信息针（池化 Σhit/Σn，头内命中）：")
        for cat in cats:
            cells = []
            for a in arms:
                hit = sum(int((r.get("needle") or {}).get(cat, {}).get("hit", 0)) for r in by_arm[a])
                n = sum(int((r.get("needle") or {}).get(cat, {}).get("n", 0)) for r in by_arm[a])
                cells.append(f"{a}={hit / n:.4f}(n={n})" if n else f"{a}=—")
            out.append(f"    {cat:<14} " + "  ".join(cells))
    return out


def _duel_worker(payload: tuple[str, dict]) -> list[dict]:
    """ProcessPoolExecutor 的 worker —— 必须是模块级、可 pickle 的纯函数。"""
    path_str, kw = payload
    rows, _deg = replay_duel(Path(path_str), **kw)
    return rows


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    positional: list[str] = []
    kv: dict[str, str] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key, _, inline = a.partition("=")
            if inline:
                kv[key] = inline
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                kv[key] = argv[i + 1]
                i += 1
            else:
                kv[key] = "1"
        else:
            positional.append(a)
        i += 1
    if not positional:
        print(__doc__)
        return 2

    def opt(name: str, default: str) -> str:
        return kv.get(name, default)

    target = Path(positional[0])
    mode = opt("--mode", MODE_CLOSURE)
    level = opt("--level", "Medium+")
    cadence = opt("--cadence", "wm80")
    limit = int(opt("--limit", "131072"))
    ratio = float(opt("--ratio", "0.8"))
    arms_in = tuple(a.strip() for a in opt("--arms", "wsc,c2").split(",") if a.strip())
    econ_margin = float(opt("--econ-margin", "1.0"))
    tail_policy = opt("--tail", "c0")
    max_sessions = int(opt("--sessions", "0"))
    max_turns = int(opt("--turns", "0"))
    dump = opt("--dump", "")
    # 句柄形态（**必须跟着数一起读**）：`expand`（历史形态，无生产解析器）对
    # `read`（生产形态：`Read(file_path=…, offset=…, limit=…)`，需视图目录）。
    # 两臂尾部/切点不变、只换头 ⇒ 与「同节奏对撞」的口径一致。
    handle_style = opt("--handle-style", os.environ.get("XEYO_WSC_HANDLE_STYLE", "expand") or "expand")
    view_dir = opt("--view-dir", os.environ.get("XEYO_WSC_VIEW_DIR", ""))
    view_ref_base = opt("--view-ref-base", os.environ.get("XEYO_WSC_VIEW_REF_BASE", ""))

    files = sorted(target.glob("*.jsonl")) if target.is_dir() else [target]
    if max_sessions:
        files = files[:max_sessions]
    pset = WscParams(mode=mode).for_level(level)
    if handle_style == "read":
        import dataclasses as _dc

        pset = _dc.replace(pset, handle_style="read")

    all_rows: list[dict] = []
    kw = dict(
        level=level,
        mode=mode,
        params=pset,
        arms_in=arms_in,
        cadence=cadence,
        limit=limit,
        ratio=ratio,
        econ_margin=econ_margin,
        tail_policy=tail_policy,
        view_dir=view_dir,
        view_ref_base=view_ref_base,
    )
    jobs = max(1, int(opt("--jobs", "1")))
    if jobs > 1 and len(files) > 1:
        from concurrent.futures import ProcessPoolExecutor

        print(f"  (并行 jobs={jobs} over {len(files)} sessions)", file=sys.stderr)
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            for rows in ex.map(_duel_worker, [(str(f), kw) for f in files], chunksize=1):
                all_rows.extend(rows)
    else:
        for f in files:
            rows, _deg = replay_duel(f, **kw)
            if len(files) == 1 and rows:
                print(
                    "  turn | arm | act | fire |    L    |   H    |  hit   | head  | "
                    "lcp   |   cost  | v61_L  | v61_hit"
                )
                shown = [r for r in rows if r["turn"] < max_turns] if max_turns else rows
                for r in shown:
                    print(
                        f"  {r['turn']:>4} | {r['arm']:<3} |  {'Y' if r['active'] else '.'}  |  "
                        f"{'Y' if r['fired'] else '.'}   | {r['L']:>7} | {r['H']:>6.0f} | "
                        f"{_f(r['hit'])} | {r['head_tokens']:>5} | {r['lcp']:>5} | "
                        f"{r['cost']:>7.4f} | {r['v61_tokens']:>6} | {_f(r['v61_hit'])}"
                    )
                print()
            all_rows.extend(rows)

    label = (
        f"{target.name}  mode={mode}  cadence={cadence}  tail={tail_policy}  "
        f"水位={ratio if cadence != 'wm50' else 0.5}×{limit}  arms={','.join(arms_in)}"
        f"  handles={handle_style}"
        + (f"（ref={view_ref_base or view_dir}）" if handle_style == "read" else "")
        + f"  margin={econ_margin}"
    )
    for line in summarize(all_rows, label):
        print(line)

    if dump:
        out = Path(dump)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for r in all_rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  turns -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
