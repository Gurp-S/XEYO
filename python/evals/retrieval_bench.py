"""retrieval_bench — ⑰ 离线检索基准（纯词法，不引 embedding）。

离线、检索有已知答案；对比「含/不含语义搜索」，当前 XEYO 纯词法
先打**词法召回 hit@k** 基线——这是评估链地基，也用来判断「值不值得上 embedding」。

## 范围
- **笔记检索**：一组 `(query, 期望命中 note)`，用 `memory.search`（词法）跑，测 `hit@k`。
- **代码检索**：一组 `(query, 期望命中文件)`，用 `content_index.lookup`（trigram 候选超集）跑，
  测「期望文件是否在候选集」的召回基线（词法）。此为超集基线，仍需 rg 精确验证（对齐现状）。

## 纪律
- 离线、无 API/模型/网络；数据集内置，结果可重复。
- 纯词法检索，不引 embedding/向量库（⑯ 未启动前保持真实基线）。
- **fail-open**：任何索引异常 → 回退全量 `rg`/文件扫描（与 content_index/memindex 语义一致）。

## 用法
- 作为模块：`from evals.retrieval_bench import run_bench; run_bench(...) -> dict`
- 作为脚本：`py -3.11 evals/retrieval_bench.py`（打印 hit@k 汇总）。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: 仓库根（`python/evals/` 的上级 = 仓库根）。
REPO_ROOT = Path(__file__).resolve().parents[2]
#: ⑰ 基线落盘目录（与 evals/client.py 的 artifacts/benchmarks 同族）。
BASELINE_DIR = REPO_ROOT / "artifacts" / "benchmarks" / "retrieval"
BASELINE_PATH = BASELINE_DIR / "hitk.json"


@dataclass
class BenchCase:
    """一条检索用例：query + 期望命中（note id 或文件相对路径）。"""

    query: str
    expected: str  # 期望命中的 note id / 文件 relpath
    top_k: int = 5


# --------------------------------------------------------------------------- #
# 内置数据集
# --------------------------------------------------------------------------- #

#: 笔记检索用例。query 用真实语义自然语言，期望命中一条 note 的 id。
NOTE_CASES: list[BenchCase] = [
    BenchCase("工作区激活的是哪套记忆开关？", "note_memory_switches"),
    BenchCase("压缩后如何还原结构化原子？", "note_fragments_restore"),
    BenchCase("L5 的 project 默认链是什么？", "note_l5_project"),
    BenchCase("跨会话共享记忆查哪些笔记？", "note_session_peers"),
    BenchCase("引用锚点块长什么样？", "note_citation_block"),
]

#: 代码检索用例。query 用英文字面量，期望命中一个文件（相对受控 corpus root）。
#: 对每个用例，会在受控 corpus 里写一个对应文件（模拟真实代码片段），确保索引可建、召回可测。
CODE_CASES: list[BenchCase] = [
    BenchCase("build_index trigrams content_index", "content_index.py"),
    BenchCase("sync_table sqlite signature memindex", "memindex.py"),
    BenchCase("MEMORY_SWITCHES registry default", "memory_switches.py"),
    BenchCase("rerank_preference bonus score", "rerank_shadow.py"),
    BenchCase("transcript_pointer inject history", "transcript_pointer.py"),
]

#: 受控 corpus：为每个 CODE_CASE 生成一个文件，内容含 query 的词法 token（模拟真实候选）。
_CODE_SOURCES: dict[str, str] = {
    "content_index.py": "def _build_index(root): trigrams = {}  # content index build\n",
    "memindex.py": "def _sync_table(domain): sqlite signature  # memindex sync\n",
    "memory_switches.py": "MEMORY_SWITCHES = ()  # registry default switched\n",
    "rerank_shadow.py": "def rerank_preference(note): return bonus  # rerank_preference score\n",
    "transcript_pointer.py": "def transcript_pointer(session): inject history  # transcript_pointer\n",
}


@dataclass
class BenchResult:
    """一次检索评测：命中的 top_k、与期望命中是否匹配（hit@k）。"""

    case: BenchCase
    hits: list[str] = field(default_factory=list)
    hit: bool = False
    detail: str = ""


# --------------------------------------------------------------------------- #
# 笔记检索：memory.search 词法命中
# --------------------------------------------------------------------------- #

def _note_id(note) -> str:
    return str(getattr(note, "id", "") or "")


def bench_notes(cases: list[BenchCase], *, wsid: str | None = None) -> list[BenchResult]:
    """对内置笔记用例跑 `memory.search`（词法），评估 hit@k。

    - 用**固定 wsid**（默认 `_dedicated_wsid()`）隔离，避免与其它测试/工作区互扰。
    - 显式传 `wsid` 给 `search`，且 `scope="all"`——只读该 wsid 域，不 merge user 域（防脏数据污染）。
    """
    import importlib

    search_mod = importlib.import_module("memory.search")  # memory.search 是 facade 遮蔽，须 importlib

    wsid = wsid or _dedicated_wsid()
    _seed_notes(wsid)

    results: list[BenchResult] = []
    for case in cases:
        kwargs = {"top_k": case.top_k, "cwd": ".", "touch": False, "wsid": wsid, "scope": "all"}
        try:
            hits = search_mod.search(case.query, **kwargs)
            ids = [_note_id(n) for n in hits]
        except Exception as e:  # noqa: BLE001 — fail-open：检索异常记 detail
            results.append(BenchResult(case=case, detail=f"search error: {e}"))
            continue
        hit = case.expected in ids[: case.top_k]
        results.append(
            BenchResult(case=case, hits=ids[: case.top_k], hit=hit, detail="notes")
        )
    return results


def _dedicated_wsid() -> str:
    """固定、隔离的笔记基准域 id（与真实工作区 wsid 无关，防互扰）。"""
    return "retrieval_bench_ws"


def _seed_notes(wsid: str) -> None:
    """用 repo 正规写路径（write_note）写入被检索的 note 组（id 固定、内容含 query 关键词）。"""
    from memory.governance import parse_and_validate
    from memory.memdir import write_note

    # 数据三元组 (file_id, title, body)
    seed = [
        ("note_memory_switches", "记忆开关注册表", "工作区激活记忆开关 MEMORY_SWITCHES 设置 环境变量 默认"),
        ("note_fragments_restore", "压缩碎片还原", "压缩碎片还原 retrieve 按 notes:msg 锚点 找回结构化原子"),
        ("note_l5_project", "L5 project 默认链", "L5 模式 project 默认链 不跑每轮 decide v61 实验通道"),
        ("note_session_peers", "跨会话共享记忆", "跨会话共享记忆 session.md 检索 同工作区其他会话"),
        ("note_citation_block", "引用锚点块", "引用锚点 citation_entries rollout_ids 块格式 定位"),
    ]
    for sid, title, body in seed:
        fm = {
            "id": sid,
            "type": "fact",
            "title": title,
            "scope": "workspace",
            "status": "active",
            "confidence": 0.8,
            "source": {"kind": "user"},
        }
        note = parse_and_validate(fm, body)
        write_note(note, wsid=wsid)


# --------------------------------------------------------------------------- #
# 代码检索：content_index.lookup（trigram 候选超集）基线段
# --------------------------------------------------------------------------- #

def bench_code(cases: list[BenchCase], *, code_root: str) -> list[BenchResult]:
    """对受控 corpus 跑 `content_index.lookup`（trigram 候选超集），评估「期望文件是否在候选」召回基线。

    在 `code_root` 下写入 `_CODE_SOURCES` 对应的文件（保证索引可建、不触发 repo 大小上限回退），
    再对每个 query 用 `content_index.lookup` 求候选集。这是**超集召回**基线：真正匹配还需 rg 精确验证。
    """

    from tools.fileio import content_index

    # 写受控 corpus 文件。
    root = Path(code_root)
    root.mkdir(parents=True, exist_ok=True)
    for name, src in _CODE_SOURCES.items():
        (root / name).write_text(src, encoding="utf-8")

    results: list[BenchResult] = []
    for case in cases:
        expected = case.expected.replace("\\", "/")
        try:
            term = _stable_query_term(case.query)
            if not content_index.is_literal(term):
                # 非字面量 query：无法走索引（fail-open 回退全量 rg 语义），记为 miss 但注明。
                results.append(
                    BenchResult(case=case, hits=[], hit=False, detail=f"non-literal query: {term}")
                )
                continue
            cands = content_index.lookup(str(root), term)
            cands = [c.replace("\\", "/").lstrip("./") for c in (cands or [])]
        except Exception as e:  # noqa: BLE001 — fail-open
            results.append(BenchResult(case=case, detail=f"lookup error: {e}"))
            continue
        hit = expected in cands[: case.top_k]
        results.append(
            BenchResult(case=case, hits=cands[: case.top_k], hit=hit, detail="code(corpus)")
        )
    return results


def _stable_query_term(query: str) -> str:
    """把自然语言 query 归一成一个可被索引命中的字面量 token。

    取 query 里最长的字母数字串（尽量贴近真实词法命中）。若 query 含中文则取首个英文 token。
    """
    import re

    toks = re.findall(r"[A-Za-z0-9_]{4,}", query)
    if toks:
        # 优先取「文件相关」词：过滤掉 too-generic。
        cands = [t for t in toks if t.lower() not in ("index", "query", "retrieval", "search", "for", "the", "and")]
        return (cands or toks)[0]
    return query


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #

def summarize(results: list[BenchResult], *, name: str) -> dict:
    total = len(results)
    hit = sum(1 for r in results if r.hit)
    # hit@k 平均 = 命中用例占比（每 case 一个，top_k 内命中即算 1）。
    return {
        "domain": name,
        "cases": total,
        "hit@k": round(hit / total, 4) if total else 0.0,
        "hit": hit,
        "miss": total - hit,
        "miss_cases": [r.case.query for r in results if not r.hit],
    }


def _workspace_id() -> str:
    import os

    from memory.memdir import workspace_id

    return workspace_id(os.path.abspath("."))


def run_bench(*, code_root: str | None = None) -> dict:
    """跑完整基准（笔记 + 代码），返回 summary dict。

    笔记测量必须是**真实词法基线**：升格后 memory.search 可能被冷记忆/重排侧挂模块包装，
    也可能被其它测试留下的环境变量影响。故在笔记测量前强制「关掉这些侧挂包装 + 清冷/重排 env」，
    测完恢复——保证 hit@k 是纯词法、可重复、防回退的基线。
    """
    import shutil

    # ---- 笔记测量前：临时关掉会影响词法打分的侧挂包装与 env ----
    saved_env, installed = _suspend_search_side_effects()
    try:
        _tmp = tempfile.mkdtemp(prefix="retrieval_bench_")
        prev = os.environ.get("XEYO_MEMORY_DIR")
        os.environ["XEYO_MEMORY_DIR"] = str(Path(_tmp) / "mem")
        try:
            notes_results = bench_notes(NOTE_CASES)
        finally:
            if prev is None:
                os.environ.pop("XEYO_MEMORY_DIR", None)
            else:
                os.environ["XEYO_MEMORY_DIR"] = prev
            shutil.rmtree(_tmp, ignore_errors=True)
    finally:
        _restore_search_side_effects(saved_env, installed)

    # 受控 code corpus（写进临时目录，避免污染调用方 cwd、也避免 repo 大小触发索引回退）。
    _code_tmp = tempfile.mkdtemp(prefix="retrieval_bench_code_")
    try:
        code_results = bench_code(CODE_CASES, code_root=code_root or _code_tmp)
    finally:
        shutil.rmtree(_code_tmp, ignore_errors=True)

    return {
        "notes": summarize(notes_results, name="notes"),
        "code": summarize(code_results, name="code"),
    }


def _suspend_search_side_effects() -> tuple[dict[str, str], list[str]]:
    """临时卸载 cold-memory / rerank 侧挂包装并清相关 env；返回 (saved_env, installed_modules)."""
    import importlib

    saved: dict[str, str] = {}
    installed: list[str] = []
    envs = ("XEYO_EVAL_COLD_MEMORY", "XEYO_MEMORY_RERANK_PREFERENCE")
    for e in envs:
        saved[e] = os.environ.get(e, "")
        os.environ.pop(e, None)
    for mod_name in ("memory.eval_cold_memory_shadow", "memory.rerank_preference_shadow"):
        try:
            mod = importlib.import_module(mod_name)
            getattr(mod, "uninstall", lambda: None)()
            installed.append(mod_name)
        except Exception:  # noqa: BLE001
            pass
    return saved, installed


def _restore_search_side_effects(saved: dict[str, str], installed: list[str]) -> None:
    """恢复卸载前的 env（侧挂包装不主动重装——基准不改变主态，只测真实基线）。"""
    for e, v in saved.items():
        if v:
            os.environ[e] = v
        else:
            os.environ.pop(e, None)


def write_baseline(result: dict | None = None, *, path: Path | None = None) -> Path:
    """把 hit@k 基线落盘（JSON），供跨运行对比 / 回归门禁用。

    - 默认写到 `artifacts/benchmarks/retrieval/hitk.json`。
    - 幂等、可重复；失败不抛（基准是评估信息，不阻塞）。
    """
    target = path or BASELINE_PATH
    out = result or run_bench()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass
    return target


def main() -> int:
    import json as _json

    r = run_bench()
    path = write_baseline(r)
    print(_json.dumps(r, ensure_ascii=False, indent=2))
    print(f"[retrieval_bench] baseline -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
