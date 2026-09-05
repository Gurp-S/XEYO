"""pollution_gate_shadow 门槛/证明性测试（④）。

覆盖：
- 关（默认）：skip=True（门关闭，不拦）。
- 开=污染门：修复前快照 + 无污染 → ok；任一污染（非修复前快照 / mirror page / hidden test 暴露 /
  check 断言串）→ block 且带 reason。
- fail-open：校验异常（此处模拟 env 缺失键）→ 依 fail_open_block 决定。
"""

from __future__ import annotations

import pytest

from evals.pollution_gate_shadow import (
    check_environment,
    enabled,
)


@pytest.fixture()
def gate_off(monkeypatch):
    monkeypatch.delenv("XEYO_EVAL_POLLUTION_GATE", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


def test_default_off_skip(gate_off):
    assert enabled() is False
    v = check_environment({"snapshot_is_pre_fix": True}, path_text="clean code\n")
    assert v.skip is True and v.ok is True


def test_clean_pass(monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_POLLUTION_GATE", "1")
    assert enabled() is True
    v = check_environment(
        {"snapshot_is_pre_fix": True, "mirror_page_exposed": False, "hidden_test_exposed": False},
        path_text="def solve(): return 42\n",
    )
    assert v.ok is True and v.reasons == []


def test_post_fix_snapshot_blocked(monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_POLLUTION_GATE", "1")
    v = check_environment({"snapshot_is_pre_fix": False}, path_text="")
    assert v.ok is False
    assert any("修复前" in r for r in v.reasons)


def test_mirror_page_blocked(monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_POLLUTION_GATE", "1")
    v = check_environment(
        {"snapshot_is_pre_fix": True},
        path_text="Here is the golden patch: replace line 3 with ...",
    )
    assert v.ok is False
    assert any("镜像页" in r or "golden" in r for r in v.reasons)


def test_hidden_test_exposed_blocked(monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_POLLUTION_GATE", "1")
    v = check_environment(
        {"snapshot_is_pre_fix": True, "hidden_test_exposed": True}, path_text=""
    )
    assert v.ok is False
    assert any("隐藏测试" in r for r in v.reasons)


def test_check_assertion_exposed_blocked(monkeypatch):
    monkeypatch.setenv("XEYO_EVAL_POLLUTION_GATE", "1")
    v = check_environment(
        {"snapshot_is_pre_fix": True},
        path_text="def solve(): ...\ncheck(solve() == 1)\n",
    )
    assert v.ok is False
    assert any("check" in r or "断言" in r for r in v.reasons)


def test_fail_open_block_default(monkeypatch):
    """校验异常/缺失键 → 依 fail_open_block（缺 snapshot_is_pre_fix 即判非修复前）。"""
    monkeypatch.setenv("XEYO_EVAL_POLLUTION_GATE", "1")
    v = check_environment({}, path_text="")
    assert v.ok is False  # 缺 snapshot_is_pre_fix → 判「非修复前」→ block
