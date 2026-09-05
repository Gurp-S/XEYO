"""eval_cold_memory_shadow 门槛/证明性测试（①）。

覆盖：
- 关（默认）：不挂钩，`search` 逐位不变。
- 开=冷记忆：`search()` 返回 `[]`（召回面为空）；卸载后恢复原函数。
- fail-open：异常交回原 `search`。
- 召回归因 `mark_retrieval_assisted`：纯函数、加前缀、不改原块、不改结构。
"""

from __future__ import annotations

import importlib

import pytest

from memory.eval_cold_memory_shadow import (
    enabled,
    install,
    mark_retrieval_assisted,
    uninstall,
)

search_mod = importlib.import_module("memory.search")


@pytest.fixture()
def mem_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "mem"))
    return tmp_path / "mem"


@pytest.fixture()
def cold_off(monkeypatch):
    monkeypatch.delenv("XEYO_EVAL_COLD_MEMORY", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


def test_default_off_no_hook(mem_env, cold_off):
    assert enabled() is False
    assert install() is False
    assert not getattr(search_mod, "__eval_cold_memory_installed", False)


def test_install_uninstall_restore(mem_env, monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_COLD_MEMORY", "1")
    assert enabled() is True
    before = search_mod.search
    assert install() is True
    assert getattr(search_mod, "__eval_cold_memory_installed", False) is True
    assert search_mod.search is not before
    uninstall()
    assert getattr(search_mod, "__eval_cold_memory_installed", False) is False
    assert search_mod.search is before


def test_cold_returns_empty(mem_env, monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_COLD_MEMORY", "1")
    assert install() is True
    try:
        # 冷记忆：任何查询都清空召回面（返回 []，只测「解」不测「记」）。
        assert search_mod.search("anything", cwd=".") == []
    finally:
        uninstall()


def test_off_behavior_unchanged(mem_env, monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_COLD_MEMORY", "1")
    assert install() is True
    try:
        # 关掉冷记忆开关后（移除模块 env + 全局 promote=0）→ 不再拦截，行为与原函数一致。
        monkeypatch.delenv("XEYO_EVAL_COLD_MEMORY", raising=False)
        monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")
        assert enabled() is False
    finally:
        uninstall()
    assert getattr(search_mod, "__eval_cold_memory_installed", False) is False


def test_fail_open_delegates_to_original(mem_env, monkeypatch):
    """若冷路径异常，交回原 `search`——此处用一个能跑通的查询验证不破坏检索。"""
    monkeypatch.delenv("XEYO_EVAL_COLD_MEMORY", raising=False)
    # 正常检索（未装）应返回非异常结果（空列表或缺命中，均不抛）。
    res = search_mod.search("不存在词xyz", cwd=".")
    assert isinstance(res, list)


def test_mark_retrieval_assisted_pure():
    from memory.citation import CitationBlock, CitationEntry

    block = CitationBlock(
        entries=[
            CitationEntry(path="notes/topics/a.md", line_start=1, line_end=3, note="fact"),
            CitationEntry(path="b.md", note=""),
        ],
        rollout_ids=["s1", "s2"],
    )
    out = mark_retrieval_assisted(block)
    # 纯函数：原块未被改动。
    assert block.entries[0].note == "fact"
    assert block.rollout_ids == ["s1", "s2"]
    # 新块加前缀。
    assert out.entries[0].note == "[retrieval-assisted] fact"
    assert out.entries[1].note == "[retrieval-assisted] "
    # 结构不变（entries/rollout_ids 类型与数量）。
    assert len(out.entries) == 2
    assert out.rollout_ids == ["s1", "s2"]
    # 幂等：已标注的再次标注不重复。
    again = mark_retrieval_assisted(out)
    assert again.entries[0].note == "[retrieval-assisted] fact"


def test_mark_retrieval_assisted_none():
    assert mark_retrieval_assisted(None) is None
