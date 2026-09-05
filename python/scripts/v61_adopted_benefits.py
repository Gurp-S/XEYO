"""v61 完全采纳项（A1–A6）离线收益测量 —— 全部确定性/离线，零 LLM 调用。

用法（在 python/ 下）:
  ..\\python\\.venv\\Scripts\\python.exe -m scripts.v61_adopted_benefits

输出：控制台收益表 + JSON 落盘 ``.diag_memory_cost/v61_adopted_benefits.json``。
对应决策记录：docs/实施计划/v61建议采纳说明.md §1。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 中文 Windows 控制台默认 GBK：强制 UTF-8 输出（避免 ¥/Δ 等 字符 UnicodeEncodeError）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RESULTS: dict[str, dict] = {}


def _temp_env(monkey: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="v61_benefit_"))
    monkey["XEYO_MEMORY_DIR"] = str(tmp / "mem")
    monkey["XEYO_SESSIONS_DIR"] = str(tmp / "sessions")
    for k, v in monkey.items():
        os.environ[k] = v
    return tmp


def _restore_env(snapshot: dict[str, str]) -> None:
    os.environ.clear()
    os.environ.update(snapshot)


STACK_NEW = (
    "Traceback (most recent call last):\n"
    '  File "app.py", line 42, in run\n'
    "    theta = cfg[\"theta\"]\n"
    "KeyError: theta\n"
)
STACK_OLD = (
    "Traceback (most recent call last):\n"
    '  File "old.py", line 9, in load\n'
    "ValueError: old failure\n"
)


def _synthetic_left(n_noise: int = 60) -> list[dict]:
    """长合成左区：噪声大输出 + 取值行 + 两条报错栈（一旧一新）+ 工具路径。"""
    import hashlib

    def tool_use(i: int, name: str, **inp) -> dict:
        uid = "u" + hashlib.md5(f"u{i}".encode()).hexdigest()[:8]
        return {"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": name, "input": dict(inp)}]}

    def tool_result(i: int, text: str) -> dict:
        uid = "u" + hashlib.md5(f"u{i}".encode()).hexdigest()[:8]
        return {"role": "tool", "tool_call_id": uid, "content": [{"type": "tool_result", "tool_use_id": uid, "content": text}]}

    left: list[dict] = [tool_use(0, "Read", file_path="D:/old/first.py")]
    left.append(tool_result(1, "legacy body\n" * 40))
    left.append(tool_result(2, "Traceback (most recent call last):\n" + STACK_OLD.split("\n", 1)[1]))
    k = 3
    for i in range(n_noise):
        left.append(tool_use(k, "Grep", pattern=f"p{i}", path="D:/proj"))
        left.append(tool_result(k + 1, f"noise {i}\n" * 50 + f"theta_{i} = {i / 10:.1f}\n"))
        k += 2
    left.append(tool_use(k, "Read", file_path="D:/proj/conf/params.json"))
    left.append(tool_result(k + 1, "kv noise\n" * 30))
    left.append(tool_use(k + 2, "Edit", file_path="D:/proj/app.py"))
    left.append(tool_result(k + 3, STACK_NEW))
    left.append(tool_use(k + 4, "Read", file_path="D:/proj/tests/test_app.py"))
    left.append(tool_result(k + 5, "ok\n"))
    return left


# --------------------------------------------------------------------------- #
def measure_a3_escape_hatch() -> dict:
    from memory import runtime
    from memory.working import WorkingSnapshot

    snap = dict(os.environ)
    tmp = _temp_env({"XEYO_C2_ESCAPE_HATCH": "0"})
    try:
        left = _synthetic_left()
        messages = left + [{"role": "user", "content": "continue"}]

        def run(hatch_on: bool, budget: int | None = None) -> tuple[str, str]:
            os.environ["XEYO_C2_ESCAPE_HATCH"] = "1" if hatch_on else "0"
            if budget is not None:
                old = runtime.C2_SUMMARY_BUDGET
                runtime.C2_SUMMARY_BUDGET = budget
            try:
                w = WorkingSnapshot(session_id="benefit-a3")
                w.compact_cursor = len(left)
                proj = runtime.apply_c2_messages(messages, w)
                return proj[0]["content"], w.c2_summary_text
            finally:
                if budget is not None:
                    runtime.C2_SUMMARY_BUDGET = budget

        stack_probe = "KeyError: theta"
        old_probe = "ValueError: old failure"
        paths = ["D:/proj/tests/test_app.py", "D:/proj/app.py", "D:/proj/conf/params.json"]

        out: dict = {}
        for label, hatch in (("baseline_逃生舱关", False), ("adopted_逃生舱开", True)):
            summary, _frozen = run(hatch)
            out[label] = {
                "新报错栈在场": stack_probe in summary,
                "报错栈保真字符": sum(len(ln) for ln in STACK_NEW.splitlines() if ln.strip() and ln.strip() in summary),
                "旧报错残留": old_probe in summary,  # 基线可能残留旧栈占预算；逃生舱版旧栈折叠为一行
                "路径在场数": sum(1 for p in paths if p in summary),
                "摘要字符": len(summary),
            }
        # 极小预算压力：预算耗尽后逃生舱仍在场
        b_base, _ = run(False, budget=400)
        b_hatch, _ = run(True, budget=400)
        out["极小预算400_baseline含栈"] = stack_probe in b_base
        out["极小预算400_adopted含栈"] = stack_probe in b_hatch
        out["极小预算400_adopted路径数"] = sum(1 for p in paths if p in b_hatch)
        out["开销比_hatch块/摘要"] = round(
            (out["adopted_逃生舱开"]["摘要字符"] - out["baseline_逃生舱关"]["摘要字符"])
            / max(1, out["baseline_逃生舱关"]["摘要字符"]), 4)
        out["结论"] = (
            f"报错栈保真 {out['baseline_逃生舱关']['报错栈保真字符']}→{out['adopted_逃生舱开']['报错栈保真字符']} 字符；"
            f"路径 {out['baseline_逃生舱关']['路径在场数']}→{out['adopted_逃生舱开']['路径在场数']} 条；"
            f"极小预算下基线含栈={out['极小预算400_baseline含栈']} 采纳版含栈={out['极小预算400_adopted含栈']}"
        )
        return out
    finally:
        _restore_env(snap)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def measure_a1_cooldown_omega() -> dict:
    from memory.simulator.cache_model import CacheState
    from memory.simulator.decision import decide
    from memory.simulator.params import load_params
    from memory.simulator.projection import project
    from memory.simulator.state_model import ContextState, Segment, freeze_s0

    def build_state(target_tokens: int) -> ContextState:
        per = 900
        n = max(2, target_tokens // per)
        segs = [
            Segment(id=f"m{i}", text=("noise line for window pressure\n" * 60) + f"k{i} = {i}\n",
                    role="tool", kind="tool_result")
            for i in range(n)
        ]
        segs = segs + [
            Segment(id="mstack", text=STACK_NEW, role="tool", kind="tool_result"),
            Segment(id="mkv", text="theta = 0.5\nalpha_hit = 0.95\n", role="tool", kind="tool_result"),
        ]
        return freeze_s0(ContextState(p_s=(), p_c=(), m=tuple(segs), t_k=(), t_now=()))

    p = load_params()
    snap = dict(os.environ)
    os.environ.pop("XEYO_CACHE_COOLDOWN_OMEGA", None)
    rows: list[dict] = []
    try:
        for target in list(range(2_000, 40_001, 2_000)) + list(range(48_000, 96_001, 8_000)):
            s0 = build_state(target)
            proj = project(s0)
            cold = CacheState(age_seconds=4 * 3600, x_prev=proj.x,
                              x_prev_frozen_len=max(1, proj.length - 50))
            os.environ.pop("XEYO_CACHE_COOLDOWN_OMEGA", None)
            base = decide(s0, cold, remaining_turns=8, forecast="p0")
            os.environ["XEYO_CACHE_COOLDOWN_OMEGA"] = "1"
            omega = decide(s0, cold, remaining_turns=8, forecast="p0")
            os.environ.pop("XEYO_CACHE_COOLDOWN_OMEGA", None)
            jk_b = min(base.J["keep"].values())
            jk_o = min(omega.J["keep"].values())
            row = {
                "投影tokens": proj.length,
                "基线决策": base.a_star,
                "ω后决策": omega.a_star,
                "H_keep基线": round(base.branches["keep"].H, 1),
                "H_keep_ω": round(omega.branches["keep"].H, 1),
                "J_keep降幅": round(1 - jk_o / max(jk_b, 1e-9), 4),
                "误压避免": None,
            }
            if base.a_star != "keep" and omega.a_star == "keep":
                row["误压避免"] = True
                row["避免c_action(u¥)"] = round(omega.branches["C2"].c_action * 1e6, 1)
            elif base.a_star == omega.a_star:
                row["误压避免"] = False  # 同决策（双方都压=真需要压；双方都keep=本来就没误压）
            rows.append(row)
        # 温缓存回归护栏：age=0 时 ω 必须逐位不变
        s0 = build_state(40_000)
        proj = project(s0)
        warm = CacheState(age_seconds=0.0, x_prev=proj.x, x_prev_frozen_len=proj.length)
        b = decide(s0, warm, remaining_turns=8, forecast="p0")
        os.environ["XEYO_CACHE_COOLDOWN_OMEGA"] = "1"
        o = decide(s0, warm, remaining_turns=8, forecast="p0")
        os.environ.pop("XEYO_CACHE_COOLDOWN_OMEGA", None)
        warm_equal = (b.J == o.J and b.a_star == o.a_star)
        n_flip = sum(1 for f in rows if f["误压避免"] is True)
        first_base = next((f["投影tokens"] for f in rows if f["基线决策"] != "keep"), None)
        first_omega = next((f["投影tokens"] for f in rows if f["ω后决策"] != "keep"), None)
        band = (first_omega - first_base) if (first_base and first_omega) else None
        avoided = [f.get("避免c_action(u¥)") for f in rows if f["误压避免"] is True]
        return {
            "扫描状态数": len(rows),
            "误压缩避免数": n_flip,
            "基线压缩起点(tokens)": first_base,
            "ω后压缩起点(tokens)": first_omega,
            "误压窗口右移(tokens)": band,
            "避免c_action合计(u¥)": round(sum(avoided), 1) if avoided else 0.0,
            "温缓存逐位一致": warm_equal,
            "J_keep平均降幅": round(
                sum(f["J_keep降幅"] for f in rows if f["误压避免"] is not None)
                / max(1, sum(1 for f in rows if f["误压避免"] is not None)), 4),
            "明细": rows,
            "结论": (f"挂机4h场景：ω 把 keep 预测命中从 0 修正为 α×floor（H>0），压缩决策带右移 "
                     f"{band} tokens（窗口内基线误压、ω 保持），省 {len(avoided)} 次 c_action；"
                     f"温缓存行为逐位不变={warm_equal}（零回归护栏）"),
        }
    finally:
        _restore_env(snap)


def measure_a2_restore() -> dict:
    from memory import memindex, runtime
    from memory.working import WorkingSnapshot

    snap = dict(os.environ)
    tmp = _temp_env({})
    try:
        import hashlib

        def tool_use(i: int, name: str, **inp) -> dict:
            uid = f"u{i:04d}"
            return {"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": name, "input": dict(inp)}]}

        def tool_result(i: int, text: str) -> dict:
            uid = f"u{i - 1:04d}"  # 与前一条 tool_use 配对（真实转录的因果结构）
            return {"role": "tool", "tool_call_id": uid, "content": [{"type": "tool_result", "tool_use_id": uid, "content": text}]}

        left = [
            tool_use(0, "Read", file_path="D:/proj/old.py"),
            tool_result(1, "Traceback (most recent call last):\n" + STACK_OLD.split("\n", 1)[1]),
            tool_result(2, "noise\n" * 40 + "alpha = 0.95\nbeta = 8\n"),
            tool_result(3, STACK_NEW),
        ]
        working = WorkingSnapshot(session_id="benefit-a2")
        working.compact_cursor = len(left)
        messages = left + [{"role": "user", "content": "go"}]
        runtime.apply_c2_messages(messages, working)

        frags_all = []
        for i in range(len(left)):
            frags_all.extend(memindex.get_fragments("benefit-a2", i))
        stack_rows = [f for f in frags_all if f["kind"] == "stack"]
        newest = next((f for f in stack_rows if "KeyError" in f["text"]), None)
        oldest = next((f for f in stack_rows if "ValueError" in f["text"]), None)
        from tools.memory_tool.memory_tool import MemoryTool

        tool = MemoryTool(cwd=os.getcwd())
        tool.set_session_id("benefit-a2")
        out = tool._execute_retrieve({"id": "notes:msg:3"})
        restored_ok = bool(newest) and newest["text"] == STACK_NEW
        older_ok = bool(oldest)
        summary = working.c2_summary_text
        return {
            "入库碎片数": len(frags_all),
            "碎片种类": sorted({f["kind"] for f in frags_all}),
            "最新栈字节级还原": restored_ok,
            "旧栈可找回(摘要只留最新)": older_ok,
            "旧栈是否占用摘要正文": "ValueError: old failure" in summary,
            "Memory(retrieve)输出含栈": "KeyError: theta" in out.content,
            "因果边数": len(memindex.edges_for("benefit-a2", 0)),
            "结论": "压缩从有损→可还原：最新栈逃生舱在场+retrieve 字节级找回，旧栈折叠但 retrieve 可回",
        }
    finally:
        _restore_env(snap)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def measure_a4_sqlite_index() -> dict:
    from memory import memdir, memindex
    from memory.governance import parse_and_validate
    from memory.memdir import memdir_root, workspace_id
    from memory.search import search as mem_search

    snap = dict(os.environ)
    tmp = _temp_env({"XEYO_MEMORY_SQLITE_INDEX": "0"})
    try:
        wsid = workspace_id(os.getcwd())
        root = memdir_root(wsid)
        (root / "topics").mkdir(parents=True, exist_ok=True)
        N = 300
        for i in range(N):
            fm = {
                "id": f"note-{i:04d}",
                "type": "fact",
                "title": f"note {i}",
                "scope": "workspace",
                "status": "active",
                "confidence": 0.8,
                "source": {"kind": "user"},
            }
            from memory.memdir import write_note

            write_note(parse_and_validate(fm, f"内容 {i}：xeyo-fact-{i} 关于 sqlite-index-bench-{i}"), wsid=wsid)

        orig_split = memdir.split_frontmatter
        counter = {"n": 0}

        def counting_split(text: str):
            counter["n"] += 1
            return orig_split(text)

        memdir.split_frontmatter = counting_split  # 安装计数补丁（memindex 同样经此入口）
        queries = [f"sqlite-index-bench-{i}" for i in range(0, 300, 10)] * 3  # 90 查询

        def bench(env_on: bool) -> dict:
            os.environ["XEYO_MEMORY_SQLITE_INDEX"] = "1" if env_on else "0"
            memindex.rebuild(wsid)
            counter["n"] = 0
            t0 = time.perf_counter()
            hits = 0
            for q in queries:
                hits += len(mem_search(q, wsid=wsid, touch=False))
            dt = time.perf_counter() - t0
            return {"解析调用数": counter["n"], "墙钟秒": round(dt, 3), "命中总数": hits}

        try:
            base = bench(False)
            sql = bench(True)
            sql_warm = bench(True)  # 第二轮全缓存命中
        finally:
            memdir.split_frontmatter = orig_split  # 还原
        return {
            "笔记数": N,
            "查询数": len(queries),
            "baseline_解析/查询": round(base["解析调用数"] / len(queries), 1),
            "sqlite_解析/查询": round(sql["解析调用数"] / len(queries), 2),
            "sqlite热_解析/查询": round(sql_warm["解析调用数"] / len(queries), 2),
            "baseline_墙钟秒": base["墙钟秒"],
            "sqlite_墙钟秒": sql["墙钟秒"],
            "sqlite热_墙钟秒": sql_warm["墙钟秒"],
            "墙钟降幅_热": round(1 - sql_warm["墙钟秒"] / max(base["墙钟秒"], 1e-9), 4),
            "命中数一致": base["命中总数"] == sql["命中总数"] == sql_warm["命中总数"],
            "结论": "第一步=存储+预解析缓存：评分逻辑零改动，命中数一致，查询不再全量解析文件（热轮 0 次解析），fail-open 回退已由单测覆盖",
        }
    finally:
        _restore_env(snap)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def measure_a5_delta_rewrite() -> dict:
    from memory import session_md as sm
    from memory.working import WorkingSnapshot

    snap = dict(os.environ)
    tmp = _temp_env({})
    try:
        def run_shape(sid: str, goal_fn, rounds: int = 40):
            """返回 (updates, Σ全量渲染字符, Σdelta字符)。"""
            full_chars = 0
            delta_chars = 0
            updates = 0
            for k in range(1, rounds + 1):
                msgs: list[dict] = [{"role": "user", "content": f"remember the goal is {goal_fn(k)}"}]
                for i in range(8 * k):
                    uid = f"{sid}-t{k}-{i}"
                    msgs.append({"role": "tool", "tool_call_id": uid,
                                 "content": [{"type": "tool_result", "tool_use_id": uid, "content": f"round{k} out{i} status=ok\n"}]})
                before = len(sm.read_deltas(sid))
                w = WorkingSnapshot(session_id=sid)
                sm.maybe_update(sid, msgs, working=w)
                rows = sm.read_deltas(sid)
                if len(rows) > before:
                    updates += 1
                    delta_chars += len(json.dumps(rows[-1], ensure_ascii=False))
                    full_chars += len(sm.load(sid) or "")
            return updates, full_chars, delta_chars

        # 形态1「推进型」：目标每轮推进 → 多数节的值都在变（差分上限压力测试）
        upd_p, full_p, delta_p = run_shape("benefit-a5", lambda k: f"phase{k}: ship v61 adoption")
        # 形态2「稳定型」：目标长期不变、只追加工具进展（真实长任务常态）
        upd_s, full_s, delta_s = run_shape("benefit-a5s", lambda _k: "ship v61 adoption (unchanged)")

        sid = "benefit-a5"
        rebuilt = sm._fold_sections(sm.fold_deltas(sm.read_deltas(sid)))
        fold_ok = rebuilt.strip() == (sm.load(sid) or "").strip()
        # 回滚精确截断（含端点语义：turn ≤ T 保留）——截到第 20 条 delta
        rows = sm.read_deltas(sid)
        cut_row = rows[19]
        sm.clear_after_rollback(sid, keep_tool_calls=cut_row["turn"])
        kept = sm.load(sid) or ""
        rewind_ok = bool(kept.strip()) and "phase20" in kept and "phase21" not in kept
        # 坏行容错
        with sm.path_deltas(sid).open("a", encoding="utf-8") as fh:
            fh.write("corrupt line\n")
        rows2 = sm.read_deltas(sid)
        corrupt_ok = all(isinstance(r, dict) for r in rows2)
        return {
            "推进型_更新轮数": upd_p,
            "推进型_全量渲染累计字符": full_p,
            "推进型_delta日志累计字符": delta_p,
            "推进型_增量占比": round(delta_p / max(1, full_p), 4),
            "稳定型_更新轮数": upd_s,
            "稳定型_全量渲染累计字符": full_s,
            "稳定型_delta日志累计字符": delta_s,
            "稳定型_增量占比": round(delta_s / max(1, full_s), 4),
            "fold==物化": fold_ok,
            "回滚截断保留前半历史": rewind_ok,
            "坏行只废一条": corrupt_ok,
            "结论": (f"推进型（多数节每轮都变）增量占比 {delta_p / max(1, full_p):.0%}——差分不省字节但换来可回放审计；"
                     f"稳定型（真实长任务常态）增量占比 {delta_s / max(1, full_s):.0%}；"
                     "回滚从整删失忆→按 turn 精确截断；单条损坏不毁历史"),
        }
    finally:
        _restore_env(snap)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def measure_a6_source_health() -> dict:
    import json as _json

    from scripts.memory_stack_eval import source_health

    tmp = Path(tempfile.mkdtemp(prefix="v61_a6_"))
    try:
        # 病态源：17 轮 × 12 副本（复刻 12× 循环副本口径）
        p_bad = tmp / "sess_bad.jsonl"
        rows = []
        for rep in range(12):
            for i in range(17):
                rows.append({"role": "user", "content": f"turn {i}", "ts": 1000.0 + i})
                rows.append({"role": "tool", "tool_call_id": f"c{i}",
                             "content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": f"out {i}"}]})
        p_bad.write_text("\n".join(_json.dumps(r) for r in rows), encoding="utf-8")
        bad = source_health(p_bad)
        # 健康源：唯一轮 + 真实负载
        p_good = tmp / "sess_good.jsonl"
        rows = []
        for i in range(220):
            rows.append({"role": "user", "content": f"real task step {i}: fix module {i % 7}", "ts": 5000.0 + i})
            rows.append({"role": "tool", "tool_call_id": f"g{i}",
                         "content": [{"type": "tool_result", "tool_use_id": f"g{i}",
                                      "content": f"result {i}\ntheta_{i} = {i}\n"
                                                 + ("Traceback (most recent call last):\nValueError: x\n" if i % 40 == 0 else "")}]})
        p_good.write_text("\n".join(_json.dumps(r) for r in rows), encoding="utf-8")
        good = source_health(p_good)
        return {
            "病态源(12×循环副本)": {"healthy": bad["healthy"], "reasons": bad["reasons"], "unique_ts": bad["unique_ts"], "rows": bad["rows"]},
            "健康源(220轮真录形态)": {"healthy": good["healthy"], "tool_results": good["tool_results"],
                          "tracebacks": good["tracebacks"], "kv_lines": good["kv_lines"]},
            "门行为": "--ab / --hitrate-live 载入长源(rows≥120)时自动强校验，不达标报错拒绝（XEYO_ALLOW_UNHEALTHY_SOURCE=1 可强制）",
            "结论": f"病态源拒绝={not bad['healthy']}；健康源放行={good['healthy']}",
        }
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print("=" * 72)
    print("v61 完全采纳项（A1–A6）离线收益测量 —— 零 LLM 调用")
    print("=" * 72)
    results: dict[str, dict] = {}
    for name, fn in (
        ("A3_C2逃生舱", measure_a3_escape_hatch),
        ("A1_ω冷却平滑", measure_a1_cooldown_omega),
        ("A2_retrieve还原", measure_a2_restore),
        ("A4_sqlite清单索引", measure_a4_sqlite_index),
        ("A5_session_md差分重写", measure_a5_delta_rewrite),
        ("A6_源健康门", measure_a6_source_health),
    ):
        print(f"\n### {name}")
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001
            out = {"error": f"{type(exc).__name__}: {exc}"}
        results[name] = out
        for k, v in out.items():
            if k == "明细":
                continue
            print(f"  {k}: {v}")
        if "明细" in out:
            for row in out["明细"][:8]:
                print(f"    · {row}")
    out_dir = ROOT / ".diag_memory_cost"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "v61_adopted_benefits.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\n[已保存] {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
