"""wsc_shadow — 阶段 B：突触压缩（WSC）**影子档**（只观察，不生效）。

## 定位

WSC 是旁路包（`python/synaptic/`，算法层对生产链零 import）。并入主链（docs
`synaptic-compression.md` 阶段 C）之前，必须先拿到**真实分布下**的影子数据。
本模块就是那个影子：**接线点只有一处**（`engine/query_loop.py` 投影出口），
**绝不改变实际发送的投影**，只把「若改用 WSC，这一轮会长什么样」记账落盘。

## 开关

- `XEYO_WSC=1` 开启。**默认关**（`memory_switches` 注册键，GUI 可切换；切换时
  `server/routers/control.py` 立即 `apply_to_environ`，不必重启）。
  本模块 `enabled()` 走 **strict_env**（只读自己的环境变量），与注册表并存的原因：
  - 注册表给的是**权威面 + GUI 开关**（`apply_to_environ` 把 settings 桥接进 env）；
  - 若改走 `side_enabled()`：未注册时回退 `sidemod_promote()`（全局升格默认 **开**）
    ⇒ 实测 `enabled()`=True，影子会在用户毫不知情时开始花 CPU（已写回归测试）；
  - 若只认 `get_value()`：该函数契约是「settings 唯一权威、**环境变量一律不参与**」
    ⇒ 命令行 `XEYO_WSC=1` 静默失效。strict_env + 注册表两个入口都通，故取此组合。
- `XEYO_WSC_SAMPLE`：每个会话最多记多少轮（默认 6）。影子要算一次 WSC 投影
  （O(区域)）——**不采样就会把热路径拖慢**，这是刻意的成本闸。
- `XEYO_WSC_MIN_MESSAGES`：低于该消息数的会话不算（默认 24；短会话本来不该压，
  docs §11.4 第 2 条）。

## 红线（违反即回退）

1. **不改发送**：入参投影只读；本模块无返回值，调用方拿不到任何可影响发送的东西。
2. **fail-open**：任何异常一律吞掉（影子档绝不能挡住主链）。
3. **有界**：每会话采样上限 + 每次只算一轮 + 产物 append 到单一 JSONL。
4. **可整目录删除**：删掉本模块 + 那行接线即可回到现状，不留残根。

## 产物

`<home>/.xeyo/wsc_shadow.jsonl`，每行一轮：

```json
{"ts": 1757..., "session": "sess_x", "turn": 12, "n_messages": 812,
 "actual_tokens": 41233, "wsc_hot_tokens": 3111, "wsc_tokens": 8902,
 "cut": 800, "region_raw_tokens": 39411, "fold": true, "saved": 36300,
 "transition": 4100, "remaining": 16, "reason": "worth_fold",
 "needles": {"user": {"n": 3, "hit": 3, "rate": 1.0}, ...},
 "recover": {"coverage": 1.0, "lossless_rate": 1.0},
 "latency_ms": 41.2, "error": ""}
```

## 口径限制（用它做结论前必读）

1. **本档每轮独立投影**（不传 `prev=` / `cold=`）⇒ 记的是「这一轮从零重算会长什么样」，
   头 token 不含日志累积的那部分；生产头部会比它**略大**。跨轮正确性另有约束（见下）。
2. **`actual_tokens` 只在活流量里有**（离线收割档没有「实际发送的那一枪」）⇒
   「比现状省多少」永远以官方 harness（`--compact-model adopted`）为准，两处不可互换。
3. **形态跟着数走**：`handle_style` / `view_path` / `view_ref` / `view_externalized`
   都逐行落盘，跨形态的 token 与成本**不可相减**（`read` 的引用比 `expand(node://N)` 长）。

## 接线要求（阶段 C 落地时必读，两条都有实测证据）

1. **冷层必须与 `AssemblyState` 一起跨轮携带**（`project(..., prev=state, cold=cold)`）。
   头是 append-only 的日志、老行一直在；取回视图却是重写的 ⇒ 只带状态不带冷层时，
   后续轮次会把**更小 idx** 的节点插进视图前面，行号整体平移，
   **头里那批老引用静默指向别的节点**（引用自洽、能取回内容，只是内容是别的节点）。
   实测：1047 条引用样本里 115 条漂移；两条都做（携带冷层 + 视图按插入序排块）后为 0。
   回归锁：`tests/wsc/test_handle_style.py::test_cross_turn_refs_keep_pointing_at_their_nodes`。
2. **视图必须落在 `<ws>/.xeyo_offload/` 下**，否则 `Read` 的 read-state 豁免失效
   （见 `view_path_for` 的三条约束）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("xeyo.memory.wsc_shadow")

_ENV = "XEYO_WSC"
_ENV_SAMPLE = "XEYO_WSC_SAMPLE"
_ENV_MIN_MESSAGES = "XEYO_WSC_MIN_MESSAGES"

_DEFAULT_SAMPLE = 6
_DEFAULT_MIN_MESSAGES = 24

#: 每会话已记账轮数（进程内、有界；键为 session_id）。
_seen: dict[str, int] = {}


def enabled() -> bool:
    """是否开启影子档：**strict_env，默认关**（不注册、不吃全局升格默认）。

    为什么不用 `sidecar.policy.side_enabled`：它对本键的两条回退都会造成事故——
    ①未注册 → 回退 `sidemod_promote()`（默认开）⇒ 影子在用户不知情时开始花 CPU；
    ②注册 → `get_value` 的「settings 唯一权威、env 一律不参与」会让 `XEYO_WSC=1`
    静默失效。见模块文档「开关」一节。
    """
    return os.environ.get(_ENV, "").strip().lower() in ("1", "true", "on", "yes")


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


def log_path() -> Path:
    base = os.environ.get("XEYO_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".xeyo"
    return root / "wsc_shadow.jsonl"


def reset_for_tests() -> None:
    """清空每会话计数（测试用；生产无调用方）。"""
    _seen.clear()


def maybe_observe(
    messages: list[dict[str, Any]],
    *,
    session_id: str = "",
    projected: list[dict[str, Any]] | None = None,
    context_limit: int | None = None,
    cwd: str = "",
) -> None:
    """记一轮影子账目。**无返回值**——调用方无法据此改动发送内容。

    `projected` = 本轮**实际发送**的投影（只读，用于同口径对照）。
    `cwd` = **读取方自己的工作区**（会话 registry 的 cwd），用于把取回视图落进
    `<ws>/.xeyo_offload/`（不传则退到进程 cwd —— 两者在生产里相等，别处不保证）。

    ⚠️ 早期版本收的是调用方算好的 `actual_tokens`（`Σ token_len(str(content))`）——
    那个口径与 `wsc_tokens` **不是同一把尺**：列表型 content 会带上 Python repr，
    实测在 3 条真实会话 × 2 个长度点上膨胀 **1.31–3.40 倍**（textarea 型会话反而
    偏小 0.88–0.95）。⇒ 现在两个数都由本模块用同一套 `message_text + node_token_len`
    计算（`raw_tokens` = 整段原文，`actual_tokens` = 实际投影）。
    """
    if not enabled():
        return
    try:
        _observe_inner(
            messages,
            session_id=session_id,
            projected=projected,
            context_limit=context_limit,
            cwd=cwd,
        )
    except Exception:  # noqa: BLE001 — 红线 2：影子档绝不挡主链
        _log.debug("wsc shadow failed", exc_info=True)


def view_path_for(cwd: str, session_id: str) -> Path:
    """影子档的取回视图路径。**三个约束，缺一条就是事故**：

    1. **必须落在 offload 根下**（`<ws>/.xeyo_offload/`，或 `XEYO_OFFLOAD_DIR` 覆盖）：
       否则 `memory/offload.py::is_externalized_path` 判不出来，`Read` 的
       read-state 豁免失效 ⇒ 取回会写 `FileStateEntry`（挤掉正在编辑的真文件快照、
       同区间重复读被 `FILE_UNCHANGED_STUB` 顶掉正文）。docs §15.16.4/§15.16.6。
    2. **`cwd` 用读取方自己的工作区**，不是进程 cwd（两者在生产里相等，别处不保证）。
    3. **与生产视图路径不同路径**（子目录 `wsc-shadow/`）：影子档的切点与生产**不同**
       （`region_end` 取未 pair-safe 的原值 vs 生产 `c2_cut_index`）⇒ 若共用同一文件，
       影子的写入会覆盖生产头部那些 `Read(offset=…)` 的行号，**生产头部的引用会静默
       指向错内容**（比没有引用严重得多）。这条是接线期最容易踩的一脚。
    """
    from memory.offload import _offload_root

    return _offload_root(cwd or None) / "wsc-shadow" / f"{_safe(session_id)}.txt"


def _wsc_read_calls(
    messages: list[dict[str, Any]], view_path: Path, cwd: str
) -> tuple[int, int]:
    """返回当前历史中对该 WSC 视图的 ``(Read 调用数, 调用消息数)``。

    影子阶段不会把 WSC 头发给模型，故通常为 0；阶段 C 接线后，同一函数用
    已落在转录里的 ``tool_use`` 事实计算真实取回率。相对路径按读取方工作区解析，
    与 `Read` 的路径语义一致。
    """
    try:
        target = view_path.resolve(strict=False)
    except OSError:
        return 0, 0
    base = Path(cwd) if cwd else Path.cwd()
    calls = 0
    turns = 0
    for msg in messages:
        if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
            continue
        matched = False
        for block in msg["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Read":
                continue
            inp = block.get("input")
            raw = inp.get("file_path") if isinstance(inp, dict) else None
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = base / candidate
            try:
                if candidate.resolve(strict=False) == target:
                    calls += 1
                    matched = True
            except OSError:
                continue
        turns += int(matched)
    return calls, turns


def _safe(s: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "x")[:40]


def _observe_inner(
    messages: list[dict[str, Any]],
    *,
    session_id: str,
    projected: list[dict[str, Any]] | None,
    context_limit: int | None,
    cwd: str = "",
) -> None:
    cap = _int_env(_ENV_SAMPLE, _DEFAULT_SAMPLE)
    if cap <= 0:
        return
    min_msgs = _int_env(_ENV_MIN_MESSAGES, _DEFAULT_MIN_MESSAGES)
    if len(messages) < min_msgs:
        return
    key = session_id or "-"
    if _seen.get(key, 0) >= cap:
        return

    from engine.compact import keep_tail_cut
    from memory.offload import is_externalized_path, ref_path_for
    from memory.runtime import c2_cut_index
    from synaptic.cadence import CadenceState, estimate_remaining
    from synaptic.metrics import exposed_handles, needle_survival, recoverability
    from synaptic.project import project as wsc_project
    from synaptic.replay import _region_raw_tokens
    from synaptic.seeds import harvest_needles
    from synaptic.textutil import node_token_len
    from synaptic.types import WscParams

    # `handle_style="read"`：影子探的就是**生产形态**（热层句柄渲染成
    # `Read(file_path=…, offset=…, limit=…)`）。形态会让热层 token 变化（引用比
    # `expand(node://N)` 长）⇒ 影子必须用生产形态量，否则量的是另一条链路。
    pset = WscParams(
        mode="closure", fold_cadence="econ", handle_style="read"
    ).for_level("Medium+")
    view_path = view_path_for(cwd, session_id)
    # 引用路径（渲染进热层的那个）：工作区相对路径优先——绝对路径在**每个句柄**上重复一次，
    # 实测热层 token +41.6% / 总成本 +7.25%（同语料 A/B，见 offload.ref_path_for 的表）。
    # 判不出相对（cwd 未知 / 视图不在工作区下）时自动回落绝对路径。
    view_ref = ref_path_for(view_path, cwd)
    # 切点用**生产 C2 的同一个**（`c2_cut_index` = pair_safe_cut(keep_tail_cut)），
    # 这样影子账目与「真的换成 WSC」可比；region_end 用未 pair-safe 的原值。
    cut = int(c2_cut_index(messages, None))
    if cut <= 1:
        return
    region_end = int(keep_tail_cut(messages))
    if region_end <= 1:
        return

    t0 = time.perf_counter()
    proj = wsc_project(
        messages,
        region_end=region_end,
        params=pset,
        session=session_id,
        view_path=view_path,
        view_ref=view_ref,
    )
    dt_ms = (time.perf_counter() - t0) * 1000.0

    cadence = CadenceState(
        head_delta_cap=int(pset.hot_budget_tokens) + int(pset.journal_growth_tokens)
    )
    region_tok = _region_raw_tokens(messages[:region_end])
    tail_tok = _region_raw_tokens(messages[region_end:])
    # 同口径对照：两个数都用 `message_text + node_token_len`（= `_region_raw_tokens` 的口径），
    # 与 `wsc_tokens` 可直接相减。理由见 `maybe_observe` 的口径警示。
    raw_tokens = region_tok + tail_tok
    actual_tokens = _region_raw_tokens(projected) if projected is not None else 0
    dec = cadence.decide(
        region_tokens_=region_tok,
        tail_tokens_=tail_tok,
        remaining_turns=estimate_remaining(messages),
        margin=pset.fold_margin,
        price_ratio=pset.fold_price_ratio,
    )

    needles: dict[str, Any] = {}
    try:
        needles = needle_survival(
            proj.text,
            harvest_needles(proj.graph, {}, region_end=region_end),
        )
    except Exception:  # noqa: BLE001
        needles = {}
    recover: dict[str, Any] = {}
    try:
        recover = recoverability(proj)
    except Exception:  # noqa: BLE001
        recover = {}
    retrieval_calls, retrieval_turns = _wsc_read_calls(messages, view_path, cwd)

    row = {
        "ts": time.time(),
        "session": session_id,
        "n_messages": len(messages),
        #: 实际发送的投影 token（**与 wsc_tokens 同口径**，可直接比）
        "actual_tokens": int(actual_tokens),
        #: 整段原文 token（同口径；WSC 压缩率的分母）
        "raw_tokens": int(raw_tokens),
        "wsc_hot_tokens": node_token_len(proj.text),
        "wsc_tokens": int(node_token_len(proj.text) + tail_tok),
        "cut": cut,
        "region_end": region_end,
        "region_raw_tokens": region_tok,
        "tail_tokens": tail_tok,
        "compressed": bool(proj.result.compressed),
        # ── 取回面（暴露量）：与真实会话里的**使用量**配对，才算「取回率」的证据 ──
        # 取回接口 = `Read`（2026-09-16 用户裁定：expand/offload/Read 是同一功能，
        # 专用工具 `offload_read` 已删除；冷层引用渲染成
        # `Read(file_path=…, offset=…, limit=…)`，见 `synaptic/coldstore.py::read_ref`）。
        "handles_exposed": int(exposed_handles(proj)),
        # 阶段 C 后的真实取回观测；影子阶段为 0 是预期，不可解释成“模型不需要取回”。
        "retrieval_calls": retrieval_calls,
        "retrieval_turns": retrieval_turns,
        # 句柄形态与取回视图必须留痕：跨形态的热层 token 不可混用，而
        # `view_externalized=False` 表示视图没落在 offload 根下 ⇒ **read-state 豁免失效**
        # （应当立刻修接线，别拿这份影子数据当基线）。
        "handle_style": str(pset.handle_style),
        "view_path": str(view_path),
        #: 热层里**渲染**出来的引用路径（相对形态省 token；与 `view_path` 的关系见
        #: `memory/offload.py::ref_path_for`）
        "view_ref": str(view_ref),
        "view_externalized": bool(is_externalized_path(view_path, cwd)),
        "nodes_pruned": len(proj.result.hot.pruned_nodes),
        "nodes_kept": len(proj.result.hot.kept_nodes),
        "cards": len(proj.result.hot.cards),
        "fold": bool(dec.fold),
        "saved": dec.saved,
        "head_delta": dec.head_delta,
        "transition": dec.transition,
        "remaining": dec.remaining,
        "reason": dec.reason,
        "context_limit": int(context_limit or 0),
        # 阶段 C 准入条件之一「shadow 里 PIN 超预算率 < 5%」靠这两项算：
        "budget": dict(proj.result.budget or {}),
        "needles": needles,
        "recover": recover,
        "latency_ms": round(dt_ms, 3),
        "error": "",
    }
    _append(row)
    _seen[key] = _seen.get(key, 0) + 1


def _append(row: dict[str, Any]) -> None:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
