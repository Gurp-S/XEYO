"""WSC 问答集离线裁定器：多臂 × 分母纪律 × provenance（**不输出任务成功率**）。

用法::

    py -3.11 evals/wsc_failure_judge.py --corpus evidence --out _wsc_out/qa_judge
    py -3.11 evals/wsc_failure_judge.py --corpus legacy   --limit 6

臂（同一批轨迹，只换「模型当时看到的上下文」）：

- ``wsc``         当前压缩投影（该轮**开始时**的前缀，不含尾部）
- ``nocompress``  不压缩原文（上界臂）
- ``empty``       什么都不给（下界臂：测漏报）
- ``hostile``     贴**别的会话**的投影（负控：测误报——无关文本能不能骗过判据）

纪律（== 讨论十条的落地）：

1. **不输出「任务成功率」**。成功率只能来自外部 verifier；本报告输出「信息可得性 + 过程质量」，
   以及「机械三件套 vs 外部 reward」的**配对表**（叫预测力，不叫成功率）。
2. **分母透明**：所有指标带 ``yes/total/status``；分母 0 ⇒ ``not_applicable``，不折算成任何数
   （历史事故：``if total else 1.0`` 让三个零错误会话各贡献 1.0 ⇒ 头条数 0.9583 是伪影）。
3. **臂对称**：``wsc`` 的可见率不得高于 ``nocompress``，违反即列红（判据与投影同源的残留）。
4. **provenance**：judge / runner / 语料清单指纹 + python 版本进报告头，对不上拒绝采信。

产物：``wsc_qa_report.json``（含逐题证据与 msg#）+ ``wsc_qa_report.md``。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_ROOT = REPO_ROOT / "python"
if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))

from evals.bash_write_probe import install as install_bash_write_probe
from evals.wsc_qa_corpus import (  # noqa: E402  （必须先插 sys.path）
    DEFAULT_EVIDENCE,
    LEGACY_CODEX,
    REPO_ROOT as CORPUS_ROOT,
    manifest,
    resolve_evidence,
    resolve_jsonl_dir,
)

from synaptic.failure_modes import QUESTION_BANK, analyze, turn_facts  # noqa: E402
from synaptic.freshness import analyze as freshness_analyze  # noqa: E402
from synaptic.graph import build_graph  # noqa: E402
from memory.wsc_projection import production_params  # noqa: E402  （生产配置的唯一来源）
from synaptic.project import project  # noqa: E402
from synaptic.qa_grading import (  # noqa: E402
    aggregate,
    arm_symmetry_violations,
    file_digest,
    provenance,
    question_bank_digest,
)
from synaptic.textutil import message_text, node_token_len  # noqa: E402
from memory.runtime import deterministic_c2_summary  # noqa: E402  （生产对照臂的本体）

#: `c2` = 生产里 WSC **实际顶替的那个东西**（``memory.runtime.apply_c2_messages`` 的
#: 左段确定性摘要）。基线臂原先只有 `nocompress`（原文），于是所有“wsc vs nocompress”
#: 量的是**相对原文的代价**，而不是**相对替代物的收益**——后者才是"WSC 比 C2 更省/更保真"
#: 这句话需要的那个数。同切点、只换压缩器，两臂体积一并报（只比可见率会让 3k tok 白赢）。
ARMS = ("wsc", "nocompress", "c2", "empty", "hostile")
#: 与臂无关（trajectory 维）的题：不能用来做臂间比较，报告里单列。
TRAJECTORY_QIDS = tuple(q.id for q in QUESTION_BANK if q.dims == "trajectory")
PROJECTION_QIDS = tuple(q.id for q in QUESTION_BANK if q.dims == "projection")


def raw_text(msgs: list[dict]) -> str:
    return "\n".join(message_text(m) for m in msgs)


def _project_prefix(msgs: list[dict], end: int, sid: str, params=None, *,
                    prev=None, cold=None, view_path=None, view_ref=None):
    """该轮开始时模型的上下文 = 压缩前缀本身（**不含尾部**；含尾部会把本轮自己的
    结果算成"事前可见"，这是已修过的口径污染）。

    **与生产同配置、同状态**：参数取自 ``memory.wsc_projection.production_params()``，
    且跨回合携带 ``prev`` / ``cold``（日志累积、``[HEAD]`` 换头都会进被测量）。
    原先这里是无状态单发重投 + ``fold_cadence=always`` + ``handle_style=expand``，
    量的其实不是产品发出的那个投影（热层中位 2,467 vs 生产口径 10,234 tok）。
    """
    from synaptic.replay import _region_raw_tokens

    proj = project(msgs[:end], region_end=end,
                   params=params or production_params(), session=sid,
                   prev=prev, cold=cold,
                   region_baseline_tokens=int(_region_raw_tokens(msgs[:end])),
                   view_path=str(view_path) if view_path else "",
                   view_ref=view_ref or "")
    # **臂必须等于"实际发出去的东西"**，不是"算出来的东西"。
    # 未过收益门/触发闸时生产根本不发这份投影（`wsc_projection` 直接 return None 回退
    # C2 ⇒ 发整段未压缩区域）。旧实现在那种回合仍拿 hot.text 去判可见性，等于给一个
    # 从未发送的投影记了分（实测 evidence 94 回合里 47 回合属于此类）。
    text = proj.text if proj.result.compressed else raw_text(msgs[:end])
    return text, proj


#: 发射文本的分段归类（与 ``synaptic/assemble.py`` 的段名同源）。
_SEG_HEAD_RE = re.compile(r"^\[([A-Z][A-Z0-9_ -]*)\]")
#: 可恢复性索引：被剪节点卡面 —— 唯一取回出口，逐字锚定，不竞争注意力额度。
_INDEX_SEGS = frozenset({"DECISIONS", "PRUNED"})
#: 注意力段：模型真正要读的东西。
_ATTENTION_SEGS = frozenset({
    "CONSTRAINTS", "UNRESOLVED", "TODO", "WORKING SET", "PATHS", "MAIN", "REHYDRATED",
    "NEXT", "HEAD",
})


def _budget_row(proj) -> dict:
    """对**同一份发射文本**按段前缀做真拆解（裁定：索引不竞争注意力额度，但必须单列）。

    为什么不用 ``proj.result.budget``：那套字段量的是"本回合选择了多少"，而实发头里还带着
    跨回合累积的日志 ⇒ 两者不同源（对平过：短会话差 91–632 tok，长会话差到 18k）。
    所以这里只按发射行分段，保证 ``attention + index + requests + other == 实发头``。
    """
    text = str(getattr(proj, "text", "") or "")
    buckets = {"attention": 0, "index": 0, "requests": 0, "other": 0}
    for ln in text.splitlines():
        t = node_token_len(ln) + 1
        m = _SEG_HEAD_RE.match(ln)
        head = (m.group(1).strip() if m else "_NONE")
        if head in _INDEX_SEGS:
            buckets["index"] += t
        elif head == "REQUESTS":
            buckets["requests"] += t
        elif head in _ATTENTION_SEGS:
            buckets["attention"] += t
        else:
            buckets["other"] += t
    b = dict(getattr(proj.result, "budget", {}) or {})
    buckets["index_budget"] = int(b.get("index_budget_tokens") or 0)
    buckets["segmented_total"] = (buckets["attention"] + buckets["index"]
                                  + buckets["requests"] + buckets["other"])
    return buckets


def build_arm_contexts(sessions: list, params=None, view_dir=None, *,
                       invoke: str = "every-turn", trigger_ratio: float = 0.8,
                       context_limit: int = 0):
    """先只算 ``wsc`` 上下文（hostile 臂要拿别的会话的投影），再派生其余臂。

    第三个返回值 ``hot_rows`` 是**同一次投影**顺带记下的逐回合热层体积：统计口径必须
    与被测投影同源，否则一份报告里会出现两套数（旧版就是：臂走无状态单发、
    ``hot_stats`` 走末轮单发，两者都跟生产的逐回合有状态序列不一样）。

    ``invoke`` 决定**什么时候折**（WSC 自己不读这个旋钮——``fold_cadence`` 只活在调用方）：
    - ``every-turn``（**生产现状**，默认档）：每个用户回合都尝试折叠。2026-09-21 生产冒烟实测过：
      ``memory/runtime.py`` 一旦 ``compact_cursor > 0`` 就每枪走 ``apply_c2_messages`` →
      ``wsc_projection`` 重投影，而 ``fold_cadence`` 在 ``synaptic/`` 里只有 ``replay.py`` 读 ⇒
      成本判据在生产**未接线**。
    - ``prod``（cadence 节奏 = 回放台的 ``adopted`` 档）：折叠由 ``synaptic.cadence`` 的成本
      判据决定；**一旦压过就一直发「冻结头 + cursor 之后原文」**，绝不回退整段原文。
      水位基准 = 上一回合实际发出的 token。
      ⚠️ **未接线的应然节奏**：它回答的是"按成本判据该不该折"，不是"现在产品发了什么"
      （``_wsc_out/qa_set_hardening_plan.md`` §14 已把这条错标签改回来）。
    """
    from memory.offload import ref_path_for
    from synaptic.cadence import CadenceState
    from synaptic.replay import _region_raw_tokens

    pset = params or production_params()
    wsc: dict[str, dict[int, str]] = {}
    facts_by_sid: dict[str, list] = {}
    hot_rows: list[dict] = []
    for s in sessions:
        msgs = list(s.messages)
        graph = build_graph(msgs, include_soft_edges=False)
        facts = turn_facts(graph, msgs, len(msgs))
        facts_by_sid[s.sid] = facts
        ctx: dict[int, str] = {}
        # 逐回合携带状态：与生产一致（生产按 (session,cwd) 缓存，消息不回退则续用）
        state = cold = None
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", s.sid)[:64]
        view_path = (Path(view_dir) / f"{safe}.txt") if view_dir else None
        view_ref = ref_path_for(view_path, None) if view_path is not None else ""
        # ── ``prod`` 的跨回合状态（照抄 replay adopted 分支的语义）────────────
        cursor = 0
        hot = ""
        last_sent = 0.0
        cadence = CadenceState(
            head_delta_cap=int(pset.hot_budget_tokens) + int(pset.journal_growth_tokens)
        )
        for tf in facts:
            end = tf.region_end
            if invoke != "prod":
                text, proj = _project_prefix(
                    msgs, end, s.sid, pset,
                    prev=state, cold=cold, view_path=view_path, view_ref=view_ref)
                ctx[tf.turn] = text
                state, cold = proj.state, proj.cold
                hot_rows.append({"sid": s.sid, "turn": tf.turn,
                                 "hot_tokens": proj.result.hot.tokens,
                                 **_budget_row(proj),
                                 "base_tokens": proj.result.base_tokens,
                                 "compressed": bool(proj.result.compressed),
                                 "rebuilt": bool(proj.result.rebuilt),
                                 "sent_tokens": node_token_len(text),
                                 "unresolved_lines": sum(
                                     1 for ln in text.splitlines() if ln.startswith("[UNRESOLVED]")
                                 )})
                continue
            fired = True
            dec = None
            region_tok = 0
            if pset.fold_cadence == "econ":
                region_tok = _region_raw_tokens(msgs[cursor:end])
                dec = cadence.decide(
                    region_tokens_=region_tok,
                    tail_tokens_=_region_raw_tokens(msgs[end:]),
                    margin=pset.fold_margin,
                    price_ratio=pset.fold_price_ratio)
                fired = bool(dec.fold)
            else:
                fired = bool(trigger_ratio > 0 and context_limit > 0
                             and last_sent >= int(trigger_ratio * context_limit))
            proj = None
            folded = False
            if fired:
                _unused, proj = _project_prefix(
                    msgs, end, s.sid, pset,
                    prev=state, cold=cold, view_path=view_path, view_ref=view_ref)
                folded = bool(proj.result.compressed)
                if folded:
                    if dec is not None:
                        dec_head = proj.text
                        cadence.observe_fold(
                            region_tokens_=region_tok,
                            head_delta_tokens=max(
                                0, node_token_len(dec_head) - node_token_len(hot)),
                            carried_over=bool(hot and not proj.result.rebuilt))
                    cursor = end
                    hot = proj.text
                    state, cold = proj.state, proj.cold
            text = (f"{hot}\n{raw_text(msgs[cursor:end])}" if cursor
                    else raw_text(msgs[:end]))
            last_sent = node_token_len(text)
            ctx[tf.turn] = text
            hot_rows.append({"sid": s.sid, "turn": tf.turn,
                             "hot_tokens": node_token_len(hot) if cursor else 0,
                             **(_budget_row(proj) if proj is not None else {}),
                             "base_tokens": proj.result.base_tokens if proj is not None
                             else _region_raw_tokens(msgs[:end]),
                             "compressed": folded,
                             "rebuilt": bool(proj.result.rebuilt) if folded else False,
                             "sent_tokens": int(last_sent),
                             "trigger_skipped": not fired,
                             "unresolved_lines": sum(
                                 1 for ln in text.splitlines() if ln.startswith("[UNRESOLVED]")
                             )})
        wsc[s.sid] = ctx
    order = [s.sid for s in sessions]
    out: dict[str, dict[int, str]] = {arm: {} for arm in ARMS}
    arm_sizes: dict[str, list[int]] = {}
    for i, s in enumerate(sessions):
        msgs = list(s.messages)
        facts = facts_by_sid[s.sid]
        other = order[(i + 1) % len(order)] if len(order) > 1 else None
        for tf in facts:
            end = tf.region_end
            out["wsc"].setdefault(s.sid, {})[tf.turn] = wsc[s.sid].get(tf.turn, "")
            out["nocompress"].setdefault(s.sid, {})[tf.turn] = raw_text(msgs[:end])
            c2_text = deterministic_c2_summary(msgs[:end])
            out["c2"].setdefault(s.sid, {})[tf.turn] = c2_text
            arm_sizes.setdefault("c2", []).append(node_token_len(c2_text))
            out["empty"].setdefault(s.sid, {})[tf.turn] = ""
            if other is not None:
                other_ctx = wsc.get(other, {})
                key = min(tf.turn, max(other_ctx) if other_ctx else 0)
                out["hostile"].setdefault(s.sid, {})[tf.turn] = other_ctx.get(key, "")
            else:
                out["hostile"].setdefault(s.sid, {})[tf.turn] = ""
    return out, facts_by_sid, hot_rows, arm_sizes


def hot_stats_from_rows(hot_rows: list[dict], params, arm_sizes: dict | None = None) -> dict:
    """逐回合热层体积分布——**与被测臂同源**（同一批有状态投影顺带记的数）。

    收益门拒绝 / 触发闸跳过的回合照样计入 ``skipped_gate``，因为它们正是"这一回合
    发的是整段原文"，把它从分母里剔掉就等于把压缩率报高。
    """
    import statistics

    sent = [r for r in hot_rows if r["compressed"]]
    toks = [r["hot_tokens"] for r in sent]

    def _q(xs, q):
        return (sorted(xs)[min(len(xs) - 1, int(len(xs) * q))] if xs else None)

    def _med(xs):
        return (round(statistics.median(xs)) if xs else None)

    cap = int(params.hot_budget_tokens)
    return {
        "turns": len(hot_rows),
        "compressed_turns": len(sent),
        "skipped_gate": len(hot_rows) - len(sent),
        "nominal_hot_budget": cap,
        "hot_tokens_median": (round(statistics.median(toks)) if toks else None),
        "hot_tokens_p90": _q(toks, 0.9),
        "hot_tokens_max": (max(toks) if toks else None),
        "over_nominal_budget": sum(1 for t in toks if t > cap),
        # ── 发射文本的真拆解（同源：attention+index+requests+other == 分段和）──
        # 裁定 2026-09-22：可恢复性索引**不竞争**注意力额度，但必须单列并告警。
        "attention_tokens_median": _med([int(r.get("attention") or 0) for r in sent
                                         if r.get("attention") is not None]),
        "index_tokens_median": _med([int(r.get("index") or 0) for r in sent
                                     if r.get("index") is not None]),
        "requests_tokens_median": _med([int(r.get("requests") or 0) for r in sent
                                        if r.get("requests") is not None]),
        "other_tokens_median": _med([int(r.get("other") or 0) for r in sent
                                     if r.get("other") is not None]),
        "index_budget_tokens": (max([int(r.get("index_budget") or 0) for r in sent], default=0)),
        "index_over_turns": sum(1 for r in sent
                                if int(r.get("index") or 0) > int(r.get("index_budget") or 0)),
        "index_over_median_tok": _med([int(r.get("index") or 0) - int(r.get("index_budget") or 0)
                                       for r in sent
                                       if int(r.get("index") or 0) > int(r.get("index_budget") or 0)]),
        "segmented_median": _med([int(r.get("segmented_total") or 0) for r in sent
                                  if r.get("segmented_total")]),
        # 实际发出的上下文体积（every-turn 档 = 热层或整段原文；prod 档 = 冻结头 + 右段原文）
        "sent_tokens_median": _med([int(r.get("sent_tokens", 0) or 0) for r in hot_rows]),
        "trigger_skipped": sum(1 for r in hot_rows if r.get("trigger_skipped")),
        # prod 口径下可能整场会话一次都没折 ⇒ wsc 臂恒等于原文臂（该臂的分母要另算）
        "sessions_total": len({r["sid"] for r in hot_rows}),
        "sessions_ever_folded": len({r["sid"] for r in hot_rows if r["compressed"]}),
        "rebuilds": sum(1 for r in sent if r["rebuilt"]),
        "c2_arm_median": _med((arm_sizes or {}).get("c2", [])),
        "unresolved_lines_median": _med([r["unresolved_lines"] for r in hot_rows]),
        "unresolved_lines_max": (max([r["unresolved_lines"] for r in hot_rows], default=None)),
    }


def run(sessions: list, *, arms: tuple[str, ...] = ARMS, params=None, view_dir=None,
        invoke: str = "every-turn", trigger_ratio: float = 0.8, context_limit: int = 0) -> dict:
    contexts, _facts, hot_rows, arm_sizes = build_arm_contexts(
        sessions, params, view_dir,
        invoke=invoke, trigger_ratio=trigger_ratio, context_limit=context_limit)
    per_arm: dict[str, dict[str, dict]] = {a: {} for a in arms}
    session_rows: list[dict] = []
    for s in sessions:
        msgs = list(s.messages)
        graph = build_graph(msgs, include_soft_edges=False)
        resolved = frozenset(freshness_analyze(graph, region_end=len(msgs)).resolved_idx)
        arms_out: dict[str, dict] = {}
        for arm in arms:
            rep = analyze(msgs, graph, contexts[arm].get(s.sid, {}), len(msgs), resolved_idx=resolved)
            per_arm[arm][s.sid] = rep.answers
            arms_out[arm] = rep.metrics
        session_rows.append({"sid": s.sid, "task": s.task, "shape": s.shape, "batch": s.batch,
                             "reward": s.reward, "sha256": s.sha256,
                             "messages": len(s.messages), "arms": arms_out})
    agg = {arm: aggregate(per_arm[arm]) for arm in arms}
    violations = arm_symmetry_violations(
        {arm: {qid: rec for qid, rec in agg[arm].items() if qid in PROJECTION_QIDS} for arm in arms})
    return {"aggregate": agg, "violations": violations, "sessions": session_rows,
            "hot_stats": hot_stats_from_rows(hot_rows, params or production_params(), arm_sizes),
            "per_session_answers": per_arm,
            "corpus": manifest(sessions),
            "provenance": provenance(
                {"judge": PY_ROOT / "synaptic" / "failure_modes.py",
                 "visibility": PY_ROOT / "synaptic" / "qa_visibility.py",
                 "grading": PY_ROOT / "synaptic" / "qa_grading.py",
                 "runner": Path(__file__),
                 "corpus": PY_ROOT / "evals" / "wsc_qa_corpus.py"},
                extra={"question_bank": question_bank_digest(QUESTION_BANK),
                       "arms": list(arms),
                       "invoke": invoke,
                       "fold_cadence": (params or production_params()).fold_cadence,
                       "corpus_root": str(CORPUS_ROOT)}),
            "truth_pairing": truth_pairing(sessions, per_arm.get("wsc", {}))}


def truth_pairing(sessions: list, wsc_answers: dict[str, dict]) -> dict:
    """「机械三件套」与外部 reward 的配对（**这是预测力检验，不是成功率**）。"""
    cells = {"pred_ok_true_ok": 0, "pred_ok_true_fail": 0,
             "pred_fail_true_ok": 0, "pred_fail_true_fail": 0}
    disagreement: list[dict] = []
    usable = 0
    for s in sessions:
        if not s.has_truth:
            continue
        answers = wsc_answers.get(s.sid) or {}
        trio = [answers.get(q) for q in ("A1", "A2", "A3")]
        if any(a is None or a.total == 0 for a in trio):
            continue
        usable += 1
        pred_ok = all(a.yes == a.total for a in trio)
        true_ok = str(s.reward).strip() == "1"
        cells[f"pred_{'ok' if pred_ok else 'fail'}_true_{'ok' if true_ok else 'fail'}"] += 1
        if pred_ok != true_ok:
            disagreement.append({"sid": s.sid, "reward": s.reward,
                                 "A1": trio[0].row(), "A2": trio[1].row(), "A3": trio[2].row()})
    return {"usable_sessions": usable, "cells": cells, "disagreements": disagreement[:20],
            "note": ("分母 = 有外部真值且三件套可判的会话；两个方向的分歧都要看，"
                     "不能只看「预测失败但真成功」。样本 < 30 时不具统计意义。")}


def render_md(result: dict) -> str:
    agg = result["aggregate"]
    prov = result["provenance"]
    corpus = result["corpus"]
    L: list[str] = ["# WSC 问答集离线裁定（多臂 / 分母纪律 / provenance）", "",
                    "> 本报告**不产出任务成功率**。成功率只能来自外部 verifier；",
                    "> 这里输出的是「信息可得性 + 过程质量」，以及与外部 reward 的配对（预测力）。", ""]
    L += ["## 语料与 provenance", "",
          f"- 会话 {corpus['sessions']} 个，其中带外部真值 {corpus['with_external_truth']} 个",
          f"- 语料清单指纹 `{corpus['digest']}`",
          f"- 题库指纹 `{prov.get('question_bank')}`（题目增删即变）",
          f"- 判定器 `{prov['digests'].get('judge', '')[:16]}` / 可见性 "
          f"`{prov['digests'].get('visibility', '')[:16]}` / 计分 "
          f"`{prov['digests'].get('grading', '')[:16]}` / 运行器 "
          f"`{prov['digests'].get('runner', '')[:16]}`",
          f"- python `{prov.get('python')}`", ""]
    hs = result.get("hot_stats") or {}
    inv = str(prov.get("invoke", "every-turn"))
    if hs.get("turns"):
        kn = (prov.get("knobs") or {})
        L += ["## 热层体积与 `[UNRESOLVED]`（**逐回合、与生产同配置同状态**）", "",
              f"- 被评投影 = ``memory.wsc_projection.production_params()``"
              f"（`mode=closure` / `fold_cadence=econ` / `handle_style=read` / Medium+），"
              f"跨回合携带 `prev`+`cold`",
              f"- 回合 {hs.get('turns')}（其中压缩 {hs.get('compressed_turns')} / "
              f"**未过闸发原文 {hs.get('skipped_gate')}**）；整层重建 {hs.get('rebuilds')} 次",
              f"- **折叠节奏 `invoke={prov.get('invoke', 'every-turn')}`**"
              + ("：会话 "
                 f"{hs.get('sessions_total')} 个里 {hs.get('sessions_ever_folded')} 个至少折过一次；"
                 f"触发闸跳过 {hs.get('trigger_skipped')} 回合；"
                 f"实际发出上下文 token median {hs.get('sent_tokens_median')}"
                 " ← **cadence 应然节奏**（生产未接线这条判据 ⇒ 不是产品现状）"
                 if inv == "prod" else
                 "：**生产现状**（活路径每枪重投影，``fold_cadence`` 生产侧无人读）"
                 "⇒ 引用「产品实际发出的东西」用这一档"),
              f"- 名义**注意力预算** {hs.get('nominal_hot_budget')} tok（Medium+ 的 "
              f"``hot_budget_tokens``，**不是**实发大小）；实发头 median "
              f"{hs.get('hot_tokens_median')} / p90 {hs.get('hot_tokens_p90')} / max "
              f"{hs.get('hot_tokens_max')}，**超名义 {hs.get('over_nominal_budget')} 回合**",
              f"- 实发头拆解（**按发射行分段，与实发头同源**；裁定 2026-09-22：可恢复性索引"
              f"**不竞争**注意力额度，但必须单列）：注意力 median "
              f"{hs.get('attention_tokens_median')} + 索引（卡面）median "
              f"{hs.get('index_tokens_median')} + 用户原话 median {hs.get('requests_tokens_median')}"
              f" + 其余 median {hs.get('other_tokens_median')} ⇒ 分段和 median "
              f"{hs.get('segmented_median')}",
              (f"- ⚠️ **索引超它自己的额度（{hs.get('index_budget_tokens')} tok）"
               f" {hs.get('index_over_turns')} 回合**，超量 median "
               f"{hs.get('index_over_median_tok')} tok ——现行**只报账不删内容**（删它等于削掉"
               f"可恢复性句柄的唯一出口）。**引用“热层 ~3k”之前先读这一行**"),
              f"- `[UNRESOLVED]` 行数 median {hs.get('unresolved_lines_median')} / "
              f"max {hs.get('unresolved_lines_max')}", ""]
    L += ["## 逐题（分母 / 状态 / 偏斜）", "",
          "| 题 | 模式 | 维度 | " + " | ".join(ARMS)
          + " | 分母 | 状态 | 单会话占比 | 仅合成串命中 | 可门禁 |",
          "|" + "---|" * (3 + len(ARMS) + 5), ""]
    for qid in [q.id for q in QUESTION_BANK]:
        cells = []
        for arm in ARMS:
            rec = agg.get(arm, {}).get(qid)
            if rec is None:
                cells.append("-")
            elif rec["unit"] == "count":
                cells.append(f"{rec['yes']} 次/{rec['density_per_1k']}‰")
            elif rec["rate"] is None:
                cells.append("n/a")
            else:
                cells.append(f"{rec['yes']}/{rec['total']} = {rec['rate']:.3f}")
        rec0 = agg.get("wsc", {}).get(qid) or {}
        L.append(f"| {qid} | {rec0.get('mode', '')} | "
                 f"{'trajectory' if qid in TRAJECTORY_QIDS else 'projection'} | "
                 + " | ".join(cells)
                 + f" | {rec0.get('total', 0)} | {rec0.get('status', '')} | "
                   f"{rec0.get('max_session_share')} | {rec0.get('synth_only', 0)} | "
                   f"{'✓' if rec0.get('gate_eligible') else '✗'} |")
    L += ["", "`trajectory` 维的题**与臂无关**（由轨迹自身决定），不得用于臂间比较。", ""]
    viol = result["violations"]
    L += ["## 臂对称检查（wsc 不得高于 nocompress）", ""]
    if viol:
        for v in viol:
            L.append(f"- ❌ `{v['qid']}` wsc {v['subject_rate']} > nocompress {v['reference_rate']}"
                     f"（Δ{v['delta']}，分母 {v['total']}）——判据可能仍与投影同源")
    else:
        L.append("- ✓ 投影维全部题上 wsc ≤ nocompress（或任一侧无分母）")
    tp = result["truth_pairing"]
    L += ["", "## 机械三件套 vs 外部 reward（预测力，不是成功率）", "",
          f"- 可用会话 {tp['usable_sessions']}（需有外部真值且 A1–A3 可判）", ""]
    if tp["usable_sessions"]:
        c = tp["cells"]
        L += ["| | 真值通过 | 真值失败 |", "|---|---|---|",
              f"| 三件套通过 | {c['pred_ok_true_ok']} | {c['pred_ok_true_fail']} |",
              f"| 三件套失败 | {c['pred_fail_true_ok']} | {c['pred_fail_true_fail']} |"]
        for d in tp["disagreements"][:8]:
            L.append(f"- 分歧 `{d['sid']}` reward={d['reward']}")
        L.append("")
        L.append(f"> {tp['note']}")
    else:
        L += ["- 无可用样本（语料没有外部真值 ⇒ 只能当调试线索，报告不做任何成功率推断）", ""]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WSC 问答集离线裁定器")
    ap.add_argument("--corpus", choices=("evidence", "legacy"), default="evidence")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(REPO_ROOT / "_wsc_out" / "qa_judge"))
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--no-bash-write", action="store_true",
                    help="不注册 bash 重定向写判据（A/B 对照用：容器任务的改盘全走 bash，"
                         "关掉它 A1–A3 就没有分母）")
    ap.add_argument("--invoke", choices=("every-turn", "prod"), default="every-turn",
                    help=(
                        "**什么时候折**（调用方节奏，WSC 算法层不读它）。"
                        "every-turn（默认）= 每回合都尝试折叠 ⇒ **生产现状**"
                        "（runtime 一旦 compact_cursor>0 就每枪重投影，且生产侧无人读 fold_cadence）；"
                        "prod = cadence 成本节奏（replay 的 adopted 档）：按 synaptic.cadence 判据"
                        "决定折叠，且一旦压过就一直发「冻结头 + cursor 之后原文」"
                        "⇒ **生产未接线这条判据**，它测的是应然节奏不是现状。"
                        "两个档的分数**不可相减**，报告 provenance.invoke 留痕。"
                    ))
    ap.add_argument("--trigger-ratio", type=float, default=0.8,
                    help="prod 档 fold_cadence!=econ 时的水位闸（生产取 0.8）")
    ap.add_argument("--context-limit", type=int, default=0,
                    help="prod 档水位闸的窗口上限 token；0 = 不设（econ 档用不到）")
    args = ap.parse_args(argv)
    bash_write = not args.no_bash_write
    if bash_write:
        install_bash_write_probe()
    params = production_params()
    if args.corpus == "evidence":
        sessions = resolve_evidence(DEFAULT_EVIDENCE, limit=args.limit or None)
    else:
        sessions = resolve_jsonl_dir(LEGACY_CODEX, limit=args.limit or None)
    if not sessions:
        print(json.dumps({"status": "corpus_missing", "corpus": args.corpus}, ensure_ascii=False))
        return 2
    arms = tuple(a for a in args.arms.split(",") if a in ARMS)
    views = Path(args.out) / "wsc_views"
    views.mkdir(parents=True, exist_ok=True)
    result = run(sessions, arms=arms, params=params, view_dir=views,
                 invoke=args.invoke, trigger_ratio=args.trigger_ratio,
                 context_limit=args.context_limit)
    result["provenance"]["bash_write_probe"] = "on" if bash_write else "off"
    result["provenance"]["knobs"] = {
        "hot_budget_tokens": params.hot_budget_tokens,
        "invoke": args.invoke,
        "trigger_ratio": args.trigger_ratio,
        "context_limit_tokens": args.context_limit,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "wsc_qa_report.json").write_text(json.dumps(
        {k: v for k, v in result.items() if k != "per_session_answers"},
        ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "wsc_qa_report.md").write_text(render_md(result), encoding="utf-8")
    agg = result["aggregate"]
    print(f"会话 {len(sessions)}（外部真值 {result['corpus']['with_external_truth']}）"
          f"→ {out / 'wsc_qa_report.md'}")
    print(f"  被评投影 = memory.wsc_projection.production_params() · "
          f"节奏 invoke={args.invoke}"
          f"{'  ← cadence 应然节奏（生产未接线）' if args.invoke == 'prod' else '  ← 生产现状（每枪重投影）'}")
    for qid in ("E1", "V3", "R2", "I1", "I3", "A1", "A3"):
        rec = agg.get("wsc", {}).get(qid) or {}
        other = agg.get("nocompress", {}).get(qid) or {}
        print(f"  {qid:3s} wsc={rec.get('yes')}/{rec.get('total')} "
              f"nocompress={other.get('yes')}/{other.get('total')} "
              f"synth_only={rec.get('synth_only')} status={rec.get('status')}")
    hs = result.get("hot_stats") or {}
    if hs.get("turns"):
        print(f"  热层(逐回合·生产配置) median {hs.get('hot_tokens_median')} / "
              f"p90 {hs.get('hot_tokens_p90')} / max {hs.get('hot_tokens_max')}"
              f"（名义注意力预算 {hs.get('nominal_hot_budget')}，超 {hs.get('over_nominal_budget')} / "
              f"{hs.get('turns')} 回合，未过闸 {hs.get('skipped_gate')}）"
              f"  三桶：注意力 {hs.get('attention_tokens_median')} + 索引 "
              f"{hs.get('index_tokens_median')}/{hs.get('index_budget_tokens')}"
              + (f" ⇒ **索引超帽 {hs.get('index_over_turns')} 回合（只报账不删）**"
                 if hs.get("index_over_turns") else "")
              + f"  UNRESOLVED行 median {hs.get('unresolved_lines_median')}")
    if result["violations"]:
        print("  臂对称违规:", ", ".join(v["qid"] for v in result["violations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
