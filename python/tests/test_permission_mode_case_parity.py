"""`permission_mode` 的两份归一化必须同一口径：大小写变体不许被静默降档。

同一个"审批模式"字符串有两条入口、两套归一化：
- `permissions/runtime_mode.normalize_mode`（活值那一路）：**lower() 后再认**，
  所以 `"ALWAYS"` 是被接受的；认不出返回 None，调用方（`sessions.py:178`）据此报 400。
- `permissions/policy.permission_mode()`（请求 body 那一路）：拿**原文**比
  `mode in _PERMISSION_MODES`，大小写不符就**悄悄落到默认档**。

10-04 实测（真函数，无 mock）：
    set_permission_mode("always")   -> permission_mode() == "always"
    set_permission_mode("ALWAYS")   -> permission_mode() == "risk"      ← 静默降档
    set_permission_mode("alway")    -> permission_mode() == "risk"      ← 静默降档
方向要说清：打错的是"**要最严的 always**"，拿到的是默认的 risk（更松），且没有任何信号
—— 与 §40 那条「只读意图打错 = 拿到写权限」同形。

**10-05 已修**：`permission_mode()` 的 ctx 分支改用 `normalize_mode` 再比对，
两条入口共用一份归一化；`ALWAYS` 等大小写变体不再静默降档。未知值是
"回退默认"还是"报错"仍属政策（未动，保持回退默认）；strict xfail 已摘牌。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from permissions.policy import _PERMISSION_MODES, permission_mode, set_permission_mode  # noqa: E402
from permissions.runtime_mode import normalize_mode  # noqa: E402

VALID = ("always", "risk", "never", "allow")


@pytest.fixture(autouse=True)
def _restore_mode():
    yield
    set_permission_mode(None)


def test_control_valid_lowercase_values_are_honored() -> None:
    """正向自证：合法小写值原样生效（本门不许把这条改坏）。"""
    for mode in VALID:
        set_permission_mode(mode)
        got = permission_mode()
        expected = "never" if mode == "allow" else mode
        assert got == expected, (mode, got)
        assert got in _PERMISSION_MODES, (mode, got)


def test_control_runtime_normalizer_accepts_case_variants() -> None:
    """两端一致性的另一端：`normalize_mode` 认大小写与空白（活值那一路的行为）。"""
    for raw in ("ALWAYS", " Risk ", "NEVER"):
        assert normalize_mode(raw) in {"always", "risk", "never"}, raw


def test_case_variant_is_not_silently_downgraded() -> None:
    set_permission_mode("ALWAYS")
    assert permission_mode() == "always", permission_mode()


def test_begin_turn_baseline_keeps_case_variant_against_midturn_loosening() -> None:
    """轮边界基线的同一路残根：body=``ALWAYS`` 时基线必须记成 always。

    旧写法在 ``begin_permission_turn`` 里拿**原文**比 ``_PERMISSION_MODES``：
    ``"ALWAYS"`` 落不进去 ⇒ 本轮基线错写成默认档 risk。后果（T26 单向性）：
    该轮里 GUI 把活值调松（如 never）时，``set()`` 的「更严才抬升基线」判据
    对着错误的低基线（risk）不抬升，放宽**即时生效**——正确基线（always）
    本应把它压到轮末。方向同 10-04 事故：要最严，拿到更松。
    """
    from permissions.policy import begin_permission_turn
    from permissions.runtime_mode import get_runtime_mode_store

    store = get_runtime_mode_store()
    sid = "s-parity-baseline"
    try:
        set_permission_mode("ALWAYS")
        begin_permission_turn(sid)
        # 轮中 GUI 把活值调松一次（放宽意图）
        store.set(sid, "never")
        # 收紧即时、放宽延后 ⇒ 本轮实效仍应是 always
        assert store.effective(sid) == "always", store.effective(sid)
    finally:
        store.clear(sid)
