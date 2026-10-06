"""`error_kind` 的双重闭合：既是清单内的名字，又必须有归属 party。

为什么值得钉：`diagnostics/fault_split.py` 按 `_ENGINE_KINDS / _ENVIRONMENT_KINDS /
_MODEL_KINDS` 三个集合给失败定责，**认不出的名字一律落到"归属未定"**，而且不报错、
不红、不留痕 ⇒ 新增一个 kind 的人永远不知道自己漏了一格。

10-04 实测抓到一条已经存在的漏洞：`tools/tool_registry.py:307` 发的
`error_kind="ACTION_JOURNAL_UNAVAILABLE"` 既不在 `tools/error_taxonomy.py` 的清单里，
也不在任何归属集合里 ⇒ "我方动作账本写不进去"这一格一直静默未定责。
本轮修法：把该名字登记进 taxonomy 并放进 `_ENGINE_KINDS`（失败的是我方记账子系统，
不是模型参数、也不是外部基础设施），并用本门防止以后再出现"裸字符串 kind"。

本门同时反向查：归属集合里写了清单没有的名字（打错的 `"PERMISSION_DENY"`）
等于那条规则**永远匹配不上**，也是静默失效 —— 所以两个方向都必须闭合。

有意未定责的两格由 `UNPLACED_BY_DECISION` 显式登记（带理由），
不是"豁免列表"式的沉默：条目消失时本门会红。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import diagnostics.fault_split as fault_split  # noqa: E402
import tools.error_taxonomy as taxonomy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("tools", "engine", "server", "session", "coord", "channels", "memory", "diagnostics")

#: 有意的"不定责"，必须带理由；集合本身要精确相等（对齐后忘了登记也会红）。
UNPLACED_BY_DECISION = {
	# 引擎只填"没分类"这个事实；把它算成我方故障等于把全部工具失败判给自己。
	"INTERNAL": "base_tool/classify_exception 的兜底值，语义是未细分",
	# 两条成因（插件钩子 should_abort / 用户停止）都不是模型侧，也没有 user party。
	"ABORTED": "用户停止或钩子中止，两案都不该算到某方头上",
}


def inventory() -> set[str]:
    return {
        name
        for name in taxonomy.__all__
        if name.isupper() and isinstance(getattr(taxonomy, name, None), str)
    }


def placed() -> set[str]:
    return (
        set(fault_split._ENGINE_KINDS)
        | set(fault_split._ENVIRONMENT_KINDS)
        | set(fault_split._MODEL_KINDS)
    )


def missing_placement(kinds: set[str], have: set[str], exempt: set[str]) -> set[str]:
    return kinds - have - exempt


def unknown_names(kinds: set[str], have: set[str], exempt: set[str]) -> set[str]:
    return (have | exempt) - kinds


def scan_raw_error_kinds() -> dict[str, set[str]]:
    """生产树里 `error_kind="字面量"` 但不在清单内的位置。"""
    out: dict[str, set[str]] = {}
    known = inventory()
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            try:
                tree = ast.parse(p.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "error_kind" or not isinstance(kw.value, ast.Constant):
                        continue
                    val = kw.value.value
                    if isinstance(val, str) and val and val not in known:
                        out.setdefault(rel, set()).add(f"{val}@{node.lineno}")
    return out


# ---------------------------------------------------------------- 真实闭合检查


def test_every_inventory_kind_has_a_party_or_an_explicit_reason() -> None:
    gaps = missing_placement(inventory(), placed(), set(UNPLACED_BY_DECISION))
    assert not gaps, f"这些 error_kind 会被诊断静默算成未定责：{sorted(gaps)}"


def test_every_party_name_is_a_real_kind() -> None:
    ghosts = unknown_names(inventory(), placed(), set(UNPLACED_BY_DECISION))
    assert not ghosts, f"归属集合里有清单外的名字（打错=永不匹配）：{sorted(ghosts)}"


def test_exempt_list_has_no_stale_entries() -> None:
    assert set(UNPLACED_BY_DECISION) <= inventory(), "豁免登记了不存在的 kind"
    for name, why in UNPLACED_BY_DECISION.items():
        assert why.strip(), f"{name} 的未定责理由不能为空"


def test_no_uninventoried_error_kind_literals_in_production() -> None:
    strays = scan_raw_error_kinds()
    assert not strays, f"裸字符串 error_kind 绕过了清单：{strays}"


# ------------------------------------------------------------- 门的牙（合成夹具）

NEW_KIND = "SOMETHING_BRAND_NEW"
TYPO = "PERMISSION_DENY"


def test_gate_flags_a_new_kind_without_party() -> None:
    assert missing_placement(inventory() | {NEW_KIND}, placed(), set(UNPLACED_BY_DECISION)) == {
        NEW_KIND
    }


def test_gate_flags_a_typo_in_a_party_set() -> None:
    assert unknown_names(inventory(), placed() | {TYPO}, set(UNPLACED_BY_DECISION)) == {TYPO}


def test_gate_is_not_vacuously_satisfied() -> None:
    """清单与集合都非空且确有交集，否则上面几条都是空转。"""
    kinds, have = inventory(), placed()
    assert len(kinds) >= 12, kinds
    assert have & kinds, (have, kinds)
    assert have - kinds == set(), sorted(have - kinds)
