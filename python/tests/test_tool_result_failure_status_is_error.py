"""静态门：失败态 `ToolResult` 的**两层判定必须一致**（本门不预设哪边对）。

同一条事实有两个读者，默认值相反：

- `msgtypes.message.tool_result_message`：`is_error = bool(is_error or status == "cancelled")`
  ⇒ 只要 `status="cancelled"`，**模型看到的那一行**就是失败；
- `tools/base_tool.ToolResult.__post_init__`：只有 `status == "error"` 才反推 `is_error=True`
  ⇒ `status="cancelled"` 且没写 `is_error=True` 时，**审计 / 编排 / 熔断读到的是成功**。

⇒ 同一枪在两个面上一个是失败一个是成功：错误率、`fault_split` 归属、
loop_breaker 的"这一枪有没有进展"都会被喂成成功。

本门**不裁决哪边是对的**（那是政策）：只要求"给同一枪写的两个 `is_error` 不许互相矛盾"。
`status="error"` 时两层都算失败 ⇒ 不写 `is_error` 也算一致；`cancelled` 时必须两边同向
（写 `is_error=True`，或改掉 `msgtypes` 那个 or 条件——两边各自对齐都算过）。

已登记的一处不一致（KNOWN，必须精确相等才算过）：
`tools/orchestration.py:274` 的 `asyncio.CancelledError` 分支写
`_error_result(..., status="cancelled", is_error=False, cancelled=True)`，
注释原文「T2：用户中止 → 确定性结果，**非 error**」⇒ 意图明确，与 `msgtypes` 的行级
推导相互矛盾，需两侧择一对齐。该文件此刻在并发会话手里（M），故只登记不代改。

可判定的表达式才判：`is_error` 写成变量/函数调用时本门**跳过并计数**（打进分母），
不假装"0 命中 = 全树干净"。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("tools", "engine", "server", "session", "coord", "channels", "memory")

#: 两层都判失败的写法不用管；只有 cancelled 会分叉（error 时 __post_init__ 也会置 True）。
ROW_FORCED_FAILURE = frozenset({"cancelled"})
TOOL_RESULT_NAMES = frozenset({"ToolResult"})
ERROR_HELPER_NAMES = frozenset({"_error_result"})

#: "行说失败、机器面说成功"的生产点（带归属；对齐后必须从这里摘掉）。
KNOWN = {
	"tools/orchestration.py:274 _error_result(status='cancelled', is_error=False)",
}


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _keywords(node: ast.Call) -> dict[str, ast.expr]:
    return {k.arg: k.value for k in node.keywords if k.arg}


def _const(node: ast.expr | None, typ: type) -> object | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, typ):
        return node.value
    return None


def scan_text(text: str, label: str) -> tuple[list[str], int]:
    """返回 (矛盾清单, 判不了而跳过的数量)。"""
    problems: list[str] = []
    skipped = 0
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [f"{label}: UNPARSEABLE"], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in TOOL_RESULT_NAMES and name not in ERROR_HELPER_NAMES:
            continue
        kw = _keywords(node)
        status = _const(kw.get("status"), str)
        if status not in ROW_FORCED_FAILURE:
            continue
        if "is_error" not in kw:
            # `_error_result` 默认 True（一致）；裸 ToolResult 默认 False（矛盾）。
            if name in TOOL_RESULT_NAMES:
                problems.append(
                    f"{label}:{node.lineno} {name}(status={status!r}) 缺 is_error "
                    "⇒ 行=失败 / 机器面=成功"
                )
            continue
        value = _const(kw["is_error"], bool)
        if value is None:
            skipped += 1
            continue
        if value is False:
            problems.append(
				f"{label}:{node.lineno} {name}(status={status!r}, is_error=False)"
            )
    return problems, skipped


def scan_production_tree() -> tuple[set[str], int, int]:
    findings: set[str] = set()
    total_skipped = 0
    files = 0
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            try:
                text = p.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                findings.add(f"{rel}: UNREADABLE")
                continue
            files += 1
            found, skipped = scan_text(text, rel)
            total_skipped += skipped
            findings.update(found)
    return findings, files, total_skipped


# -------------------------------------------------------------- 双向夹具（门的牙）

CONTRADICTING = (
    'ToolResult(content="x", status="cancelled")',
    'ToolResult(content="x", is_error=False, status="cancelled")',
    '_error_result(content="x", kind="ABORTED", retryable=False, status="cancelled", is_error=False)',
)

CONSISTENT = (
    'ToolResult(content="x", is_error=True, status="cancelled")',
    '_error_result(content="x", kind="ABORTED", retryable=False, status="cancelled")',
    'ToolResult(content="x", status="error")',
    'ToolResult(content="x", is_error=False, status="ok")',
    'ToolResult(content="x")',
)


@pytest.mark.parametrize("src", CONTRADICTING)
def test_gate_flags_row_machine_disagreement(src: str) -> None:
    problems, skipped = scan_text(src, "<fixture>")
    assert problems, (src, problems, skipped)


@pytest.mark.parametrize("src", CONSISTENT)
def test_gate_does_not_flag_agreed_shapes(src: str) -> None:
    problems, skipped = scan_text(src, "<fixture>")
    assert not problems, (src, problems)


def test_gate_is_not_blind_to_dynamic_is_error() -> None:
    """`is_error` 写成变量时判不了 ⇒ 计入分母并出声，不许当成"通过"。"""
    problems, skipped = scan_text(
        'ToolResult(content="x", is_error=flag, status="cancelled")', "<fixture>"
    )
    assert not problems and skipped == 1, (problems, skipped)


def test_production_tree_has_no_unregistered_disagreements() -> None:
    findings, files, skipped = scan_production_tree()
    assert files > 200, files  # 作用域自证：真扫到了生产树
    assert findings == KNOWN, (
        f"新增或已消失的两面账：{sorted(findings ^ KNOWN)}；全部现状={sorted(findings)}"
    )
    assert skipped < 40, f"is_error 动态化的调用过多（{skipped}），本门已近失明"
