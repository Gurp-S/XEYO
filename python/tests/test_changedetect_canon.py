"""canon 规范化 + L0 快照层的端到端测试。

涵盖：
  - 易变量抹平（路径 / UUID / 时间戳 / 临时目录）
  - 确定性（同样输入两次产出同样的字节）
  - 1 字符灵敏度（改个字符就 hash 变）
  - L0 golden 对自己通过 check（防止熵漂移）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.changedetect import canon, surface


def test_canon_strips_uuid():
    s = "user session 12345678-1234-1234-1234-123456789012 done"
    out = canon.scrub(s)
    assert "<UUID>" in out
    assert "123456789012" not in out


def test_canon_strips_xeyo_env_id():
    s = "before xeyo_env_abc123def456 after"
    assert "xeyo_env_<ID>" in canon.scrub(s)


def test_canon_register_literal_overrides_path_rule():
    canon.reset_extras()
    canon.register_literal("C:\\secret\\raw\\path", "<TMP>")
    out = canon.scrub("see C:\\secret\\raw\\path and also C:\\secret\\raw\\path\\pkg")
    assert "<TMP>" in out
    assert "secret" not in out
    canon.reset_extras()


def test_canon_obj_scrubs_inside_nested_before_dump():
    canon.reset_extras()
    canon.register_literal("C:\\temp\\xeyo_abc", "<TMP>")
    obj = {"a": [{"path": "C:\\temp\\xeyo_abc\\pkg"}], "b": "C:\\temp\\xeyo_abc"}
    out = canon.canon_obj(obj)
    assert "<TMP>" in out
    assert "C:\\\\temp" not in out
    canon.reset_extras()


def test_canon_text_strips_trailing_ws():
    s = "line1   \nline2\t\nline3"
    out = canon.canon_text(s)
    assert out == "line1\nline2\nline3\n"


def test_first_diff_line_number():
    a = "a\nb\nc\n"
    b = "a\nB\nc\n"
    assert canon.first_diff_line(a, b) == 2
    assert canon.first_diff_line(a, a) is None


def test_char_delta():
    added, removed = canon.char_delta("abc", "axc")
    assert added == 1 and removed == 1


def test_safe_name_keeps_path_safe():
    assert canon.safe_name("tools/Read") == "tools__Read"
    assert canon.safe_name("系统/中文") == "系统__中文"


# ---------- L0 表面层 ----------


def test_surface_collects_expected_groups():
    arts = surface.collect()
    groups = {a.group for a in arts}
    assert {"system", "tools", "tnow", "slash"}.issubset(groups)


def test_surface_determinism():
    a = {x.name: x.sha for x in surface.collect()}
    b = {x.name: x.sha for x in surface.collect()}
    assert a == b


def test_surface_mutation_selftest_is_perfect():
    rep = surface.mutation_selftest()
    assert rep["perfect"] is True
    assert rep["probed"] >= 30
    assert rep["missed"] == []


def test_surface_check_against_committed_golden_passes():
    """golden 漂移是这条测试的失败模式——任何渲染的字节变化都会被它捕获。"""
    arts = surface.collect()
    changes = surface.compare(arts)
    # 期望：新写的 golden 与当前代码完全一致（写 golden 时已经锁齐）
    assert changes == [], f"L0 golden 与当前代码漂移：{[c.name for c in changes]}"


def test_surface_one_char_change_is_detected():
    """改一个字符 → 该 artifact 的 sha 必变（这是 L0 灵敏度的直接证明）。"""
    arts = surface.collect()
    target = next(a for a in arts if len(a.canonical) > 20 and a.group == "system")
    name = target.name
    mutated = []
    for a in arts:
        if a.name == name:
            mutated.append(
                surface.Artifact(
                    name=a.name,
                    text=a.text + "Z",
                    group=a.group,
                    note=a.note,
                )
            )
        else:
            mutated.append(a)
    mut_hashes = {x.name: x.sha for x in mutated}
    orig_hashes = {x.name: x.sha for x in arts}
    # 单 artifact 的 sha 必不同——其他保持稳定
    assert orig_hashes[name] != mut_hashes[name]
    # 且其他不能被牵连
    for k in orig_hashes:
        if k == name:
            continue
        assert orig_hashes[k] == mut_hashes[k], f"误牵连：{k}"
