"""rerank_preference_shadow 证明性测试（⑮，**已固化开启**）。

覆盖：
- 恒开：`enabled()` 恒 True，不再有开关面（原 XEYO_MEMORY_RERANK_PREFERENCE 键已删，
  settings/env 均不可关；唯一残留旁路是 XEYO_SIDEMOD_PROMOTE=0 全局回退跳过 install）。
- 开=偏好信号：被采用（last_used_at 新）的 note 排序提前；未采用者靠后。
- **P0 召回集不变**：命中列表长度与来源与「原召回」一致（只重排，不扩充/不收缩）。
- 卸载后恢复原函数（可随时卸载，fail-open）。
"""

from __future__ import annotations

import importlib
import time

import pytest

# 用 importlib 取模块（memory.search 是 facade 遮蔽）。
search_mod = importlib.import_module("memory.search")
from memory.rerank_preference_shadow import (  # noqa: E402
    _preference_bonus,
    _rerank,
    enabled,
    install,
    uninstall,
)

_ORIG_NAME = "_ORIG__search"


class _FakeNote:
    def __init__(self, note_id, content, adopted):
        self.id = note_id
        self.content = content
        self.type = "fact"
        self.title = f"t{note_id}"
        self.status = "active"
        self.scope = "workspace"
        self.confidence = 0.8
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 60))
        self.last_used_at = ts if adopted else "2020-01-01 00:00:00"
        self.last_confirmed_at = None


def test_fixed_on():
    """固化契约：enabled() 恒 True；env / settings 均不可关。"""
    assert enabled() is True


def test_env_cannot_disable(monkeypatch):
    """环境变量残留不参与（开关已删）。"""
    monkeypatch.setenv("XEYO_MEMORY_RERANK_PREFERENCE", "0")
    assert enabled() is True


def test_install_uninstall_restore():
    before = search_mod.search
    assert install() is True
    assert getattr(search_mod, "__rerank_preference_installed", False) is True
    assert search_mod.search is not before
    uninstall()
    assert getattr(search_mod, "__rerank_preference_installed", False) is False
    assert search_mod.search is before


def test_preference_bonus_levels():
    n_recent = _FakeNote("a", "x", True)
    assert _preference_bonus(n_recent) == 3.0  # 近 24h
    n_old = _FakeNote("b", "x", False)
    assert _preference_bonus(n_old) == 0.0  # 更早


def test_rerank_reorders_not_expands():
    """P0 召回集不变：结果 = 原召回的重排，不扩充/不收缩。"""
    # 先保存真正的 search（避免 uninstall 回填 `_ORIG__search` 时把 search 变成 lambda）。
    real_search = search_mod.search
    orig_backup = getattr(search_mod, _ORIG_NAME, None)
    try:
        # 原 search 返回两个命中：adopted 近期被采用（偏好分高）。
        adopted = _FakeNote("adopted", "alpha beta gamma", True)
        not_adopted = _FakeNote("notadopted", "alpha beta gamma delta", False)
        orig_hits = [not_adopted, adopted]
        search_mod._ORIG__search = lambda query, **kw: list(orig_hits)
        assert install() is True

        # touch=False：touch 路径会向 memdir 落盘（FakeNote 无处落），这里只验证重排。
        res = _rerank("alpha", cwd=".", touch=False)
        ids = [n.id for n in res]
        # 召回集不变：两个命中仍在（不扩充不收缩）。
        assert len(res) == 2
        assert set(ids) == {"adopted", "notadopted"}
        # 偏好信号让「被采用者」提前。
        assert ids.index("adopted") < ids.index("notadopted")
    finally:
        if orig_backup is not None:
            search_mod._ORIG__search = orig_backup
        else:
            try:
                delattr(search_mod, _ORIG_NAME)
            except AttributeError:
                pass
        uninstall()
        search_mod.search = real_search


def test_switch_deregistered():
    """XEYO_MEMORY_RERANK_PREFERENCE 已移出注册表（固化=不再是开关）。"""
    from memory import memory_switches

    cur = memory_switches.current()
    assert "XEYO_MEMORY_RERANK_PREFERENCE" not in cur
    # 保存已删键 → 显式报错（防 GUI/脚本误写回）
    with pytest.raises(ValueError):
        memory_switches.save({"XEYO_MEMORY_RERANK_PREFERENCE": "1"})
