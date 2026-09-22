"""WSC live projection (stage C).

C2 remains the trigger; WSC becomes the execution projection.  The module is
fail-open: when the switch is off, the region is too small, the gain gate
declines, or any error occurs, the caller keeps the existing C2 projection.

Two caller-side policies live here because WSC's algorithm layer never reads them:

* ``XEYO_WSC_FROZEN_HEAD`` (default on) -- between fold events the head is reused
  byte-for-byte, so the emitted prompt only ever appends.
* ``XEYO_WSC_CADENCE_ABSORB`` (default **off**) -- when on, *when* the right segment gets
  absorbed into the head is decided by ``synaptic.cadence`` (cost economics) instead of
  waiting for the caller's next fold event.
  Floor: ``journal_growth_tokens``.  Measured 2026-09-22 on three production transcripts
  (47 request boundaries): with ``PAYBACK_SHOTS=8`` the economic gate approved **0 of 43**
  decisions (34 refused as ``pays_back_too_slow``, 9 still in cooldown) -- the live floor
  folds shallow regions (15~65% of the emission) whose measured payback is 12~238 shots,
  so the gate only ever vetoes.  Total modelled cost vs the frozen-head default: 1.036x.
  It stays opt-in until a live smoke run decides it.
  2026-09-22 update: ``PAYBACK_SHOTS`` moved 8 -> 30 (= "this shot's net saving must cover
  this shot's resend face"), and ``memory.runtime.try_extend_c2`` now enforces that same
  criterion on the cursor push for **both** arms.  So this flag would be re-tuning a gate
  that already fires on the identical rule -- its 1.036x measurement predates the change
  and has to be re-run before the flag can be considered again.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from typing import Any

_log = logging.getLogger(__name__)
_ENV = "XEYO_WSC"
#: 头冻结（kill switch，默认开）。关掉 = 回到"每枪重投影、交界每枪前移"的历史行为。
_FREEZE_ENV = "XEYO_WSC_FROZEN_HEAD"
#: 吸收节奏（**默认关**，等真冒烟数据裁定）：开了就由 ``synaptic.cadence`` 的成本判据
#: 决定何时把右段折进头，而不是等调用方下一次折叠事件。
_ABSORB_ENV = "XEYO_WSC_CADENCE_ABSORB"


@dataclasses.dataclass
class _Live:
    """单会话活路径状态。原来是 6 元组按位置解包，读的人只能靠记序。"""

    prev: Any = None
    cold: Any = None
    n_messages: int = 0
    region_end: int = 0
    cursor: int = 0
    head: str = ""
    cadence: Any = None
    #: 这个会话被服务过几枪 / 当前这份头是第几枪建的。二者之差就是**索引新鲜度**
    #: （头不重建 ⇒ 头里所有索引段一起变旧）。实测 GUI 流量 125 枪才折一次，
    #: 所以"索引占比"这个旧口径量的是"多久没折"，不是"索引胖"。
    shots: int = 0
    head_shot: int = 0
    #: 这份头的句柄面占用（tok）与它活着期间被引用了几次 —— ③ 的取数点。
    handle_tokens: int = 0
    handle_refs: int = 0


_STATE: dict[str, _Live] = {}
_MAX_STATE = 64


def _flag_on(name: str) -> bool:
    """布尔旗标的唯一判据 —— 与 ``memory_switches.env_flag`` 同一份。

    以前这里三个读法两套字面量（`XEYO_WSC` 只认 1/true/on/yes，`FROZEN_HEAD` 反过来
    "不在关字面量里就算开"），而报账走注册表的 allowed ⇒ 同一个 env 值可以"运行时开、
    账面关"。收成一个函数后，注册表报的就是这里读的。
    """
    from memory.memory_switches import env_flag

    return env_flag(name)


def live_enabled() -> bool:
    return _flag_on(_ENV)


def freeze_enabled() -> bool:
    return _flag_on(_FREEZE_ENV)


def absorb_gated_enabled() -> bool:
    return _flag_on(_ABSORB_ENV)


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value or "x")[:64]


def _view_path_for(cwd: str, session_id: str):
    from memory.offload import _offload_root

    return _offload_root(cwd or None) / "wsc" / f"{_safe(session_id)}.txt"


def production_params() -> "Any":
    """WSC 生产档的**唯一配置来源**。

    存在的理由：离线评测台（``evals/wsc_failure_judge.py``）原先自己抄了一份
    ``default_params("Medium+", "closure")``，于是它量的其实是
    ``fold_cadence=always`` + ``handle_style=expand``、且**每回合无状态重投**的投影，
    而不是生产发出的那一个（实测热层中位数 2,467 vs 生产口径 10,234 tok）。
    评测台与被评对象配置不一致，报出来的差异就说不清是谁的。
    生产改档只改这里，评测自动跟上。
    """
    from synaptic.types import WscParams

    return WscParams(
        mode="closure", fold_cadence="econ", handle_style="read"
    ).for_level("Medium+")


def _head_msg(text: str) -> dict:
    return {"role": "assistant", "content": text, "name": "session_summary"}


def _emit(head: str, messages: list[dict], base: int, frozen_attr: int, *, cwd) -> list[dict]:
    from engine.compact import project as project_c0c1

    return [_head_msg(head)] + project_c0c1(
        messages[base:], frozen_until=max(0, frozen_attr - base), cwd=cwd
    )


def project_c2_messages(messages: list[dict], working, *, cwd=None) -> list[dict] | None:
    if not live_enabled():
        return None
    try:
        from engine.compact import keep_tail_cut
        from memory.offload import ref_path_for
        from synaptic.cadence import CadenceState
        from synaptic.project import project as wsc_project
        from synaptic.replay import _region_raw_tokens
        from synaptic.textutil import node_token_len

        session = str(getattr(working, "session_id", "") or "-")
        cursor = int(getattr(working, "compact_cursor", 0) or 0)
        frozen_attr = int(getattr(working, "c1_frozen_until", 0) or 0)
        params = production_params()

        # 可吸收上界：调用方游标之上、keep_tail_cut 之内，并且**落在 pair-safe 切点**
        # （不拆散 assistant tool_use 与它的 tool_result —— 那会直接造出 400 形状）。
        upper = min(len(messages), max(int(keep_tail_cut(messages)), cursor))
        try:
            from memory.runtime import c2_cut_index

            pair_safe = int(c2_cut_index(messages, None))
            if 1 < pair_safe < upper:
                upper = pair_safe
        except Exception:  # noqa: BLE001 - 拿不到就用原切点，绝不阻塞投影
            _log.debug("c2_cut_index unavailable; boundary not snapped", exc_info=True)
        if upper <= 1:
            return None

        key = _state_key(session, cwd)
        cached = _STATE.get(key)
        if cached is not None and (
            len(messages) < cached.n_messages
            or cached.cursor > cursor
            or upper < cached.region_end
        ):
            cached = None  # 回滚 / 游标倒退 ⇒ 连冻结头一起作废

        moved = cached is None or cursor > cached.cursor       # 真发生了折叠/扩展事件
        grow = cached is not None and upper > cached.region_end  # 右段长大了，可吸收
        # 谁来决定吸收：默认**只有折叠事件**推进交界（B 档）；开节奏判据后由成本经济性
        # 决定"右段攒到值得折一次"（C 档）；两个开关都关 = 每枪都推进（A 档 = 历史行为）。
        region_tok = 0
        dec = None
        absorb = moved
        if grow and not absorb and absorb_gated_enabled():
            region_tok = int(_region_raw_tokens(messages[cached.region_end:upper]))
            if cached.cadence is None:
                cached.cadence = CadenceState(
                    head_delta_cap=int(params.hot_budget_tokens)
                    + int(params.journal_growth_tokens)
                )
            dec = cached.cadence.decide(
                region_tokens_=region_tok,
                tail_tokens_=int(_region_raw_tokens(messages[upper:])),
                margin=params.fold_margin,
                price_ratio=params.fold_price_ratio,
            )
            # 保底：待吸收区已长过一个头的增长周期 ⇒ 不划算也得折（尾巴不能无限长）
            absorb = bool(dec.fold) or region_tok >= int(params.journal_growth_tokens)

        if cached is not None and cached.head and not absorb and freeze_enabled():
            # 头字节原样复用 + 右段只追加 ⇒ 整份发射是上一枪的前缀扩展。
            # 反面形状被生产实测过：交界每枪前移 ⇒ 头之后全重排，
            # 厂商 cache_hit 99.8%→55.6%、每请求成本 ¥9.23m→¥21.11m（2.3 倍）。
            _reuse_frozen(cached, messages)
            return _emit(cached.head, messages, cached.region_end, frozen_attr, cwd=cwd)

        view_path = _view_path_for(_cwd_of(cwd), session)
        proj = wsc_project(
            messages,
            region_end=upper,
            params=params,
            prev=cached.prev if cached is not None else None,
            cold=cached.cold if cached is not None else None,
            session=session,
            region_baseline_tokens=int(_region_raw_tokens(messages[:upper])),
            view_path=view_path,
            view_ref=ref_path_for(view_path, os.environ.get("XEYO_CWD") if cwd is None else str(cwd) or None),
        )
        if not proj.result.compressed:
            # 收益门拒了本次折叠 ⇒ 绝不能返回 None。返回 None 会让调用方回退 C2 本体，
            # 那等于把已冻结的头整段换掉（前缀全废），比"这次不折"糟糕得多。
            if cached is not None and cached.head and freeze_enabled():
                _reuse_frozen(cached, messages)
                return _emit(cached.head, messages, cached.region_end, frozen_attr, cwd=cwd)
            return None

        if dec is not None and cached is not None and cached.cadence is not None:
            cached.cadence.observe_fold(
                region_tokens_=region_tok,
                head_delta_tokens=max(
                    0, node_token_len(proj.text) - node_token_len(cached.head)
                ),
                # 只有头被沿用才算 carry_over；首折/整层重冻结的 delta 是整个新头
                carried_over=bool(cached.head and not proj.result.rebuilt),
            )
        if cached is not None:
            _note_head_usage(session, cached)   # 旧头退场前补一条取回账
        if len(_STATE) >= _MAX_STATE and key not in _STATE:
            _STATE.pop(next(iter(_STATE)))
        shot = (cached.shots if cached is not None else 0) + 1
        handle_tok = 0
        try:
            handle_tok = int((proj.result.budget or {}).get("handle_tokens") or 0)
        except Exception:  # noqa: BLE001 - 观测字段，拿不到就算了
            handle_tok = 0
        _STATE[key] = _Live(
            prev=proj.state,
            cold=proj.cold,
            n_messages=len(messages),
            region_end=upper,
            cursor=cursor,
            head=proj.text,
            cadence=(cached.cadence if cached is not None
                     else CadenceState(head_delta_cap=int(params.hot_budget_tokens)
                                       + int(params.journal_growth_tokens))),
            shots=shot,
            head_shot=shot,
            handle_tokens=handle_tok,
        )
        return _emit(proj.text, messages, upper, frozen_attr, cwd=cwd)
    except Exception:  # noqa: BLE001 - WSC must never block the projection
        _log.debug("wsc live projection failed; falling back to C2", exc_info=True)
        return None


def _cwd_of(cwd) -> str:
    """本进程当前把工作区当作哪个目录（与 `_state_key` 同一份判据，不留两处读法）。"""
    return os.fspath(cwd) if cwd is not None else os.environ.get("XEYO_CWD", "")


#: 头里那句"被剪节点可以拉回来"到底有没有被用 —— 唯一能结束"句柄面该不该加上限"的量。
#: 形状：`expand(branch://…)` 或按头里给的 Read 句柄去读冷层视图文件。
_HANDLE_REF_RE = re.compile(r"(expand\(|branch://|read://|\.xeyo_offload)")


def _handle_refs(messages: list[dict], start: int) -> int:
    """新增消息里"取回形状"的 tool 调用数（引用了句柄或冷层视图路径）。"""
    n = 0
    for m in messages[max(0, start):]:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            if _HANDLE_REF_RE.search(str(b.get("input") or "")):
                n += 1
    return n


def _usage_ledger():
    from pathlib import Path

    home = (os.environ.get("XEYO_HOME") or "").strip()
    base = Path(home) if home else Path(os.path.expanduser("~")) / ".xeyo"
    return base / "wsc_index_usage.jsonl"


def _reuse_frozen(st: "_Live", messages: list[dict]) -> None:
    """复用冻结头的那一枪：把两项观测计数走掉（不改任何发射形状）。"""
    st.shots += 1
    st.handle_refs += _handle_refs(messages, st.n_messages)
    st.n_messages = len(messages)


def _note_head_usage(session: str, st: "_Live") -> None:
    """头被替换时补一条账：这份头活了几枪、句柄面多大、期间被取回几次。

    只记账，不改任何发射形状；写失败必须静默（投影永远不能被观测拖住）。
    """
    if st is None or not st.head:
        return
    try:
        import json
        from datetime import datetime, timezone

        line = json.dumps({
            "ts": round(datetime.now(tz=timezone.utc).timestamp(), 3),
            "session": session,
            "head_shots": max(0, st.shots - st.head_shot),
            "handle_tokens": int(st.handle_tokens),
            "handle_refs": int(st.handle_refs),
            "head_tokens": node_tokens_of(st.head),
        }, ensure_ascii=False)
        path = _usage_ledger()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + chr(10))
    except Exception:  # noqa: BLE001
        _log.debug("wsc index-usage ledger failed", exc_info=True)


def node_tokens_of(text: str) -> int:
    try:
        from synaptic.textutil import node_token_len

        return int(node_token_len(text))
    except Exception:  # noqa: BLE001
        return 0


def _state_key(session: str, cwd) -> str:
    return f"{session}\0{_cwd_of(cwd)}"


def live_index_age(session: str = "", cwd: str | None = None) -> int:
    """头自建出后过了几枪（= 头的年龄）。

    为什么单独报这个数：热层"索引占比"这个旧口径把两件事混成一件——
    占比低可能因为索引瘦，也可能因为**头根本没重建**（GUI 流量实测 125 枪才折一次）。
    只有"多少枪没刷"才是能据以行动的量。没有活路径状态 ⇒ 0（宁可报 0 也不猜）。
    """
    st = _STATE.get(_state_key(session, cwd))
    return max(0, st.shots - st.head_shot) if st is not None else 0
