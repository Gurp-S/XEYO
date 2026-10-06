"""数字字段类型收口：值"怎么都当不成数"时必须吵，不许降级成"没给"。

缺陷（2026-10-03 生产派发实测，与已修的 string 分支同族）：解析层写成
``_coerce_optional_int``——认不出的一律返回 ``None``，而 ``None`` 在这些工具里
的含义是"没给"。于是：

- ``Read.limit='abc'`` ⇒ 读回**整份 534 行**（要求 5 行），看起来是一次成功的读取；
- ``Read.offset='abc'`` ⇒ 静默从第 1 行开始（要求第 500 行）；
- ``Grep.head_limit='abc'`` ⇒ 完全不截断（结果被预算挤去 spill）；
- ``Grep.-A='abc'`` ⇒ 上下文被丢光（模型会以为命中周围没有内容）。

口径与既有实现保持一致：缺席、``None``、空串、``"undefined"/"null"``、数字字符串、
int/float/bool 全部照常放行；只挡"给了且无论如何也当不成数"的形状。
"""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from tools.catalog import build_default_registry
from tools.input_types import int_field_type_error

SRC = Path(__file__).resolve().parents[1] / "tools" / "catalog.py"   # 534 行，够长


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "big.py").write_text(
        "".join(f"line {i} needle\n" for i in range(400)), encoding="utf-8"
    )
    shutil.copyfile(SRC, tmp_path / "catalog.py")
    return tmp_path


async def _run(ws: Path, name: str, payload: dict):
    reg = build_default_registry(cwd=str(ws))
    return await reg.run(
        ToolUse(id="tu", name=name, input=payload), AbortController(), skip_ask=True
    )


# ── 缺陷回归：坏数字值不再被当成"没给" ────────────────────────────────
@pytest.mark.parametrize(
    "name,payload,field",
    [
        ("Read", {"file_path": "catalog.py", "limit": "abc"}, "limit"),
        ("Read", {"file_path": "catalog.py", "limit": ["x"]}, "limit"),
        ("Read", {"file_path": "catalog.py", "limit": {"k": 1}}, "limit"),
        ("Read", {"file_path": "catalog.py", "offset": "abc", "limit": 3}, "offset"),
        ("Read", {"file_path": "catalog.py", "offset": ["x"], "limit": 3}, "offset"),
        # "inf" 能过 float()，但 int(float('inf')) 抛 OverflowError——原解析层只捕
        # ValueError，于是异常一路逃到 registry 之外把整个回合打死。
        ("Read", {"file_path": "catalog.py", "limit": "inf"}, "limit"),
        ("Read", {"file_path": "catalog.py", "limit": "-inf"}, "limit"),
        ("Grep", {"pattern": "needle", "path": ".", "head_limit": "abc"}, "head_limit"),
        ("Grep", {"pattern": "needle", "path": ".", "-A": ["x"]}, "-A"),
        ("Grep", {"pattern": "needle", "path": ".", "context": {"k": 1}}, "context"),
        ("Grep", {"pattern": "needle", "path": ".", "offset": "abc"}, "offset"),
        ("Glob", {"pattern": "*.py", "head_limit": "abc"}, "head_limit"),
        ("Glob", {"pattern": "*.py", "offset": ["x"]}, "offset"),
    ],
)
async def test_bad_numeric_field_is_rejected(ws: Path, name: str, payload: dict, field: str) -> None:
    res = await _run(ws, name, payload)
    assert res.is_error, (name, payload, str(res.content)[:120])
    text = str(res.content)
    assert text.startswith(f"invalid {field}: expected an integer, got "), text[:120]
    # 关键：不许把文件/搜索结果当回答吐回去（那才是"换了请求还装作成功"）
    assert "needle" not in text
    assert "→" not in text          # Read 的行号视图特征


# ── 反向控制：既有宽松口径一项都不许被关小 ────────────────────────────
@pytest.mark.parametrize(
    "value,expect_lines",
    [
        (5, 5),            # int
        ("5", 5),          # 数字字符串
        (5.9, 5),          # float 截断（原有行为）
        (True, 1),         # bool 走 int()（原有行为）
        (None, None),      # None = 没给 = 整份
        ("", None),        # 空串 = 没给
        ("  ", None),      # 纯空白 = 没给
        ("undefined", None),
        ("null", None),
    ],
)
async def test_lenient_numeric_paths_unchanged(
    ws: Path, value, expect_lines: int | None
) -> None:
    payload = {"file_path": "big.py"}
    if value is not None:
        payload["limit"] = value
    res = await _run(ws, "Read", payload)
    assert not res.is_error, str(res.content)[:160]
    body = [ln for ln in str(res.content).splitlines() if "→" in ln]
    if expect_lines is None:
        assert len(body) > 100, len(body)      # 没给限制 ⇒ 整份，口径不变
    else:
        assert len(body) == expect_lines, (value, len(body))


async def test_offset_still_positions_the_window(ws: Path) -> None:
    """`offset` 的有效值行为不许被收口带偏。"""
    res = await _run(ws, "Read", {"file_path": "big.py", "offset": 200, "limit": 3})
    assert not res.is_error, str(res.content)[:160]
    first = str(res.content).splitlines()[0]
    assert first.startswith("   200→"), first


# ── 单元：判定表本身 ──────────────────────────────────────────────────
@pytest.mark.parametrize(
    "value,ok",
    [
        (1, True), (1.5, True), (True, True), ("3", True), ("-1", True),
        ("3.5", True), ("", True), ("   ", True), ("undefined", True),
        ("null", True), (None, True),
        ("abc", False), ("1abc", False), (["x"], False), ({"k": 1}, False),
        ("nan", False), ("inf", False),
    ],
)
def test_helper_acceptance_table(value, ok: bool) -> None:
    got = int_field_type_error({"limit": value}, ("limit",))
    assert bool(got) is not ok, (value, got)


def test_absent_field_is_never_flagged() -> None:
    assert int_field_type_error({}, ("limit", "offset")) == ""
    assert int_field_type_error("not a dict", ("limit",)) == ""


def test_float_and_inf_strings_are_named_not_swallowed() -> None:
    """`nan`/`inf` 能过 float() 但不是可用下标——判定表要求它们也被挡。"""
    assert int_field_type_error({"offset": "nan"}, ("offset",)).startswith("invalid offset")
    assert int_field_type_error({"offset": "inf"}, ("offset",)).startswith("invalid offset")


# ── 结构门：schema 里声明的每个数字字段都必须被守卫覆盖 ────────────────
@pytest.mark.parametrize("tool_name", ["Read", "Grep", "Glob"])
def test_every_numeric_schema_field_is_guarded(tool_name: str) -> None:
    """新增整数/数字字段却忘了加守卫 ⇒ 当场红。

    搬家式失效（改解析层、加字段）是这一族缺陷重演的主要方式，只看上面几条
    行为用例挡不住"新字段走老路"。
    """
    reg = build_default_registry(cwd=".")
    tool = reg._tools[tool_name]  # type: ignore[attr-defined]
    schema = tool.schema()["input_schema"]
    declared = {
        name
        for name, spec in (schema.get("properties") or {}).items()
        if isinstance(spec, dict) and spec.get("type") in ("integer", "number")
    }
    module = __import__(
        {
            "Read": "tools.file_read_tool.file_read_tool",
            "Grep": "tools.grep_tool.grep_tool",
            "Glob": "tools.glob_tool.glob_tool",
        }[tool_name],
        fromlist=["*"],
    )
    cls = next(
        obj
        for obj in vars(module).values()
        if isinstance(obj, type) and getattr(obj, "name", "") == tool_name
    )
    guarded: set[str] = set()
    for node in ast.walk(ast.parse(Path(module.__file__).read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.ClassDef) and node.name == cls.__name__):
            continue
        for fn in node.body:
            if not isinstance(fn, ast.AsyncFunctionDef) or fn.name != "execute":
                continue
            for call in ast.walk(fn):
                if (
                    isinstance(call, ast.Call)
                    and getattr(call.func, "id", "") == "int_field_type_error"
                    and len(call.args) >= 2
                    and isinstance(call.args[1], ast.Tuple)
                ):
                    guarded |= {
                        el.value for el in call.args[1].elts if isinstance(el, ast.Constant)
                    }
    assert declared - guarded == set(), (
        f"{tool_name} 的数字字段没进守卫: {sorted(declared - guarded)}"
    )


# ── 半有限字面量：int(float(x)) 对 "1e400"/"inf" 抛的是 OverflowError ──────
# 四处解析层只捕 ValueError ⇒ 异常逃出 ToolRegistry.run（它对 BaseException
# 只记不吞）⇒ 整回合被打死。这一族比"静默降级"更坏：模型只是写了一种
# 数字表达，结果这一枪直接中断。
NON_FINITE = ["1e400", "1e309", "inf", "-inf", "nan", "  inf  "]


@pytest.mark.parametrize("value", NON_FINITE)
def test_shared_coercion_helpers_never_raise(value: str) -> None:
    from tools.bash_tool.bash_tool import _coerce_optional_int as bash_coerce
    from tools.file_read_tool.file_read_tool import _coerce_optional_int as read_coerce
    from tools.grep_tool.grep_tool import _coerce_optional_int as grep_coerce

    for fn in (bash_coerce, read_coerce, grep_coerce):
        assert fn(value) is None, (fn.__module__, value)


@pytest.mark.parametrize("value", NON_FINITE)
async def test_job_output_survives_bad_timeout(ws: Path, value: str) -> None:
    """生产派发层：job_output 的 timeout_ms 收到这些写法不得有异常逃逸。"""
    res = await _run(ws, "job_output", {"job_id": "no-such-job", "timeout_ms": value})
    assert res is not None and hasattr(res, "content")


@pytest.mark.parametrize("value", NON_FINITE)
def test_guard_helper_rejects_non_finite_strings(value: str) -> None:
    """守卫口径与解析层一致：这些写法如实挡回，不悄悄换成默认值。"""
    assert int_field_type_error({"limit": value}, ("limit",)).startswith("invalid limit")


def test_read_pdf_bad_offset_is_invalid_argument(tmp_path: Path) -> None:
    """PDF 页号取值带兜底（2026-10-05 摘账）：坏 offset ⇒ INVALID_ARGUMENT，不是 INTERNAL。

    此前 `_execute_pdf` 的裸 int() 在 try 外抛 ValueError，被编排层兜成
    `tool error: ValueError` + error_kind=INTERNAL（=没分类）。
    """
    from tools.error_taxonomy import INVALID_ARGUMENT
    from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput

    tool = FileReadTool(cwd=str(tmp_path))
    out = tool._execute_pdf(
        str(tmp_path / "x.pdf"), ReadInput(file_path="x.pdf", offset="abc")
    )
    assert out.is_error is True, out
    assert out.error_kind == INVALID_ARGUMENT, out.error_kind
    assert "invalid offset" in out.content
