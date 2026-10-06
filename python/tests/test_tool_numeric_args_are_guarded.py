"""门：工具不许把模型给的字符串裸 `int()/float()` —— 坏参数要报 INVALID_ARGUMENT，不许炸成 INTERNAL。

为什么这条值得钉死（不是一次性清扫）：
`tools/base_tool.py` 会把 `is_error=True` 且没分类的失败一律兜成 INTERNAL，而
`diagnostics/fault_split.py` / `rules.py` 明写"INTERNAL 说的是没分类，不是引擎出错"；
`tools/orchestration.py` 的 `except Exception` 又是最后一道兜底 —— 于是
`int(inp["count"])` 撞上 `"12abc"` 时，模型看到的是 `tool error: ValueError: ...`，
归属表看到的是"没分类"，**没人知道那是模型自己参数写错**。

判据（宁可窄）：`int()/float()` 的实参表达式引用了 input 类变量
（`input/inputs/data/args/raw/params/payload/tool_input`，含下标与 `.get()`），
且该行不在一个捕 `ValueError/TypeError/Exception` 的 `try` 块里。
命中面：生产 `tools/**`（含并发在途文件，命中 0 ⇒ KNOWN 为空）。
"""

import ast
import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_NAMES = ("input", "inputs", "data", "args", "raw", "params", "payload", "tool_input")

#: 全树实测：clean 文件 0 命中；下面这一处落在并发会话今日在改的文件里 ⇒ 挂账，
#: 落地后必须摘掉（摘的条件：那行 `int(read_input.offset)` 走进带 except 的区间，
#: 或改成"取不到数字就用 INVALID_ARGUMENT 明确拒绝"）。
#: 现状：模型给 offset 传非数字串时，`int()` 在 try 之外抛 ValueError
#: ⇒ 编排层兜成 `tool error: ValueError` + error_kind=INTERNAL（=没分类），
#: 本该是 INVALID_ARGUMENT（模型侧参数错）。
#: 2026-10-05：`_execute_pdf` 的裸 int() 已修（带兜底 + INVALID_ARGUMENT），摘账。
KNOWN: set[str] = set()


def _from_input(node, depth=0):
    if depth > 3:
        return False
    if isinstance(node, ast.Name):
        return node.id in INPUT_NAMES
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        return _from_input(node.value, depth + 1)
    if isinstance(node, ast.Call):
        base = node.func
        if isinstance(base, ast.Attribute) and base.attr == "get":
            return _from_input(base.value, depth + 1)
        return any(_from_input(a, depth + 1) for a in node.args)
    if isinstance(node, ast.BinOp):
        return _from_input(node.left, depth + 1) or _from_input(node.right, depth + 1)
    return False


def _input_params(fn):
    """函数里"承载模型输入"的名字：参数（含 typed `XxxInput`）+ 一层直接别名。

    工具有两种写法：`execute(self, input: dict)` 与 `call(self, inp: ReadInput)`；
    而 `raw = input or {}` / `data = input` 这种别名在真实代码里就是模型输入本身
    （`tool_registry`、`web_search_tool` 都这么写），不认别名会大面积漏判。
    """
    names = set()
    for a in list(fn.args.args) + list(fn.args.kwonlyargs) + list(fn.args.posonlyargs):
        n = a.arg
        if n.startswith(("inp", "input", "data", "arg", "param", "payload", "raw")):
            names.add(n)
        elif a.annotation is not None and ast.unparse(a.annotation).rstrip("]").endswith("Input"):
            names.add(n)
    for s in ast.walk(fn):
        if not isinstance(s, ast.Assign) or len(s.targets) != 1 or not isinstance(s.targets[0], ast.Name):
            continue
        v = s.value
        if isinstance(v, ast.Name) and v.id in names:
            names.add(s.targets[0].id)
        elif isinstance(v, ast.BoolOp) and isinstance(v.values[0], ast.Name) and v.values[0].id in names:
            names.add(s.targets[0].id)
    return names


def _refs(node, names, depth=0):
    """表达式是否引用了这些参数（含 `inp.offset` / `data["count"]` / `args.get(...)`）。"""
    if depth > 4:
        return False
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        return _refs(node.value, names, depth + 1)
    if isinstance(node, ast.Call):
        base = node.func
        if isinstance(base, ast.Attribute) and base.attr == "get":
            return _refs(base.value, names, depth + 1)
        return any(_refs(a, names, depth + 1) for a in node.args)
    if isinstance(node, ast.BinOp):
        return _refs(node.left, names, depth + 1) or _refs(node.right, names, depth + 1)
    return False


def _protected_lines(fn):
    """被 except ValueError/TypeError/Exception（或裸 except）覆盖的行区间。"""
    covered = set()
    for s in ast.walk(fn):
        if not isinstance(s, ast.Try):
            continue
        catches = False
        for h in s.handlers:
            if h.type is None:
                catches = True
                continue
            names = [ast.unparse(t) for t in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type])]
            if set(names) & {"ValueError", "TypeError", "Exception", "BaseException",
                             "builtins.ValueError", "builtins.TypeError"}:
                catches = True
        if not catches:
            continue
        stmts = list(s.body) + list(s.orelse)
        if not stmts:
            continue
        lo = min(x.lineno for x in stmts)
        hi = max(getattr(x, "end_lineno", x.lineno) or x.lineno for x in stmts)
        covered.update(range(lo, hi + 1))
    return covered


def scan_source(src):
    tree = ast.parse(src)
    hits = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = _input_params(fn)
        if not names:
            continue
        covered = _protected_lines(fn)
        for s in ast.walk(fn):
            if not isinstance(s, ast.Call) or not (isinstance(s.func, ast.Name) and s.func.id in ("int", "float")):
                continue
            if not s.args or not _refs(s.args[0], names):
                continue
            if s.lineno in covered:
                continue
            hits.append((s.lineno, fn.name))
    return hits


_CTL_BAD = [
    '''
def run(inp):
    raw = inp
    n = int(raw["count"])
    return n
''',
    '''
def run(input):
    return float(input.get("temp"))
''',
    # typed dataclass 形状（工具的主流写法：call(self, inp: XxxInput)）
    '''
class ReadInput:
    offset: int

def call(inp: ReadInput):
    return int(inp.offset)
''',
]

_CTL_GOOD = [
    # 显式兜住类型/值错
    '''
def run(input):
    try:
        return int(input["count"])
    except (TypeError, ValueError):
        return 1
''',
    # `or 0` 让非数字串走 falsy 分支，不抛
    '''
def run(input):
    return int(input.get("count") or 0)
''',
    # 与模型输入无关的常量转换
    '''
def run(input):
    return int("12")
''',
    # int() 无参
    '''
def run(input):
    return int()
''',
]


def test_detector_has_teeth():
    for i, src in enumerate(_CTL_BAD):
        assert scan_source(src), f"裸转换的坏形状 #{i} 必须判红"
    for i, src in enumerate(_CTL_GOOD):
        assert not scan_source(src), f"安全形状 #{i} 不许判红：{scan_source(src)}"


def test_tools_do_not_parse_model_numbers_barely():
    found = set()
    base = ROOT / "tools"
    for dirpath, dirnames, filenames in os.walk(str(base)):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".venv")]
        for f in filenames:
            if not f.endswith(".py"):
                continue
            p = os.path.join(dirpath, f)
            rel = p.replace("\\", "/")
            rel = rel[rel.index("/tools/") + 1:]
            src = io.open(p, encoding="utf-8-sig", errors="replace").read()
            for ln, fn in scan_source(src):
                found.add(f"{rel}::{fn}")
    assert found == KNOWN, (
        "工具里对模型给的数字必须走带兜底的取值（见模块 docstring：否则坏参数被记成 INTERNAL=没分类）。\n"
        f"新出现: {sorted(found - KNOWN)}\n可以摘账: {sorted(KNOWN - found) or '无'}"
    )
