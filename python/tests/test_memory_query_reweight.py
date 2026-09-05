"""F4 检索侧重排（**已固化开启**，原 XEYO_MEMORY_QUERY_REWEIGHT 键已删）。

机制：词法分把「重复命中单一词」无限加分（depth），重排把每词命中封顶到
_QUERY_TERM_CAP，广度主导深度（query-aware）；**召回集绝不改动**（P0）。

探针 A/B（都命中同一查询）：
- A：单一词「pnpm」重复 30 次、仅覆盖 1 个不同查询词（词频高、相关面窄）；
- B：覆盖全部查询词（语义完整）。
固化后排序恒为广度主导 → B 领先。
"""

from __future__ import annotations

import asyncio

from engine.abort import AbortController
from memory.search import (
    _normalize_query,
    _query_terms,
    query_reweight_enabled,
    query_reweight_score,
    search,
)
from tools.memory_tool import MemoryTool

QUERY = "pnpm 安装 单元测试"
# A：重复单一词 30 次（raw lexical 极大，但只覆盖 1 个不同查询词）
A_TXT = " ".join(["pnpm"] * 30)
# B：覆盖全部查询词（每个词只出现一次 → 封顶后广度仍占优）
B_TXT = "用 pnpm 安装依赖并运行单元测试，单元测试通过后合并"


def test_reweight_fixed_on():
    """固化契约：F4 恒开（settings/env 均不可关）。"""
    assert query_reweight_enabled() is True


def test_query_reweight_breadth_dominates(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
    root = tmp_path / "proj"
    root.mkdir()
    write = MemoryTool(cwd=str(root))
    for title, content in (("包管理A", A_TXT), ("包管理B", B_TXT)):
        out = asyncio.run(
            write.execute(
                {
                    "action": "write",
                    "type": "reference",
                    "content": content,
                    "title": title,
                    "source_kind": "user",
                },
                AbortController(),
            )
        )
        assert not out.is_error

    # —— 重排信号有效性：B 的 breadth（封顶后）明显高于 A ——
    terms, _rq, _mo = _query_terms(_normalize_query(QUERY))
    assert query_reweight_score(_normalize_query(B_TXT), terms) > query_reweight_score(
        _normalize_query(A_TXT), terms
    )

    # —— 召回集：两条都命中 ——
    hits = search(QUERY, cwd=str(root), scope="workspace", top_k=5, touch=False)
    assert len(hits) == 2

    # —— 排序：广度主导，B 领先（raw lexical 下 A 靠词频反超，正是固化要修的）——
    assert [n.title for n in hits][0] == "包管理B"


def test_search_no_hit_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
    root = tmp_path / "proj"
    root.mkdir()
    write = MemoryTool(cwd=str(root))
    out = asyncio.run(
        write.execute(
            {
                "action": "write",
                "type": "feedback",
                "content": "测试必须打真库",
                "title": "真实 DB",
                "source_kind": "user",
            },
            AbortController(),
        )
    )
    assert not out.is_error
    hits = search("真库", cwd=str(root), scope="workspace", top_k=3, touch=False)
    assert hits and hits[0].title == "真实 DB"
    assert search("不存在的词xyzzy", cwd=str(root), scope="workspace") == []
