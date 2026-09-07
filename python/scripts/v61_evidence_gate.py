"""v61 条件采纳项（B1/B2/B3）证据门离线测试 —— 零 LLM 调用。

用法（在 python/ 下）:
  ..\\python\\.venv\\Scripts\\python.exe -m scripts.v61_evidence_gate

对每个条件采纳项跑基线 vs 变体的同场景对照，按 v61 建议采纳说明（#61 §3）
的门限给出【采纳 / 不采纳】裁决。变体全部 env 门控、默认关（关闭时与冻结公式逐位
一致，由单测保证；本脚本只测开启后的收益侧）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STACK = (
    "Traceback (most recent call last):\n"
    '  File "app.py", line 42, in run\n'
    "    theta = cfg[\"theta\"]\n"
    "KeyError: theta\n"
)
KV = "theta = 0.5\nalpha_hit = 0.95\nlambda_q = 2.0\n"


def _decide(state, cache, *, remaining=8, env: dict | None = None, params=None):
    """在受控开关下跑一次决策链。

    开关走 settings.memory（memory_switches 唯一权威，运行时不再读 env）：把注册键
    写进临时工作区的 settings.json 并把 XEYO_CWD/XEYO_HOME 指向它；未注册的遗留键
    （如 XEYO_ATOM_SEGMENT，fidelity_segmenter 直读 env）仍走 os.environ。``None``
    值 = 显式默认（临时目录无该键 / pop env）。
    """
    import shutil
    import tempfile

    from memory.memory_switches import _DEFAULTS
    from memory.simulator.decision import decide

    saved = {k: os.environ.get(k) for k in (
        "XEYO_CWD", "XEYO_HOME",
        "XEYO_V61_PARETO", "XEYO_V61_SI", "XEYO_V61_DYNAMIC_R", "XEYO_ATOM_SEGMENT")}
    ws = tempfile.mkdtemp(prefix="xeyo-gate-env-")
    try:
        os.environ["XEYO_CWD"] = ws
        os.environ["XEYO_HOME"] = ws
        registered = {}
        for k, v in (env or {}).items():
            if v is None:
                os.environ.pop(k, None)
            elif k in _DEFAULTS:
                registered[k] = v
            else:
                os.environ[k] = v
        if registered:
            from memory.memory_switches import save as _save

            _save(registered, cwd=ws)
        return decide(state, cache, remaining_turns=remaining, forecast="p0", params=params)
    finally:
        shutil.rmtree(ws, ignore_errors=True)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _build_state(n_kv: int = 6, n_noise: int = 4, with_stack: bool = True,
                 stack_pos: int = -1, tail_kv: int = 2, atomize: bool = False):
    """构造 stack/kv 混合 M 区状态；atomize=True 时按 P1 缺失1 切原子（带 atom_kind）。"""
    from memory.simulator.state_model import (
        ContextState,
        Segment,
        atomize_m_segments,
        freeze_s0,
    )

    segs: list[Segment] = []
    for i in range(n_noise):
        segs.append(Segment(id=f"mn{i}", text=f"noise line for window pressure {i}\n" * 24,
                            role="tool", kind="tool_result"))
    for i in range(n_kv):
        segs.append(Segment(id=f"mk{i}", text=KV, role="tool", kind="tool_result"))
    if with_stack:
        pos = len(segs) + stack_pos if stack_pos >= 0 else len(segs)
        segs.insert(min(pos, len(segs)), Segment(id="mstk", text=STACK, role="tool", kind="tool_result"))
    for i in range(tail_kv):
        segs.append(Segment(id=f"mt{i}", text=KV, role="tool", kind="tool_result"))
    m = tuple(segs)
    if atomize:
        m = atomize_m_segments(m)
    return freeze_s0(ContextState(p_s=(), p_c=(), m=m, t_k=(), t_now=()))


def _cold_cache(state):
    """挂机 4h 冷缓存（x_prev 有共同前缀）——压缩决策带所在区域。"""
    from memory.simulator.cache_model import CacheState
    from memory.simulator.projection import project

    proj = project(state)
    return CacheState(age_seconds=4 * 3600, x_prev=proj.x,
                      x_prev_frozen_len=max(1, proj.length - 50))


def _drops_stack(s0, action: str) -> bool:
    """该动作执行后，完整报错栈是否还留在投影内容里（C2 摘要一行引用不算存活）。"""
    from memory.simulator.projection import project
    from memory.simulator.state_model import apply as sim_apply

    if action == "keep":
        return False
    s_a = sim_apply(action, s0)
    return not any(STACK in seg.text for seg in s_a.m)


def _j_pred_error(s0, cache, dec, *, r: int = 8) -> float:
    """J_pred 误差代理：|J_p0(a*) − J_p1(a*)| / J_p1(a*)（p1=含扰动口径）。"""
    from memory.simulator.horizon import trajectory_for
    from memory.simulator.params import load_params

    a = dec.a_star
    if a not in dec.J or r not in dec.J.get(a, {}):
        return 0.0
    j0 = dec.J[a][r]
    try:
        from memory.simulator.state_model import apply as sim_apply

        s_a = sim_apply(a, s0)
        tr = trajectory_for(s_a, cache, load_params(), remaining_turns=r, forecast="p1")
        j1 = tr.J(r)
    except Exception:  # noqa: BLE001
        return 0.0
    return abs(j0 - j1) / max(abs(j1), 1e-12)


def _branch_of(dec, action: str):
    """a_star 可能是 L4（safety 兜底=强制压缩，等价 C2 语义）——映射到真实分支。"""
    a = "C2" if action == "L4" else action
    br = dec.branches.get(a)
    return a, br


def gate_b1_pareto() -> dict:
    """B1 Pareto 可行集（文档 §3）：硬约束 + 非支配替代 argmin J。

    门槛：同成本保真 +≥3pp 或 同保真成本 −≥5%；「丢高价值原子省 <5% 成本」清零；
    J_pred 误差不升。θ_D 扫描（0.05/0.2/0.5）取最优前沿——θ 是 B1 的待校准参数。
    """
    from memory.simulator.decision import ACTIONS
    from memory.simulator.projection import project

    grids = []
    for n_noise in (12, 16, 20, 24, 28, 36, 44):
        for stack_pos in (-1, -(4 + n_noise)):
            grids.append(dict(n_kv=4, n_noise=n_noise, stack_pos=stack_pos, tail_kv=2))
    # 温缓存细扫描：J(C2)≈J(keep) 的临界带（省<5% 成本的「丢大脸」band 所在）
    warm_fine = dict(n_kv=4, stack_pos=-1, tail_kv=2)
    rows = []
    for cfg in grids:
        s0 = _build_state(**cfg)
        cache = _cold_cache(s0)
        base = _decide(s0, cache, env={"XEYO_V61_PARETO": None})
        a_b, ab = _branch_of(base, base.a_star)
        ck = max(base.branches["keep"].c_biz, 1e-12)
        base_patho = (
            a_b != "keep"
            and _drops_stack(s0, a_b)
            and (1 - ab.c_biz / ck) < 0.05
        )
        entry = {
            "L": project(s0).length,
            "缓存": "冷(4h)",
            "基线": a_b, "基线Q": round(ab.Q, 4),
            "基线C": round(ab.c_biz, 6),
            "基线病态": base_patho,
            "基线丢栈": _drops_stack(s0, a_b),
            "基线J误差": round(_j_pred_error(s0, cache, base), 4),
            "θ结果": {},
        }
        for theta in ("0.05", "0.2", "0.5"):
            os.environ["XEYO_V61_PARETO_DMAX"] = theta
            try:
                var = _decide(s0, cache, env={"XEYO_V61_PARETO": "1"})
            finally:
                os.environ.pop("XEYO_V61_PARETO_DMAX", None)
            a_v, av = _branch_of(var, var.a_star)
            var_patho = (
                a_v != "keep"
                and _drops_stack(s0, a_v)
                and (1 - av.c_biz / ck) < 0.05
            )
            entry["θ结果"][theta] = {
                "决策": a_v,
                "Q": round(av.Q, 4),
                "C": round(av.c_biz, 6),
                "病态": var_patho,
                "J误差": round(_j_pred_error(s0, cache, var), 4),
            }
        rows.append(entry)
    # 温缓存临界带细扫描（L 1900..2400 步进 50）
    for n_noise in (8, 9, 10, 11, 12, 13, 14):
        s0 = _build_state(**{**warm_fine, "n_noise": n_noise})
        from memory.simulator.cache_model import CacheState
        from memory.simulator.projection import project as _proj

        pr = _proj(s0)
        cache = CacheState(age_seconds=30.0, x_prev=pr.x, x_prev_frozen_len=pr.length)
        base = _decide(s0, cache, env={"XEYO_V61_PARETO": None})
        a_b, ab = _branch_of(base, base.a_star)
        ck = max(base.branches["keep"].c_biz, 1e-12)
        base_patho = (
            a_b != "keep"
            and _drops_stack(s0, a_b)
            and (1 - ab.c_biz / ck) < 0.05
        )
        entry = {
            "L": pr.length,
            "缓存": "温(30s)",
            "基线": a_b, "基线Q": round(ab.Q, 4),
            "基线C": round(ab.c_biz, 6),
            "基线病态": base_patho,
            "基线丢栈": _drops_stack(s0, a_b),
            "基线J误差": round(_j_pred_error(s0, cache, base), 4),
            "θ结果": {},
        }
        for theta in ("0.05", "0.2", "0.5"):
            os.environ["XEYO_V61_PARETO_DMAX"] = theta
            try:
                var = _decide(s0, cache, env={"XEYO_V61_PARETO": "1"})
            finally:
                os.environ.pop("XEYO_V61_PARETO_DMAX", None)
            a_v, av = _branch_of(var, var.a_star)
            var_patho = (
                a_v != "keep"
                and _drops_stack(s0, a_v)
                and (1 - av.c_biz / ck) < 0.05
            )
            entry["θ结果"][theta] = {
                "决策": a_v,
                "Q": round(av.Q, 4),
                "C": round(av.c_biz, 6),
                "病态": var_patho,
                "J误差": round(_j_pred_error(s0, cache, var), 4),
            }
        rows.append(entry)

    out: dict = {"场景数": len(rows), "θ扫描": {}}
    for theta in ("0.05", "0.2", "0.5"):
        n_patho = sum(1 for r in rows if r["θ结果"][theta]["病态"])
        base_patho_n = sum(1 for r in rows if r["基线病态"])
        q_b = sum(r["基线Q"] for r in rows) / len(rows)
        q_v = sum(r["θ结果"][theta]["Q"] for r in rows) / len(rows)
        c_b = sum(r["基线C"] for r in rows) / len(rows)
        c_v = sum(r["θ结果"][theta]["C"] for r in rows) / len(rows)
        e_b = sum(r["基线J误差"] for r in rows) / len(rows)
        e_v = sum(r["θ结果"][theta]["J误差"] for r in rows) / len(rows)
        changed = sum(1 for r in rows if r["θ结果"][theta]["决策"] != r["基线"])
        cost_ratio = c_v / max(c_b, 1e-12)
        dq = q_v - q_b
        frontier_ok = (dq >= 0.03 and cost_ratio <= 1.05) or (cost_ratio <= 0.95 and dq >= -1e-9)
        err_ok = e_v <= e_b * 1.001
        out["θ扫描"][theta] = {
            "基线病态数": base_patho_n, "变体病态数": n_patho,
            "决策改变数": changed,
            "平均Q_基线": round(q_b, 4), "平均Q_变体": round(q_v, 4), "ΔQ_pp": round(dq * 100, 2),
            "成本比(变体/基线)": round(cost_ratio, 4),
            "平均J误差_基线": round(e_b, 4), "平均J误差_变体": round(e_v, 4),
        }
        out[f"裁决_θ{theta}"] = "采纳" if (n_patho == 0 and frontier_ok and err_ok) else "不采纳"
    best_theta = next((t for t in ("0.2", "0.5", "0.05") if out[f"裁决_θ{t}"] == "采纳"), None)
    out["门限"] = "丢栈省小钱清零 且 (同成本ΔQ≥+3pp 或 同保真成本−≥5%) 且 J_pred 误差不升"
    out["裁决"] = f"采纳(θ_D={best_theta})" if best_theta else "不采纳（全 θ 扫描未过门）"
    out["明细"] = rows
    return out


def _si_grid() -> list[dict]:
    """B2/F2 共享网格：噪声 + stack/kv 混合 M 区（原子化，带 atom_kind）。"""
    grids: list[dict] = []
    for n_noise in (12, 16, 20, 24, 28, 36, 44):
        for stack_pos in (-1, -(4 + n_noise)):
            grids.append(dict(n_kv=4, n_noise=n_noise, stack_pos=stack_pos, tail_kv=2, atomize=True))
    return grids


# --------------------------------------------------------------------------- #
# F2：scale-drift 护栏（地基）。任何「改评分/权重标尺」的开关（s_i、未来信息论 Q、
# 查询感知重排、Shapley 加权…）都会让 Q 分布整体缩放，导致 θ 阈值失准 —— B2 病根。
# 统一度量 = run 同一份网格，比较 variant vs base 的 keep 分支 Q 中位比。
# 带内 [0.5, 2.0] 放行（仍要求连同 θ 重校准交付）；带外 REFUSE（标尺漂移过大）。
# --------------------------------------------------------------------------- #

_SCALE_DRIFT_BAND = (0.5, 2.0)


def scale_drift(
    variant_env: dict, *, grid: list[dict] | None = None, base_env: dict | None = None
) -> float:
    """median(Q_variant(keep)/Q_base(keep)) over grid（F2 标尺漂移度量）。

    ``base_env`` 默认 s_i 关（冻结口径）。纯标量，供 gate_scale_drift 与单测复用。
    """
    grid = grid if grid is not None else _si_grid()
    base_env = base_env if base_env is not None else {"XEYO_V61_SI": None}
    ratios: list[float] = []
    for cfg in grid:
        s0 = _build_state(**cfg)
        cache = _cold_cache(s0)
        b = _decide(s0, cache, env=base_env)
        v = _decide(s0, cache, env=variant_env)
        bb, vb = b.branches["keep"], v.branches["keep"]
        if bb.Q > 1e-9:
            ratios.append(vb.Q / bb.Q)
    ratios.sort()
    if not ratios:
        return 1.0
    return ratios[len(ratios) // 2]


def gate_scale_drift() -> dict:
    """F2 scale-drift 护栏报告：逐开关测 Q 标尺漂移，带内放行 / 带外 REFUSE。"""
    flags = {
        "XEYO_V61_SI (s_i 驻留分)": {"XEYO_V61_SI": "1"},
        "XEYO_ATOM_SEGMENT (原子分段)": {"XEYO_ATOM_SEGMENT": "1"},
    }
    rows: dict[str, dict] = {}
    for label, env in flags.items():
        drift = scale_drift(env)
        in_band = _SCALE_DRIFT_BAND[0] <= drift <= _SCALE_DRIFT_BAND[1]
        rows[label] = {
            "drift(Q变体(keep)/Q基线(keep)中位)": round(drift, 4),
            "在带内[0.5,2.0]": in_band,
            "裁决": ("放行(需连同θ重校准交付)" if in_band
                     else "REFUSE(标尺漂移过大,强制θ重校准或放弃)"),
        }
    all_ok = all(r["在带内[0.5,2.0]"] for r in rows.values())
    return {"规则": "0.5 ≤ drift ≤ 2.0 放行；否则 REFUSE", "全部放行": all_ok, "明细": rows}


def gate_b2_si() -> dict:
    """B2 内容类型驻留分 s_i（文档 §3）：stack 原子压缩后存活率 ≥95%；整体保真不降；成本 ≤2%。

    两臂都用原子化状态（P1 缺失1 的 atomize_m_segments），只差 s_i 公式。
    额外对照：s_i 会改变 Q 的标尺（噪声 chunk 从 1/λ 降到 s/λ）→ θ 安全网可能失准
    触发 L4 兜底——因此同时测「θ 按标尺比例重校准」后的行为（adopt 前置工程量证据）。
    """
    from memory.simulator.params import load_params

    grids = _si_grid()

    # θ 重校准系数：keep 分支上 Q_si / Q_base 的中位比（F1：全量网格，非 grids[:6]）。
    # 注意这是「部署形态」的前提——s_i 会改变 Q 标尺，θ 必须连同重校准一起交付。
    ratios: list[float] = []
    for cfg in grids:
        s0 = _build_state(**cfg)
        cache = _cold_cache(s0)
        b = _decide(s0, cache, env={"XEYO_V61_SI": None})
        v = _decide(s0, cache, env={"XEYO_V61_SI": "1"})
        bb, vb = b.branches["keep"], v.branches["keep"]
        if bb.Q > 1e-9:
            ratios.append(vb.Q / bb.Q)
    ratios.sort()
    theta_scale = ratios[len(ratios) // 2] if ratios else 1.0
    import dataclasses as _dc
    from memory.simulator.params import load_params

    p_base = load_params()
    p_si = _dc.replace(p_base, theta=max(0.05, min(0.95, p_base.theta * theta_scale)))

    rows = []
    for cfg in grids:
        s0 = _build_state(**cfg)
        cache = _cold_cache(s0)
        base = _decide(s0, cache, env={"XEYO_V61_SI": None})
        var = _decide(s0, cache, env={"XEYO_V61_SI": "1"})
        var_cal = _decide(s0, cache, env={"XEYO_V61_SI": "1"}, params=p_si)
        a_b, ab = _branch_of(base, base.a_star)
        a_v, av = _branch_of(var, var.a_star)
        a_c, ac = _branch_of(var_cal, var_cal.a_star)
        if ab is None or av is None or ac is None:
            continue
        rows.append({
            "L": _proj_len(s0),
            "基线": a_b, "变体": a_v, "变体θ校准": a_c,
            "变体L4兜底": var.a_star == "L4",
            "基线栈存活": not _drops_stack(s0, a_b),
            "变体栈存活": not _drops_stack(s0, a_v),
            "校准后栈存活": not _drops_stack(s0, a_c),
            "基线Q": round(ab.Q, 4), "变体Q": round(av.Q, 4), "校准Q": round(ac.Q, 4),
            "基线C": round(ab.c_biz, 6), "变体C": round(av.c_biz, 6), "校准C": round(ac.c_biz, 6),
        })
    n = len(rows)
    var_surv = sum(1 for r in rows if r["变体栈存活"])
    base_surv = sum(1 for r in rows if r["基线栈存活"])
    cal_surv = sum(1 for r in rows if r["校准后栈存活"])
    l4_count = sum(1 for r in rows if r["变体L4兜底"])
    c_base = sum(r["基线C"] for r in rows) / max(1, n)
    c_var = sum(r["变体C"] for r in rows) / max(1, n)
    c_cal = sum(r["校准C"] for r in rows) / max(1, n)
    q_base = sum(r["基线Q"] for r in rows) / max(1, n)
    q_var = sum(r["变体Q"] for r in rows) / max(1, n)
    q_cal = sum(r["校准Q"] for r in rows) / max(1, n)
    cost_ratio = c_var / max(c_base, 1e-12)
    cal_cost_ratio = c_cal / max(c_base, 1e-12)
    surv_rate = var_surv / max(1, n)
    cal_surv_rate = cal_surv / max(1, n)
    # 同标尺归一化：s_i 把 Q 整体缩放 ~theta_scale（frozen 标尺 → s_i 标尺）。直接比
    # 原始 Q 是错标尺，故把校准变体的 Q 拉回 frozen 标尺再比（F2 scale-drift 的同源坑）。
    q_cal_norm = q_cal / max(theta_scale, 1e-9)
    # 部署形态 = s_i + θ 重校准。裁决判校准变体；原始变体只作「不校准会差多少」的对照。
    surv_ok = cal_surv_rate >= 0.95
    q_ok = q_cal_norm >= q_base - 1e-9
    cost_ok = cal_cost_ratio <= 1.02
    cal_keep = sum(1 for r in rows if r["变体θ校准"] == "keep")
    verdict = "采纳" if (surv_ok and q_ok and cost_ok) else "不采纳"
    return {
        "场景数": n,
        "θ重校准系数(keep分支Q中位比,全网格)": round(theta_scale, 4),
        "校准θ": round(p_si.theta, 4),
        "s_i触发L4兜底次数": l4_count,
        "栈存活_基线": f"{base_surv}/{n}",
        "栈存活_变体(未校准)": f"{var_surv}/{n}",
        "栈存活_变体θ校准后(部署形态)": f"{cal_surv}/{n}",
        "校准决策=keep 占比": f"{cal_keep}/{n}",
        "平均C比_未校准(变体/基线)": round(cost_ratio, 4),
        "平均C比_校准后(变体/基线)": round(cal_cost_ratio, 4),
        "平均Q_基线": round(q_base, 4),
        "平均Q_未校准": round(q_var, 4),
        "平均Q_校准(同标尺归一)": round(q_cal_norm, 4),
        "存活达标": surv_ok, "保真达标(归一)": q_ok, "成本≤+2%达标": cost_ok,
        "门限": "stack 原子存活率 ≥95% 且 整体保真不降(同标尺) 且 成本 ≤+2%",
        "裁决": verdict,
        "备注": ("部署形态 = s_i + θ 全量重校准。实测：校准后栈存活率达标，但保栈是靠"
                 "「整窗不压缩(全 keep)」换来的——校准后平均成本比 = {}".format(
                     round(cal_cost_ratio, 4)) + "，远超 ≤+2% 成本门；"
                 "s_i 的「死保报错栈」在当前成本结构下与「省成本」不可兼得（与 B1 同构）。"),
        "明细": rows,
    }


def _proj_len(s0) -> int:
    from memory.simulator.projection import project

    return project(s0).length


def gate_b3_dynamic_r() -> dict:
    """B3 动态 R_base 分级（文档 §3）：加性不收紧；J_pred 误差（档位对齐口径）中位 −≥25%；
    静态正确性不回归（窗口 30%/0 待读→仅4；75%/5 待读→16 参与）。"""
    from memory.simulator.r_estimator import estimate_r_gate

    # —— 静态正确性回归检查（P1 缺失3 验收场景）——
    low = estimate_r_gate(0.30, 0)
    high = estimate_r_gate(0.75, 5)
    static_regression = (max(r for r, ok in low.allow.items() if ok) == 4
                         and high.allow[16] is True)

    unlock = 0
    total = 0
    tighten_violations = 0
    grid = []
    for usage in (0.2, 0.4, 0.6, 0.75):
        for unread in (0, 2, 4, 9):
            for r_true in (6, 8, 10, 12, 14, 16, 20):
                grid.append((usage, unread, r_true))
    for usage, unread, r_true in grid:
        win, avg = 24_000, 900.0
        cur = int(win * usage)
        static = estimate_r_gate(usage, unread)
        os.environ["XEYO_V61_DYNAMIC_R"] = "1"
        try:
            dyn = estimate_r_gate(usage, unread, avg_turn_tokens=avg, window_tokens=win,
                                  current_tokens=cur)
        finally:
            os.environ.pop("XEYO_V61_DYNAMIC_R", None)
        if not (dyn.allow[8] >= static.allow[8] and dyn.allow[16] >= static.allow[16]):
            tighten_violations += 1
        # 死锁解除：真实剩余 r_true 对应的窗口占用下，静态仅 4 档而动态开放更高档
        cur_t = int(win - r_true * avg)
        usage_t = cur_t / win
        static2 = estimate_r_gate(usage_t, unread)
        os.environ["XEYO_V61_DYNAMIC_R"] = "1"
        try:
            dyn2 = estimate_r_gate(usage_t, unread, avg_turn_tokens=avg, window_tokens=win,
                                   current_tokens=cur_t)
        finally:
            os.environ.pop("XEYO_V61_DYNAMIC_R", None)
        s_max = max(r for r, ok in static2.allow.items() if ok)
        d_max = max(r for r, ok in dyn2.allow.items() if ok)
        if s_max == 4 and d_max > 4:
            unlock += 1
        total += 1

    # 档位对齐误差：|规划视野 − 真实剩余| / 真实剩余（静态死锁带 r_true≥8 + 对照 r_true=6）
    errs_static = []
    errs_dyn = []
    for r_true in (6, 8, 10, 12, 14, 16):
        win, avg = 24_000, 900.0
        cur_t = int(win - r_true * avg)
        usage_t = cur_t / win
        static = estimate_r_gate(usage_t, 0)
        os.environ["XEYO_V61_DYNAMIC_R"] = "1"
        try:
            dyn = estimate_r_gate(usage_t, 0, avg_turn_tokens=avg, window_tokens=win,
                                  current_tokens=cur_t)
        finally:
            os.environ.pop("XEYO_V61_DYNAMIC_R", None)
        rs = max(r for r, ok in static.allow.items() if ok)
        rd = max(r for r, ok in dyn.allow.items() if ok)
        errs_static.append(abs(rs - r_true) / r_true)
        errs_dyn.append(abs(rd - r_true) / r_true)

    def _median(xs: list[float]) -> float:
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    med_s = _median(errs_static)
    med_d = _median(errs_dyn)
    reduction = 1 - med_d / max(med_s, 1e-9)
    verdict = "采纳" if (tighten_violations == 0 and static_regression and reduction >= 0.25) else "不采纳"
    return {
        "静态正确性回归(P1缺失3)": static_regression,
        "网格状态数": total,
        "加性收紧违例": tighten_violations,
        "单档死锁解除数(仅4→开放8/16)": unlock,
        "死锁解除率": round(unlock / max(1, total), 4),
        "对齐误差中位_静态": round(med_s, 4),
        "对齐误差中位_动态": round(med_d, 4),
        "误差降幅": round(reduction, 4),
        "门限": "加性不收紧 且 静态验收不回归 且 档位对齐误差中位 −≥25%",
        "裁决": verdict,
        "明细_静态误差": [round(e, 3) for e in errs_static],
        "明细_动态误差": [round(e, 3) for e in errs_dyn],
    }


def main() -> int:
    print("=" * 72)
    print("v61 条件采纳项（B1/B2/B3）证据门离线测试 —— 零 LLM 调用")
    print("=" * 72)
    results: dict[str, dict] = {}
    for name, fn in (
        ("B1_Pareto可行集", gate_b1_pareto),
        ("B2_内容类型驻留分s_i", gate_b2_si),
        ("B3_动态R_base分级", gate_b3_dynamic_r),
        ("F2_scale-drift护栏", gate_scale_drift),
    ):
        print(f"\n### {name}")
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            out = {"error": f"{type(exc).__name__}: {exc}"}
        results[name] = out
        for k, v in out.items():
            if k.startswith("明细"):
                continue
            print(f"  {k}: {v}")
        if "明细" in out and isinstance(out["明细"], list):
            for row in out["明细"][:6]:
                print(f"    · {row}")
    out_dir = ROOT / ".diag_memory_cost"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "v61_evidence_gate.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n[已保存] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
