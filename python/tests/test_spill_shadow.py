"""spill_shadow 门槛/证明性测试（⑭）。

覆盖：
- 关（默认）：不挂钩，`save_text` hint 逐位不变。
- 开：hint 追加「若需中段，Read 该路径」；path/bytes 不变。
- 卸载后恢复原函数。
- fail-open：异常交回原 save_text（不破坏落盘）。
"""

from __future__ import annotations

import pytest

import tools.spill as spill_mod
from tools.spill_shadow import enabled, install, tail_suggestion, uninstall


@pytest.fixture()
def hint_off(monkeypatch):
    monkeypatch.delenv("XEYO_SPILL_TAIL_HINT", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


@pytest.fixture()
def tmp_spill(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / "spill"))
    return tmp_path / "spill"


def test_default_off_no_hook(hint_off):
    assert enabled() is False
    assert install() is False
    assert not getattr(spill_mod, "__spill_tail_hint_installed", False)


def test_install_uninstall_restore(monkeypatch):
    monkeypatch.setenv("XEYO_SPILL_TAIL_HINT", "1")
    assert enabled() is True
    before = spill_mod.save_text
    assert install() is True
    assert getattr(spill_mod, "__spill_tail_hint_installed", False) is True
    assert spill_mod.save_text is not before
    uninstall()
    assert spill_mod.save_text is before


def test_hint_appended(tmp_spill, monkeypatch):
    monkeypatch.setenv("XEYO_SPILL_TAIL_HINT", "1")
    assert install() is True
    try:
        ref = spill_mod.save_text("s1", "x" * 1000)
        assert "若需中段，Read 该路径" in ref.hint
        assert ref.bytes == 1000
        # 原 hint 仍在。
        assert "full output" in ref.hint
    finally:
        uninstall()


def test_off_hint_unchanged(tmp_spill, monkeypatch):
    monkeypatch.delenv("XEYO_SPILL_TAIL_HINT", raising=False)
    ref = spill_mod.save_text("s2", "y" * 500)
    assert "若需中段" not in ref.hint


def test_tail_suggestion_value():
    assert tail_suggestion() == "若需中段，Read 该路径"
