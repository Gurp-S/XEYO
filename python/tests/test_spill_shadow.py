"""spill_shadow 门槛/证明性测试（⑭）。

覆盖：
- 关（默认）：不挂钩，`save_text` hint 逐位不变。
- 开：hint 追加「若需中段，Read 该路径」；path/bytes 不变。
- 卸载后恢复原函数。
- fail-open 的**边界**：装饰 hint 失败只放弃建议，绝不重跑 `save_text`
  （那是带写盘副作用的调用，重跑会多落一份无人引用的原文）。
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

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


class _Unformattable:
    """hint 装饰步的确定性炸点：任何格式化/拼接都抛。"""

    def __str__(self):
        raise RuntimeError("hint 不可格式化")

    def __format__(self, spec):
        raise RuntimeError("hint 不可格式化")

    def __add__(self, other):
        raise RuntimeError("hint 不可拼接")

    __radd__ = __add__


def test_decoration_failure_does_not_rewrite_the_file(tmp_spill, monkeypatch):
    """缺陷回归：装饰 hint 失败时原函数只被调用一次，落盘只有一份原文。

    旧实现的 fail-open 是 `except: return 原函数(...)` —— 即**重放写盘**。
    重放会多落一份 spill 文件，而返回的 ref 指向第二份；audit 只记返回路径，
    第一份从此没有任何引用者（留在盘上、再也取不回）。
    """
    monkeypatch.setenv("XEYO_SPILL_TAIL_HINT", "1")
    assert install() is True
    real = getattr(spill_mod, "_ORIG__save_text")
    calls: list[int] = []

    def counting(session_id, text):
        calls.append(len(text))
        ref = real(session_id, text)
        return dataclasses.replace(ref, hint=_Unformattable())

    # 还原必须按"先还被包函数、再卸载挂钩"的顺序：卸载是把 save_text
    # 指回 _ORIG__save_text，若那会儿它还是我的假函数，模块就永久留下假实现。
    monkeypatch.setattr(spill_mod, "_ORIG__save_text", counting)
    try:
        ref = spill_mod.save_text("s3", "z" * 700)
        assert calls == [700], f"save_text 被重放：{calls}"
        assert Path(ref.path).is_file()
        # 只有一份原文在盘上。
        assert len(list(tmp_spill.rglob("*.txt"))) == 1
    finally:
        spill_mod._ORIG__save_text = real
        uninstall()


def test_original_failure_is_not_retried(tmp_spill, monkeypatch):
    """原函数自己失败（磁盘/容器）时也只试一次——调用方按契约兜底。"""
    monkeypatch.setenv("XEYO_SPILL_TAIL_HINT", "1")
    assert install() is True
    real = getattr(spill_mod, "_ORIG__save_text")
    calls = []

    def failing(session_id, text):
        calls.append(1)
        raise OSError("spill disk full")

    monkeypatch.setattr(spill_mod, "_ORIG__save_text", failing)
    try:
        with pytest.raises(OSError):
            spill_mod.save_text("s4", "x" * 10)
        assert calls == [1], f"失败后重放了一次写盘：{calls}"
    finally:
        spill_mod._ORIG__save_text = real
        uninstall()


def test_wrapper_never_replays_the_wrapped_call_on_error() -> None:
    """结构门：`except` 分支里不得出现对被包函数的调用（重放副作用的形状）。"""
    src = Path(spill_mod.__file__).with_name("spill_shadow.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_save_text_with_hint"
    )
    for handler in ast.walk(fn):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        for node in ast.walk(handler):
            if isinstance(node, ast.Call):
                text = ast.unparse(node.func)
                assert "_ORIG_NAME" not in text, (
                    f"except 分支重放被包函数：{text}"
                )
