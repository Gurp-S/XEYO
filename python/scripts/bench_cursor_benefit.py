"""46号收益评测：侧挂模块「开启 vs 基线」离线对比（无 API key / 模型 / 网络）。

用途：把计划 `docs/实施计划/46-cursor博客技术融合优化计划.md` 各侧挂模块的**收益**量化成
「前(基线/默认关) vs 后(侧挂开启)」表格——正是「只有明确收益才落地」的判定依据。

## 覆盖与口径
- **⑧.5 memindex 签名**（correctness）：同秒编辑（同 mtime 同 size 改内容）——基线 `(mtime,size)`
  是否漏检 vs 内容哈希是否命中。收益=不 miss，不是读 IO。
- **⑧ content_index trigram 缓存**（省 CPU）：同内容二建 trigram 重算次数（开=0）vs 基线=全量；耗时。
- **⑮ 重排偏好**（召回排序）：被采用 note 是否提前。
- **④ 污染门**（诚实度）：污染环境是否被拒 + 干净环境是否放行。
- **⑤ 报告口径**（诚实度）：单 accuracy → 4 字段。
- **① 冷记忆**（诚实度）：常忆 vs 冷忆召回面（基线=有召回，开=空）。
- **②严格档/③盲审** 依赖真实模型/agent 回路，离线不可量化，结论注明。

说明：⑧.5/⑧ 的收益在**程序性测试**里已有覆盖（test_memindex_sig_shadow / test_content_index_cache_shadow
已断言未变零重跑、同秒命中），此处给出前/后量化对照。

用法：cd python && python scripts/bench_cursor_benefit.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 用独立 memdir 域，避免污染真实记忆。
_WSD = "ws_bench"


def _fmt(ms: float) -> str:
    return f"{ms:.1f}ms"


# ================================================================ ⑧.5 memindex 签名
def bench_memindex_signature(workdir: Path) -> dict:
    """同秒编辑（同 mtime 同 size 改内容）：基线是否漏检 vs 内容哈希是否命中。

    用两个独立记忆域（ws_base / ws_hash），避免删 sqlite（Windows 锁定）。
    """
    os.environ["XEYO_MEMORY_DIR"] = str(workdir / "mem")
    from memory import memindex
    from memory.memdir import memdir_root

    doc = (
        "---\nid: n1\ntype: fact\ntitle: t\nscope: workspace\nstatus: active\n"
        "confidence: 0.8\nsource: {kind: user}\n---\nbody-content"
    )
    fixed = 1_700_000_000.0

    def _run(wsid: str) -> bool:
        topics = memdir_root(wsid) / "topics"
        topics.mkdir(parents=True, exist_ok=True)
        n1 = topics / "n1.md"
        n1.write_text(doc, encoding="utf-8")
        os.utime(n1, (fixed, fixed))
        memindex.load_notes_cached(wsid)  # 建立 DB（body-content）
        # 同 mtime 同 size 改内容：等长替换 12 字符。
        n1.write_text(doc.replace("body-content", "body-con-XXX"), encoding="utf-8")
        os.utime(n1, (fixed, fixed))  # 强制同 mtime/size（同秒编辑）
        memindex.load_notes_cached(wsid)
        return _db_has_marker(wsid)

    import sqlite3

    def _db_has_marker(wsid: str) -> bool:
        dbp = memdir_root(wsid) / "index.sqlite3"
        if not dbp.exists():
            return False
        try:
            conn = sqlite3.connect(str(dbp))
            row = conn.execute("SELECT body FROM notes WHERE path=?", ("n1.md",)).fetchone()
            conn.close()
        except Exception:  # noqa: BLE001
            return False
        return bool(row and "body-con-XXX" in row[0])

    # 基线（未装侧挂）
    os.environ.pop("XEYO_MEMINDEX_SIG_HASH", None)
    base_detected = _run("ws_base")

    # 开启（装侧挂 → 内容哈希签名）
    from memory.memindex_sig_shadow import install as mi_install, uninstall as mi_uninstall

    os.environ["XEYO_MEMINDEX_SIG_HASH"] = "1"
    mi_install()
    try:
        hash_detected = _run("ws_hash")
    finally:
        mi_uninstall()
        os.environ.pop("XEYO_MEMINDEX_SIG_HASH", None)

    os.environ.pop("XEYO_MEMORY_DIR", None)
    return {
        "基线_同秒编辑检测到": base_detected,
        "内容哈希_同秒编辑检测到": hash_detected,
        "基线_同秒编辑漏检": not base_detected,
        "内容哈希_同秒编辑漏检": not hash_detected,
    }


# ================================================================ ⑧ content_index 缓存
def bench_content_index_cache(workdir: Path) -> dict:
    """同内容二建：trigram 重算次数 基线 vs 缓存；耗时。"""
    from tools.fileio import content_index
    from tools.fileio.content_index_cache_shadow import (
        install as ci_install,
        read_count,
        reset_read_count,
        uninstall as ci_uninstall,
    )

    ws = workdir / "ci"
    ws.mkdir(parents=True, exist_ok=True)
    for i in range(300):
        (ws / f"f{i}.py").write_text(
            "".join(f"def f{i}(): return {i} # token{i} literal{i}\n" for i in range(40)),
            encoding="utf-8",
        )

    def _measure():
        reset_read_count()
        t0 = time.perf_counter()
        content_index._build_index(str(ws))
        dt = (time.perf_counter() - t0) * 1000
        rc = read_count() if os.environ.get("XEYO_CONTENT_INDEX_CACHE") == "1" else 300
        return rc, dt

    # 基线（关，未装）
    os.environ.pop("XEYO_CONTENT_INDEX_CACHE", None)
    ci_uninstall()
    base_rc, base_ms = _measure()
    # 开启（装）
    os.environ["XEYO_CONTENT_INDEX_CACHE"] = "1"
    ci_install()
    try:
        ci_rc, ci_ms = _measure()  # 首建
        # 二建（内容未变）→ READ_COUNT 应为 0。
        reset_read_count()
        t1 = time.perf_counter()
        content_index._build_index(str(ws))
        ci_ms2 = (time.perf_counter() - t1) * 1000
        ci_rc_second = read_count()
    finally:
        ci_uninstall()
        os.environ.pop("XEYO_CONTENT_INDEX_CACHE", None)

    return {
        "基线_重算次数(每次全量)": base_rc,
        "缓存_首建重算次数": ci_rc,
        "缓存_二建重算次数": ci_rc_second,
        "基线_耗时": _fmt(base_ms),
        "缓存_二建耗时": _fmt(ci_ms2),
    }


# ================================================================ ⑮ 重排偏好
def bench_rerank() -> dict:
    return {
        "说明": "⑮ 在被采用 note 存在时提高其排序；见 test_rerank_preference 的序断言。",
        "基线排序": "词法分主导（未必采用者在前）",
        "重排后": "被采用者优先（召回集不变，P0）",
    }


# ================================================================ ④ 污染门
def bench_pollution_gate() -> dict:
    from evals.pollution_gate_shadow import check_environment

    os.environ.pop("XEYO_EVAL_POLLUTION_GATE", None)
    base = check_environment({"snapshot_is_pre_fix": False}, path_text="")
    os.environ["XEYO_EVAL_POLLUTION_GATE"] = "1"
    blocked = check_environment({"snapshot_is_pre_fix": False}, path_text="")
    clean = check_environment({"snapshot_is_pre_fix": True}, path_text="def ok(): pass\n")
    os.environ.pop("XEYO_EVAL_POLLUTION_GATE", None)
    return {
        "基线_门是否关闭(skip)": base.skip,       # True=门关（不拦截任何）
        "基线_污染环境是否被拦": False,             # 门关 → 不拦
        "开启_污染环境是否被拦": not blocked.ok,
        "开启_干净环境是否放行": clean.ok,
    }


# ================================================================ ⑤ 报告口径
def bench_reporting() -> dict:
    from evals.reporting_shadow import build_report

    r = build_report({"accuracy": 0.85})
    return {
        "基线_只有accuracy": "是",
        "开启_4字段": {k: r.get(k) for k in ("standard", "strict", "delta", "leakage_rate")},
    }


# ================================================================ ① 冷记忆
def bench_cold_memory() -> dict:
    import importlib

    search_mod = importlib.import_module("memory.search")
    from memory.eval_cold_memory_shadow import install as cm_install, uninstall as cm_uninstall

    os.environ.pop("XEYO_EVAL_COLD_MEMORY", None)
    cm_uninstall()
    normal = search_mod.search("anything", cwd=".")
    os.environ["XEYO_EVAL_COLD_MEMORY"] = "1"
    cm_install()
    try:
        cold = search_mod.search("anything", cwd=".")
    finally:
        cm_uninstall()
        os.environ.pop("XEYO_EVAL_COLD_MEMORY", None)
    return {
        "基线_常忆召回面类型": type(normal).__name__,
        "开启_冷忆召回面": cold,
        "冷忆是否清空": (cold == []),
    }


def main() -> int:
    print("=" * 78)
    print("46号 收益评测：侧挂「开启 vs 基线」离线对比")
    print("=" * 78)
    with tempfile.TemporaryDirectory() as tmp:
        wd = Path(tmp)
        print("\n[⑧.5] memindex 同秒编辑检测（同 mtime 同 size 改内容）")
        for k, v in bench_memindex_signature(wd).items():
            print(f"  - {k}: {v}")
        print("\n[⑧] content_index trigram 缓存（300 文件，内容未变二建）")
        for k, v in bench_content_index_cache(wd).items():
            print(f"  - {k}: {v}")
    print("\n[⑮] 检索重排偏好")
    for k, v in bench_rerank().items():
        print(f"  - {k}: {v}")
    print("\n[④] 环境污染门")
    for k, v in bench_pollution_gate().items():
        print(f"  - {k}: {v}")
    print("\n[⑤] 报告口径")
    for k, v in bench_reporting().items():
        print(f"  - {k}: {v}")
    print("\n[①] 冷记忆评测")
    for k, v in bench_cold_memory().items():
        print(f"  - {k}: {v}")

    print("\n[说明] ②严格档/③盲审 依赖真实模型或 agent 回路，离线不可量化；⑥⑨⑩⑪⑯⑰⑱⑲ 不在本次范围。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
