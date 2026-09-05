"""sidecar.upgrade 聚合器测试：apply/unapply 与总开关门控。

覆盖：
- 升格关闭（XEYO_SIDEMOD_PROMOTE=0）：apply() 返回 False，主模块函数未被替换。
- 升格开启（默认）：apply() 返回 True，挂钩型主模块函数被替换；unapply() 恢复。
- ⑫ mcp_name_manifest 不在提升清单内（保持旁路）。
"""

from __future__ import annotations

import importlib

import pytest

from sidecar import upgrade
from sidecar.policy import sidemod_promote


def test_sidemod_promote_default_on(monkeypatch):
    monkeypatch.delenv("XEYO_SIDEMOD_PROMOTE", raising=False)
    assert sidemod_promote() is True


def test_apply_off_noop(monkeypatch):
    """回退时 apply() 不安装任何挂钩。"""
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")
    assert upgrade.apply() is False
    # 抽查一个挂钩型主模块未被替换。
    from memory import memindex

    assert not getattr(memindex, "__memindex_sig_installed", False)


def test_apply_then_unapply(monkeypatch):
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "1")
    from memory import memindex
    before = memindex._sync_table
    assert upgrade.apply() is True
    assert memindex._sync_table is not before
    assert getattr(memindex, "__memindex_sig_installed", False) is True
    # 其他挂钩型也应被安装（抽查 content_index / spill / pre_llm_inject）。
    from tools.fileio import content_index
    assert getattr(content_index, "__content_index_cache_installed", False) is True
    from tools import spill
    assert getattr(spill, "__spill_tail_hint_installed", False) is True
    from prompt import pre_llm_inject
    assert getattr(pre_llm_inject, "__c2_transcript_pointer_installed", False) is True

    upgrade.unapply()
    assert memindex._sync_table is before
    assert not getattr(memindex, "__memindex_sig_installed", False)
    assert not getattr(content_index, "__content_index_cache_installed", False)


def test_hooked_list_excludes_mcp_manifest(monkeypatch):
    """⑫ 不在升格清单（需实测收益才接入冻结快照）。"""
    assert "extension.mcp_name_manifest_shadow" not in upgrade.hooked_modules()


def test_apply_partial_failure_continues(monkeypatch):
    """单模块失败不挡其余：注入一个坏模块名后 apply() 仍安装成功项。"""
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "1")
    _orig = upgrade._HOOKED
    upgrade._HOOKED = ["memory.memindex_sig_shadow", "no.such.module"]  # noqa: SLF001
    try:
        from memory import memindex

        before = memindex._sync_table
        try:
            assert upgrade.apply() is True  # 坏模块跳过，好的照装
        finally:
            upgrade.unapply()
        assert memindex._sync_table is before
    finally:
        upgrade._HOOKED = _orig  # noqa: SLF001
