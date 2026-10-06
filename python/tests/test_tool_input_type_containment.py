"""Grep/Glob 的 string 字段拿到非 string 时必须吵，不许把请求换了再执行。

缺陷（2026-10-03 实测）：解析层写成 `x.strip() if isinstance(x, str) else None`，
`pattern` 又写成 `str(raw.get("pattern"))` ⇒ 模型发列表时：

- `glob=['*.py']`：过滤器被**静默丢掉**，搜遍整个工作区还照常报 "Found 2 files"。
  同一条请求用字符串 `glob='*.py'` 是 1 个文件 ⇒ 覆盖面翻倍而模型看不出来。
- `type=['txt']`：同上。
- `pattern=['lpha']`：被强造成字面量 `['lpha']` 当正则跑，字符类里的 `l/p/h/a` 都能命中，
  返回一个看着合理、其实答的不是所问的结果。
- `path=['src']`（Glob）：`Path(*['src'])` 恰好等价于 `'src'` 而蒙对，`path=123` 则退回整仓搜。

修法：`tools/input_types.string_field_type_error` 只做类型收口 —— 缺省、`None`、
以及 JS 侧的 `"undefined"`/`"null"` 字面量仍按"没给"处理（既有兼容），只有"给了但不是
字符串"才挡下来。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry
from tools.input_types import string_field_type_error


@pytest.fixture()
def reg(tmp_path: Path) -> object:
    (tmp_path / "a.txt").write_text("Alpha txt\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("Alpha py\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "c.md").write_text("x\n", encoding="utf-8")
    return build_default_registry(cwd=str(tmp_path))


async def _run(reg: object, name: str, payload: dict) -> object:
    return await reg.run(  # type: ignore[attr-defined]
        ToolUse(id="tu", name=name, input=payload), AbortController(), skip_ask=True
    )


@pytest.mark.parametrize(
    "name,payload,field",
    [
        ("Grep", {"pattern": "Alpha", "glob": ["*.py"], "output_mode": "files_with_matches"}, "glob"),
        ("Grep", {"pattern": "Alpha", "type": ["txt"], "output_mode": "files_with_matches"}, "type"),
        ("Grep", {"pattern": ["lpha"], "output_mode": "files_with_matches"}, "pattern"),
        ("Grep", {"pattern": "x", "path": ["src"], "output_mode": "files_with_matches"}, "path"),
        ("Glob", {"pattern": "*.md", "path": ["src"]}, "path"),
        ("Glob", {"pattern": 123}, "pattern"),
        # detail 决定视图（Grep: signatures/folded；Glob: paths/folded）。原先非字符串被
        # 静默按默认视图执行——模型以为换了视图，实际什么都没变。
        ("Grep", {"pattern": "Alpha", "output_mode": "content", "detail": ["signatures"]}, "detail"),
        ("Glob", {"pattern": "*.py", "detail": 123}, "detail"),
    ],
)
async def test_non_string_field_is_rejected(
    reg: object, name: str, payload: dict, field: str
) -> None:
    res = await _run(reg, name, payload)
    assert res.is_error is True, f"{name} 把非法的 {field} 静默接受了：{res.content[:120]!r}"
    assert res.content.startswith(f"invalid {field}:"), res.content[:120]
    assert "expected a string" in res.content


async def test_list_glob_no_longer_widens_the_search(reg: object) -> None:
    """被修掉的那个具体后果：字符串 glob 限制到 1 个文件，列表形态过去报 2 个。"""
    narrow = await _run(reg, "Grep", {
        "pattern": "Alpha", "glob": "*.py", "output_mode": "files_with_matches",
    })
    assert narrow.is_error is False
    assert "Found 1 file" in narrow.content, narrow.content[:120]

    bogus = await _run(reg, "Grep", {
        "pattern": "Alpha", "glob": ["*.py"], "output_mode": "files_with_matches",
    })
    assert bogus.is_error is True
    assert "Found 2 files" not in bogus.content, "覆盖面仍被静默放宽，只是顺便给了个错误"


async def test_string_forms_still_work(reg: object) -> None:
    """反向对照：收口不许把合法输入一起挡掉。"""
    ok_cases = [
        ("Grep", {"pattern": "Alpha", "glob": "*.py", "output_mode": "files_with_matches"}),
        ("Grep", {"pattern": "Alpha", "type": "py", "output_mode": "files_with_matches"}),
        ("Grep", {"pattern": "Alpha", "path": "src", "output_mode": "files_with_matches"}),
        ("Glob", {"pattern": "*.md", "path": "src"}),
    ]
    for name, payload in ok_cases:
        res = await _run(reg, name, payload)
        assert res.is_error is False, f"{name} {payload} 被误挡：{res.content[:120]!r}"


async def test_absent_and_jsish_null_placeholders_still_mean_absent(reg: object) -> None:
    """既有兼容：缺省、None、"undefined"/"null" 字面量都按"没给"处理，不得变成报错。"""
    for payload in (
        {"pattern": "*.md"},
        {"pattern": "*.md", "path": None},
        {"pattern": "*.md", "path": "undefined"},
        {"pattern": "*.md", "path": "null"},
    ):
        res = await _run(reg, "Glob", payload)
        assert res.is_error is False, f"{payload} 被当成类型错：{res.content[:120]!r}"


def test_helper_unit_behaviour() -> None:
    """辅助函数自己的边界：只挡"给了且不是字符串"。"""
    fields = ("pattern", "path")
    assert string_field_type_error({}, fields) == ""
    assert string_field_type_error({"pattern": "x", "path": None}, fields) == ""
    assert string_field_type_error({"pattern": "x"}, fields) == ""
    msg = string_field_type_error({"path": ["a", "b"]}, fields)
    assert msg.startswith("invalid path:") and "list" in msg
    # 数字/布尔/字典同样挡；bool 不是 str
    assert string_field_type_error({"pattern": True}, fields).startswith("invalid pattern:")
    assert string_field_type_error({"pattern": {"a": 1}}, fields).startswith("invalid pattern:")
    # 超长值截断，不许把整段 payload 抄进模型可见文本
    long = string_field_type_error({"pattern": ["x" * 500]}, fields)
    assert len(long) < 200, long[:200]


# ---------------------------------------------------------------- 策略层的同一条线
# `_pick_path` 把"没给路径"和"给了但不是字符串"合并成 None，于是 DENY 的原因只能写
# "missing_file_path"。模型明明发了 `file_path: 123`，被告知"缺 file_path"就会照原样
# 再发一遍 —— 一次类型错被指成一次遗漏，是模型可见文本里的假事实。
POLICY_CASES = [
    ({"file_path": 123, "content": "x"}, "file_path_not_a_string"),
    ({"file_path": ["a.txt"], "content": "x"}, "file_path_not_a_string"),
    ({"content": "x"}, "missing_file_path"),
    ({"file_path": "", "content": "x"}, "missing_file_path"),
    ({"file_path": None, "content": "x"}, "missing_file_path"),
]


@pytest.mark.parametrize("payload,expected_reason", POLICY_CASES)
def test_policy_names_the_actual_problem(
    tmp_path: Path, payload: dict, expected_reason: str
) -> None:
    from permissions.policy import evaluate_policy

    decision = evaluate_policy("Write", payload, cwd=str(tmp_path))
    assert str(getattr(decision.decision, "value", decision.decision)) == "deny"
    assert decision.reason == expected_reason, (
        f"{payload} 的原因说错了：{decision.reason!r}（rule={decision.matched_rule!r}）"
    )


def test_policy_still_allows_an_ordinary_string_path(tmp_path: Path) -> None:
    """反向对照：原因分档不许把正常放行一起改掉。"""
    from permissions.policy import evaluate_policy

    target = tmp_path / "ok.txt"
    decision = evaluate_policy("Write", {"file_path": str(target), "content": "x"}, cwd=str(tmp_path))
    reason = str(getattr(decision.decision, "value", decision.decision))
    assert reason in ("allow", "ask"), f"正常路径被挡：{decision.reason!r}"


async def test_valid_detail_values_still_accepted(reg: object) -> None:
    """反向控制：守卫只挡类型，合法视图口径一项都不许关小。"""
    for name, payload in (
        ("Glob", {"pattern": "*.py", "detail": "paths"}),
        ("Glob", {"pattern": "*.py", "detail": "folded"}),
        ("Glob", {"pattern": "*.py", "detail": "auto"}),
        ("Grep", {"pattern": "Alpha", "output_mode": "content", "detail": "signatures"}),
        ("Grep", {"pattern": "Alpha", "output_mode": "content", "detail": "folded"}),
    ):
        res = await _run(reg, name, payload)
        assert not res.is_error, (name, payload, str(res.content)[:140])


def test_detail_is_declared_in_both_schemas() -> None:
    """守卫清单跟着 schema 走：这两个工具确实把 detail 声明成 string 字段。"""
    from tools.catalog import build_default_registry

    reg = build_default_registry(cwd=".")
    for name in ("Glob", "Grep"):
        props = reg._tools[name].schema()["input_schema"]["properties"]  # type: ignore[attr-defined]
        assert props["detail"]["type"] == "string", name
