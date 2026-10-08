"""WSC live projection (stage C).

C2 remains the trigger; WSC becomes the execution projection.  The module is
fail-open: when the switch is off, the region is too small, the gain gate
declines, or any error occurs, the caller keeps the existing C2 projection.

Current policy (2026-10-08): heads are immutable between explicit fold events;
cost cadence cannot absorb history. The switches described below are retired.
Historical caller-side policies (the deterministic algorithm never reads them):

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
  2026-09-22 update: ``PAYBACK_SHOTS`` moved 8 -> 30 (up to 30 future requests to repay
  the transition), and ``memory.runtime.try_extend_c2`` now enforces that same
  criterion on the cursor push for **both** arms.  So this flag would be re-tuning a gate
  that already fires on the identical rule -- its 1.036x measurement predates the change
  and has to be re-run before the flag can be considered again.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from pathlib import Path
from typing import Any
from memory.wsc_source_layout import LEGACY

_log = logging.getLogger(__name__)
_ENV = "XEYO_WSC"
#: 头冻结（kill switch，默认开）。关掉 = 回到"每枪重投影、交界每枪前移"的历史行为。
#: 吸收节奏（**默认关**，等真冒烟数据裁定）：开了就由 ``synaptic.cadence`` 的成本判据
#: 决定何时把右段折进头，而不是等调用方下一次折叠事件。


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
    #: 发射侧钉住的工作区根。整份头/尾区间冻结期间它必须逐字不变（见 `_pinned`）。
    cwd: str = ""
    #: 与磁盘冻结头复用同一份来源封印，防过滤旧状态后消息下标漂移。
    source_seal: str = ""
    source_layout: str = LEGACY
    view_path: str = ""
    lifecycle: dict = dataclasses.field(default_factory=dict)
    #: 上一次**真折叠**实测到的头增量（token）：新头 − 旧头。−1 = 还没有实测
    #: （进程内从未折过 / 从磁盘接回头）。读者只有 `live_head_delta_tokens()`，
    #: 供 `memory.runtime.try_extend_c2` 的 θ 门在旗标打开时当"头增量"用。
    last_head_delta: int = -1


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
    return True


def absorb_gated_enabled() -> bool:
    return False


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
        mode="closure", fold_cadence="econ", handle_style="read",
        stable_prefix_ordering=False,
        journal_rebase=True,
    ).for_level("Medium+")


def _head_msg(text: str) -> dict:
    return {"role": "assistant", "content": text, "name": "session_summary"}


def _dump_emission(head: str) -> None:
    """``XEYO_WSC_DUMP=1`` 时把**实发头文本**追加落盘（调试用；默认关、零成本）。

    落的就是 _emit 收到的 head 本身——不重算、不重放：被观测对象必须是真正发
    出去的"那一枪"（16 条缺陷 #14：投影只在模型侧可见，调试压缩机制时对象不可见）。
    """
    if os.environ.get("XEYO_WSC_DUMP", "").strip() in ("", "0"):
        return
    try:
        from memory.instruction import xeyo_home

        d = xeyo_home() / "wsc_dump"
        d.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        with (d / "emissions.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"\n===== {stamp} =====\n{head}\n")
    except Exception:  # noqa: BLE001 — 调试落盘失败绝不影响主链
        pass


def _emit(head: str, messages: list[dict], base: int, frozen_attr: int, *, cwd, view_path=None, session="", lifecycle=None, source_layout=LEGACY) -> list[dict]:
    from engine.compact import project as project_c0c1
    from memory.wsc_recovery_emit import restore

    from memory.wsc_goal_events import augment, GoalEventLedgerError
    try:
        messages, frozen_attr = augment(messages, base, frozen_attr, head=head, cwd=cwd,
            session=session, lifecycle=lifecycle, source_layout=source_layout)
    except GoalEventLedgerError:
        raise
    except Exception as exc:
        from memory.wsc_diagnostics import record
        record("goal_event", exc, session=session)
    _dump_emission(head)
    emitted = [_head_msg(head)] + project_c0c1(
        messages[base:], frozen_until=max(0, frozen_attr - base), cwd=cwd
    )
    emitted = restore(emitted, messages, base, frozen_attr, cwd=cwd, view_path=view_path)
    from synaptic.task_checkpoint import restore_receipts
    from synaptic.receipt_render import projection_enabled, render as render_receipts
    from memory.wsc_execution_boundary import restore_tail
    projected = restore_tail(restore_receipts(emitted, messages, base, frozen_attr), messages, base, 1,
        from_index=(lifecycle or {}).get("response_tail_from"))
    return render_receipts(projected) if projection_enabled() else projected


def project_c2_messages(messages: list[dict], working, *, cwd=None) -> list[dict] | None:
    if not live_enabled():
        return None
    cached = None
    try:
        from memory import wsc_head_store
        from memory.wsc_source_layout import LEGACY, APPEND, validate
        from memory.offload import ref_path_for
        from memory.wsc_goal_source import snapshot as goal_snapshot
        from synaptic.cadence import CadenceState
        from synaptic.project import project as wsc_project
        from synaptic.replay import _region_raw_tokens
        from synaptic.textutil import node_token_len

        session = str(getattr(working, "session_id", "") or "-")
        source_layout = validate(getattr(working, "compression_source_layout", LEGACY))
        cursor = int(getattr(working, "compact_cursor", 0) or 0)
        frozen_attr = int(getattr(working, "c1_frozen_until", 0) or 0)
        params = production_params()

        # 可吸收上界：调用方游标之上、keep_tail_cut 之内，并且**落在 pair-safe 切点**
        # （不拆散 assistant tool_use 与它的 tool_result —— 那会直接造出 400 形状）。
        from memory.wsc_extension_economics import absorb_boundary

        upper = absorb_boundary(messages, cursor)
        from memory.wsc_execution_boundary import protect
        upper = protect(messages, upper)
        if upper <= 1:
            return None

        key = _state_key(session, cwd)
        cached = _STATE.get(key)
        if cached is not None:
            # 历史回滚、游标倒退或冻结区来源变化，都作废整份状态（含冻结头）。
            # 交界下标回退**不作废**：右段上界是 `keep_tail_cut` 按尾部预算现算的，一根大
            # tool 结果落进尾部就会把它顶回去。旧口径在这里把整份冻结头扔掉，于是本该是
            # "前缀扩展"的一枪变成全量重排 —— 厂商侧整段 miss（不该发生的 miss 之一）。
            # 退回旧交界发射：head 与 head 之后的重投区逐字未动 ⇒ 仍是前缀扩展。
            if len(messages) < cached.n_messages or cached.cursor > cursor:
                cached = None
            elif (
                cached.source_seal
                and cached.source_seal != wsc_head_store.region_seal(messages, cached.region_end, source_layout=source_layout)
            ):
                cached = None
            elif not _junction_intact(messages, cached.region_end):
                # 状态旧版本过滤可能让旧交界移动到结果内部；同时追加新工具轮时
                # upper 仍会变大，不能用 upper 回退作检查前提。
                cached = None

        if cached is None:
            cached = _restore_frozen(session, cursor, messages, cwd, source_layout=source_layout)

        # 冷却同源：活路径（`memory.runtime.try_extend_c2`）把**实测回本枪数**钉进
        # `working.c2_gap_shots`，而发射侧的节奏由 `CadenceState` 自己维护。同一会话里两条
        # 路径都会折叠 ⇒ 冷却必须是**一个数**：这里取两者的较大值（`adopt_gap` 只收紧不放宽）。
        try:
            gap_seen = int(getattr(working, "c2_gap_shots", 0) or 0)
        except (TypeError, ValueError):
            gap_seen = 0
        if gap_seen > 0 and cached is not None and cached.cadence is not None:
            cached.cadence.adopt_gap(gap_seen)

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
            prompt_tok = int(_region_raw_tokens(messages))
            from synaptic.cadence import watermark_tokens

            wm = watermark_tokens(int(getattr(params, "window_tokens", 0) or 0))
            below_watermark = wm > 0 and prompt_tok < wm
            dec = cached.cadence.decide(
                region_tokens_=region_tok,
                tail_tokens_=int(_region_raw_tokens(messages[upper:])),
                margin=params.fold_margin,
                price_ratio=params.fold_price_ratio,
                prompt_tokens=prompt_tok,
            )
            # 保底：待吸收区已长过一个头的增长周期 ⇒ 不划算也得折（尾巴不能无限长）
            # 水位：prompt 未到 window × FOLD_WATERMARK_RATIO 一律不折（window 未知时不设门）。
            absorb = (not below_watermark) and (
                bool(dec.fold) or region_tok >= int(params.journal_growth_tokens)
            )

        if cached is not None and cached.head and not absorb and freeze_enabled():
            # 头字节原样复用 + 右段只追加 ⇒ 整份发射是上一枪的前缀扩展。
            # 反面形状被生产实测过：交界每枪前移 ⇒ 头之后全重排，
            # 厂商 cache_hit 99.8%→55.6%、每请求成本 ¥9.23m→¥21.11m（2.3 倍）。
            _reuse_frozen(cached, messages)
            return _emit(cached.head, messages, cached.region_end, frozen_attr, cwd=_pinned(cached, cwd), view_path=cached.view_path, session=session, lifecycle=cached.lifecycle, source_layout=source_layout)

        view_path = _view_path_for(_cwd_of(cwd), session)
        from memory.wsc_continuation import resume_inputs

        previous, cold, view_path = resume_inputs(
            cached, cached.view_path if cached is not None and cached.view_path else view_path,
            mode=params.mode, level=params.level,
        )
        proj = wsc_project(
            messages,
            region_end=upper,
            params=params,
            prev=previous,
            cold=cold,
            session=session,
            region_baseline_tokens=int(_region_raw_tokens(messages[:upper])),
            view_path=view_path,
            view_ref=ref_path_for(view_path, os.environ.get("XEYO_CWD") if cwd is None else str(cwd) or None),
            exclude_state_notes=source_layout == APPEND,
            goal_snapshot=goal_snapshot(_cwd_of(cwd), session),
        )
        if not proj.result.compressed:
            # 收益门拒了本次折叠 ⇒ 绝不能返回 None。返回 None 会让调用方回退 C2 本体，
            # 那等于把已冻结的头整段换掉（前缀全废），比"这次不折"糟糕得多。
            if cached is not None and cached.head and freeze_enabled():
                _reuse_frozen(cached, messages)
                return _emit(cached.head, messages, cached.region_end, frozen_attr, cwd=_pinned(cached, cwd), view_path=cached.view_path, session=session, lifecycle=cached.lifecycle, source_layout=source_layout)
            return None

        # 本次折叠实测的头增量（新头 − 旧头；首折/头丢失时 = 整个新头）。两个读者：
        # ① CadenceState 的追加比估计（只吃"头被沿用"的那种）；② θ 门的发射侧口径
        # （`try_extend_c2` → `live_head_delta_tokens`，下一枪生效）。
        head_delta_tok = max(
            0,
            node_token_len(proj.text)
            - (node_token_len(cached.head) if cached is not None and cached.head else 0),
        )
        if dec is not None and cached is not None and cached.cadence is not None:
            cached.cadence.observe_fold(
                region_tokens_=region_tok,
                head_delta_tokens=head_delta_tok,
                # 只有头被沿用才算 carry_over；首折/整层重冻结的 delta 是整个新头
                carried_over=bool(cached.head and not proj.result.rebuilt),
            )
        if cached is not None:
            _note_head_usage(session, cached)   # 旧头退场前补一条取回账
        try:
            # 收纳事实：段数单调 + 最近出处，供 T_now 的 context_usage 一行呈现
            # （此前折叠对模型完全不可见，唯一信号是撞上写守卫的 missing_read）。
            from memory.wsc_folds import record_fold, subject_from

            record_fold(
                session,
                subject_from(
                    messages,
                    cached.region_end if cached is not None else 0,
                    upper,
                ),
            )
        except Exception:  # noqa: BLE001 — 台账失败不许挡折叠
            pass
        if len(_STATE) >= _MAX_STATE and key not in _STATE:
            _STATE.pop(next(iter(_STATE)))
        shot = (cached.shots if cached is not None else 0) + 1
        handle_tok = 0
        try:
            handle_tok = int((proj.result.budget or {}).get("handle_tokens") or 0)
        except Exception:  # noqa: BLE001 - 观测字段，拿不到就算了
            handle_tok = 0
        pinned = _pinned(cached, cwd)
        from synaptic.task_checkpoint import enabled as continuity_enabled
        if continuity_enabled():
            proj.state.lifecycle["response_tail_from"] = protect(messages, len(messages))
        # Complete the durable generation before replacing the live head.
        saved = wsc_head_store.save(
            session, text=proj.text, cwd=pinned, cursor=cursor,
            region_end=upper, messages=messages,
            view_path=str(Path(proj.view_path or view_path).resolve()),
            source_layout=source_layout,
            lifecycle=dict(proj.state.lifecycle),
        )
        from synaptic.contracts import enabled as contracts_enabled
        if contracts_enabled() and wsc_head_store.enabled() and not saved:
            if cached is not None and cached.head and freeze_enabled():
                return _emit(cached.head, messages, cached.region_end, frozen_attr,
                             cwd=_pinned(cached, cwd), view_path=cached.view_path, session=session, lifecycle=cached.lifecycle, source_layout=source_layout)
            return None
        _STATE[key] = _Live(
            prev=proj.state,
            cold=proj.cold,
            n_messages=len(messages),
            region_end=upper,
            cursor=cursor,
            head=proj.text,
            cadence=_cadence_for(cached, params, gap_seen),
            shots=shot,
            head_shot=shot,
            handle_tokens=handle_tok,
            cwd=pinned,
            source_seal=wsc_head_store.region_seal(messages, upper, source_layout=source_layout),
            view_path=str(Path(proj.view_path or view_path).resolve()),
            source_layout=source_layout,
            last_head_delta=int(head_delta_tok),
            lifecycle=dict(proj.state.lifecycle),
        )
        # 落盘只在这一个点上发生（= 头真被重排的那一枪）⇒ 写放大 = 折叠次数，不是枪数。
        return _emit(proj.text, messages, upper, frozen_attr, cwd=pinned, view_path=proj.view_path or str(view_path.resolve()), session=session, lifecycle=proj.state.lifecycle, source_layout=source_layout)
    except Exception as exc:  # noqa: BLE001 - WSC must never block the projection
        from memory.wsc_goal_events import GoalEventLedgerError
        if isinstance(exc, GoalEventLedgerError):
            raise
        from memory.wsc_diagnostics import record
        record("projection", exc, session=str(getattr(working, "session_id", "")))
        if cached is not None and cached.head and freeze_enabled():
            try:
                return _emit(cached.head, messages, cached.region_end, frozen_attr,
                             cwd=_pinned(cached, cwd), view_path=cached.view_path, session=session, lifecycle=cached.lifecycle, source_layout=source_layout)
            except GoalEventLedgerError:
                raise
            except Exception:
                pass
        _log.debug("wsc live projection failed; falling back to C2", exc_info=True)
        return None


def _restore_frozen(session: str, cursor: int, messages: list[dict], cwd, *, source_layout="latest-notes-v1"):
    """进程内状态没了（重启 / 状态槽被顶掉）时，把上一份冻结头**字节**接回来。

    不接会怎样（生产实测形状）：那一枪交给 `synaptic.project` 从头重排 ⇒ 发出的 prompt
    与上一枪逐字无关 ⇒ 厂商侧整段 miss，而单枪 prompt 中位 11.7k tok 全价重投。

    接回来的全部前提在 `wsc_head_store.load`（ver / cwd / cursor / 冻结区 sha1）；
    这里补最后一道**只在发射侧才知道**的判据：交界在新历史里是不是还没切开调用对。
    任一不成立 ⇒ None ⇒ 走原重建路径（失败方向永远是"更保守"）。
    """
    if not freeze_enabled():
        return None  # 头冻结关着 ⇒ 语义上本来就每枪重投影，别偷偷改行为
    from memory import wsc_head_store

    fh = wsc_head_store.load(
        session, cwd=_cwd_of(cwd), cursor=cursor, messages=messages, allow_advance=True, source_layout=source_layout
    )
    if fh is None or not _junction_intact(messages, fh.region_end):
        return None
    # 不恢复瞬时统计。下一次折叠由 resume_inputs 保留旧文件，并接续完整旧头。
    # 游标已前进时仍返回旧游标，使 moved 立即触发真正折叠而不是复用旧交界。
    return _Live(
        prev=None,
        cold=None,
        n_messages=len(messages),
        region_end=fh.region_end,
        cursor=fh.cursor,
        head=fh.text,
        cadence=None,
        shots=1,
        head_shot=1,
        cwd=fh.cwd,
        source_seal=wsc_head_store.region_seal(messages, fh.region_end, source_layout=source_layout),
        view_path=fh.view_path,
        source_layout=source_layout,
        lifecycle=dict(fh.lifecycle),
    )


def _cadence_for(cached, params, gap_seen: int):
    """折叠后新状态要挂的节奏状态：沿用旧的（保留观测比），否则新建；再把**实测冷却**吃进去。

    `gap_seen` 来自活路径（`working.c2_gap_shots`）：同一会话两条折叠路径共用**一个**冷却数，
    `adopt_gap` 只收紧不放宽 ⇒ 这个合流永远不会让它折得更频繁。
    """
    from synaptic.cadence import CadenceState

    cadence = cached.cadence if cached is not None else None
    if cadence is None:
        cadence = CadenceState(
            head_delta_cap=int(params.hot_budget_tokens)
            + int(params.journal_growth_tokens)
        )
    if gap_seen > 0:
        cadence.adopt_gap(gap_seen)
    return cadence


def _cwd_of(cwd) -> str:
    """本进程当前把工作区当作哪个目录（与发射侧 `_pinned` 同一份判据，不留两处读法）。"""
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


def _junction_intact(messages: list[dict], cut: int) -> bool:
    """冻结点在新历史里还是不是成对切点（不拆散 tool_use 与它的 tool_result）。

    判不了就当作"完好"：交界当年是按 pair-safe 冻下来的，而右段只增不改 ⇒
    默认复用安全；只有**明确算得出**被切开才作废。
    """
    if cut <= 0 or cut >= len(messages):
        return True
    try:
        from memory.runtime import pair_safe_cut

        return int(pair_safe_cut(messages, cut)) == cut
    except Exception:  # noqa: BLE001 - 判不了就不作废
        return True


def _pinned(st: "_Live | None", cwd) -> str:
    """发射侧要交给下游投影的 cwd —— 钉住第一个定义它的那一枪的值。

    `_emit` 把 cwd 交给 `engine.compact.project`（内部会拼 offload 路径，且
    `_offload_root("")` 会读**活值** `os.getcwd()`）。调用方每枪给的 cwd 一旦抖动
    （相对/绝对、尾斜杠、进程 cwd 与工作区 cwd 混用），尾部字节就变 ⇒ 冻结前缀
    从中间断掉。冻结点钉一次，之后整段只管字节不变。
    """
    pinned = getattr(st, "cwd", "") if st is not None else ""
    return pinned or _cwd_of(cwd)


def _reuse_frozen(st: "_Live", messages: list[dict]) -> None:
    """复用冻结头的那一枪：把两项观测计数走掉（不改任何发射形状）。"""
    st.shots += 1
    st.handle_refs += _handle_refs(messages, st.n_messages)
    st.n_messages = len(messages)


def _note_head_usage(session: str, st: "_Live") -> None:
    """头被替换时补一条账：这份头活了几枪、句柄面多大、期间被取回几次。

    只记账，不改任何发射形状；写失败必须静默（投影永远不能被观测拖住）。

    ⚠️ 离线台（重放/扫描）默认会直接调本模块的投影 ⇒ 必须能被挡在外面，
    否则生产分母被探针淹没（实测发生过：3,668 行里 3,605 行是扫描脚本写的，
    于是"头存活枪数 p50=1"这种话说的其实是探针自己）。离线台设
    ``XEYO_WSC_OFFLINE=1`` 即可，生产不设 ⇒ 行为不变。
    """
    if st is None or not st.head:
        return
    if os.environ.get("XEYO_WSC_OFFLINE", "").strip() in ("1", "true", "yes", "on"):
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


def _state_key(session: str, cwd=None) -> str:
    """活路径状态只认会话 —— 工作区不参与。

    旧口径把 cwd 拼进键：调用方每枪给的 cwd 只要抖一次（相对/绝对、尾斜杠、
    进程 cwd 与工作区 cwd 混用），同一会话就落进两个槽位，第二个槽位永远是冷的
    ⇒ 那一枪必然整段重投。会话 id（`sess_<uuid>`）本身已唯一，不需要 cwd 再区分。
    """
    return str(session or "-")


def live_index_age(session: str = "", cwd: str | None = None) -> int:
    """头自建出后过了几枪（= 头的年龄）。

    为什么单独报这个数：热层"索引占比"这个旧口径把两件事混成一件——
    占比低可能因为索引瘦，也可能因为**头根本没重建**（GUI 流量实测 125 枪才折一次）。
    只有"多少枪没刷"才是能据以行动的量。没有活路径状态 ⇒ 0（宁可报 0 也不猜）。
    """
    st = _STATE.get(_state_key(session, cwd))
    return max(0, st.shots - st.head_shot) if st is not None else 0


def live_head_delta_tokens(session: str = "", cwd: str | None = None) -> int | None:
    """上一次真折叠实测的**头增量**（token）；没有实测返回 None（调用方回退 C2 口径）。

    None 与 0 必须分开：0 表示"实测到这次折叠没让头变大"（合法事实），None 表示
    "本进程没有可信实测"（从磁盘接回的头、或从未折过）——把后者当 0 会让 θ 门
    以为头增量免费，正是"没有证据就少折"的反方向。
    """
    st = _STATE.get(_state_key(session, cwd))
    if st is None or int(getattr(st, "last_head_delta", -1)) < 0:
        return None
    return int(st.last_head_delta)
