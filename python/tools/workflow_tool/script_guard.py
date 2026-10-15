"""Workflow 脚本静态守卫与准备：AST 白名单 → 可执行入口函数。

**边界声明（必读）**：这是**表达能力约束**，不是安全边界。它把模型写的编排脚本
限制成「纯编排表达」——只有循环 / 条件 / 推导式 / 白名单函数调用，没有 import、
没有属性访问、没有 dunder、没有 exec/eval/open/compile。但它挡不住所有 Python
逃逸技巧；真正的边界是进程隔离（沙箱），沙箱未落地前本工具**默认关**（见
``engine/flag_definitions.py`` 的 ``XEYO_WORKFLOW``）。

与 dsh 的同位设计一致：dsh 在 ``workflow-worker-thread/src/realm.ts`` 里也写明
「the vm is not a security boundary」——两端都把「脚本执行器」与「安全边界」分开。

设计取舍：
- **拒绝 Attribute**（而不是过滤 dunder）：``json.dumps`` 这类写法一并禁掉，
  换成注入的 ``to_json`` / ``from_json`` 纯函数。少一个白名单维度，少一类绕过面。
- **函数名白名单**：只认注入的编排原语 + 一组无副作用内置函数。
- **入口统一包成函数**：``exec`` 不支持顶层 ``return``，所以脚本被包进
  ``__xeyo_workflow__`` 再调用。两种写法都认：末行是表达式（取值）或显式 ``return``。
- **上限**：脚本长度 / AST 节点数 / 嵌套深度都在静态层硬卡；agent 次数在执行层卡。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

#: 脚本字符上限（模型写编排脚本，不该写成长程序）。
MAX_SCRIPT_CHARS = 20_000
#: AST 节点上限（防"短文本、深展开"的构造）。
MAX_AST_NODES = 6_000
#: 语法树嵌套深度上限。
MAX_DEPTH = 24

#: 生成的入口函数名。脚本自身不得引用（下划线开头一律拒）。
ENTRY_NAME = "__xeyo_workflow__"

#: 编排原语（由 workflow_tool 注入，非内置）。
ORCHESTRATION_NAMES = frozenset({
    "agent",
    "parallel",
    "pipeline",
    "phase",
    "log",
})

#: 允许调用的无副作用内置（白名单，不是黑名单）。
SAFE_BUILTIN_NAMES = frozenset({
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "print", "range", "round", "set", "sorted", "str",
    "sum", "tuple", "zip",
})

#: 注入的纯函数（JSON 收发；替代被禁掉的属性访问）。
SAFE_HELPER_NAMES = frozenset({"to_json", "from_json"})

_CALLABLE_NAMES = ORCHESTRATION_NAMES | SAFE_BUILTIN_NAMES | SAFE_HELPER_NAMES

#: 结构类节点白名单。运算符/上下文节点（ast.operator / ast.cmpop / ast.expr_context
#: 的子类）不在此表里，由 ``_is_operator_node`` 放行——它们是语法结构的组成部分，
#: 不携带独立能力。
_ALLOWED_NODES: frozenset[type] = frozenset({
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign,
    ast.For, ast.While, ast.If, ast.FunctionDef, ast.Return,
    ast.Break, ast.Continue, ast.Pass, ast.Call, ast.Name, ast.Constant,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp,
    ast.Lambda, ast.Starred, ast.keyword, ast.arguments, ast.arg,
    ast.JoinedStr, ast.FormattedValue, ast.Try, ast.ExceptHandler,
    ast.Raise, ast.comprehension, ast.Load, ast.Store, ast.Del,
})

#: 显式拒绝的节点（先判它们，报错信息更准确）。
_FORBIDDEN_NODES: dict[type, str] = {
    ast.Import: "import is not available in workflow scripts",
    ast.ImportFrom: "import is not available in workflow scripts",
    ast.Global: "global is not available in workflow scripts",
    ast.Nonlocal: "nonlocal is not available in workflow scripts",
    ast.ClassDef: "class definitions are not available in workflow scripts",
    ast.AsyncFunctionDef: "async def is not available in workflow scripts",
    ast.AsyncFor: "async for is not available in workflow scripts",
    ast.AsyncWith: "async with is not available in workflow scripts",
    ast.With: "with is not available in workflow scripts",
    ast.Await: "await is not available in workflow scripts",
    ast.Yield: "yield is not available in workflow scripts",
    ast.YieldFrom: "yield from is not available in workflow scripts",
    ast.Delete: "del is not available in workflow scripts",
    ast.Attribute: "attribute access is not available in workflow scripts",
}


class ScriptRejected(ValueError):
    """脚本未通过静态守卫（消息为中性事实，不含劝导）。"""


@dataclass(frozen=True)
class ScriptFacts:
    """通过守卫的脚本静态事实（供 tool_result metadata）。"""

    chars: int
    nodes: int
    calls: int
    agent_calls: int


@dataclass(frozen=True)
class PreparedScript:
    """准备就绪的脚本：可 exec 的代码 + 入口名 + 静态事实。"""

    code: Any
    entry: str
    facts: ScriptFacts


def _is_operator_node(node: ast.AST) -> bool:
    return isinstance(
        node,
        (ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context),
    )


def _depth(node: ast.AST, level: int = 0) -> int:
    best = level
    for child in ast.iter_child_nodes(node):
        best = max(best, _depth(child, level + 1))
    return best


def _empty_arguments() -> ast.arguments:
    return ast.arguments(
        posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
        kw_defaults=[], kwarg=None, defaults=[],
    )


def _make_entry(body: list[ast.stmt]) -> ast.FunctionDef:
    """把一段语句包成入口函数；末行若是表达式则转成 return。"""
    statements = list(body)
    if statements and isinstance(statements[-1], ast.Expr):
        statements[-1] = ast.Return(value=statements[-1].value)
    kwargs: dict[str, Any] = {}
    if "type_params" in getattr(ast.FunctionDef, "_fields", ()):
        kwargs["type_params"] = []
    return ast.FunctionDef(
        name=ENTRY_NAME,
        args=_empty_arguments(),
        body=statements or [ast.Pass()],
        decorator_list=[],
        returns=None,
        type_comment=None,
        **kwargs,
    )


def _build_module(script: str) -> ast.Module:
    """脚本文本 → 只含入口函数的 Module。

    说明：顶层 ``return`` 在 CPython 里**能通过 ast.parse**（"return outside
    function" 是编译期符号表检查，``PyCF_ONLY_AST`` 不做），所以这里只需把语句
    搬进入口函数——不需要任何文本级包裹（那会破坏多行字符串字面量）。
    """
    try:
        parsed = ast.parse(script, mode="exec")
    except SyntaxError as exc:
        raise ScriptRejected(
            f"syntax error at line {exc.lineno}: {exc.msg}"
        ) from exc
    module = ast.Module(body=[_make_entry(parsed.body)], type_ignores=[])
    ast.fix_missing_locations(module)
    return module


def _validate(module: ast.Module) -> tuple[int, int, int]:
    """校验节点白名单/命名/调用面；返回 (nodes, calls, agent_calls)。"""
    nodes = list(ast.walk(module))
    if len(nodes) > MAX_AST_NODES:
        raise ScriptRejected(
            f"script too complex: {len(nodes)} nodes (limit {MAX_AST_NODES})"
        )
    if _depth(module) > MAX_DEPTH:
        raise ScriptRejected(f"script nesting too deep (limit {MAX_DEPTH})")
    calls = 0
    agent_calls = 0
    for node in nodes:
        for cls, message in _FORBIDDEN_NODES.items():
            if isinstance(node, cls):
                line = getattr(node, "lineno", 0)
                raise ScriptRejected(f"line {line}: {message}")
        if _is_operator_node(node):
            continue
        if type(node) not in _ALLOWED_NODES:
            line = getattr(node, "lineno", 0)
            raise ScriptRejected(
                f"line {line}: {type(node).__name__} is not available in workflow scripts"
            )
        if isinstance(node, ast.Name):
            if node.id == ENTRY_NAME:
                continue
            if node.id.startswith("_"):
                raise ScriptRejected(
                    f"line {node.lineno}: name '{node.id}' is not available"
                )
        if isinstance(node, ast.Call):
            calls += 1
            func = node.func
            if not isinstance(func, ast.Name):
                raise ScriptRejected(
                    f"line {node.lineno}: only direct calls to orchestration "
                    "helpers are allowed"
                )
            if func.id not in _CALLABLE_NAMES:
                raise ScriptRejected(
                    f"line {node.lineno}: '{func.id}' is not callable in workflow scripts"
                )
            if func.id == "agent":
                agent_calls += 1
    return len(nodes), calls, agent_calls


def prepare_script(script: str) -> PreparedScript:
    """校验并编译脚本；不通过抛 ``ScriptRejected``。

    入口函数是**生成**的（不是用户写的），校验会跳过它的名字；用户语句被原样
    搬进函数体，因此**行号与用户脚本一致**。
    """
    text = script if isinstance(script, str) else ""
    if not text.strip():
        raise ScriptRejected("empty script")
    if len(text) > MAX_SCRIPT_CHARS:
        raise ScriptRejected(
            f"script too long: {len(text)} chars (limit {MAX_SCRIPT_CHARS})"
        )
    module = _build_module(text)
    nodes, calls, agent_calls = _validate(module)
    try:
        code = compile(module, "<workflow>", "exec")
    except SyntaxError as exc:  # 生成节点不应产生语法错；兜底不静默
        raise ScriptRejected(f"syntax error: {exc.msg}") from exc
    return PreparedScript(
        code=code,
        entry=ENTRY_NAME,
        facts=ScriptFacts(
            chars=len(text),
            nodes=nodes,
            calls=calls,
            agent_calls=agent_calls,
        ),
    )


def validate_script(script: str) -> ScriptFacts:
    """兼容入口：只取静态事实。"""
    return prepare_script(script).facts


__all__ = [
    "ENTRY_NAME",
    "MAX_AST_NODES",
    "MAX_DEPTH",
    "MAX_SCRIPT_CHARS",
    "ORCHESTRATION_NAMES",
    "SAFE_BUILTIN_NAMES",
    "SAFE_HELPER_NAMES",
    "PreparedScript",
    "ScriptFacts",
    "ScriptRejected",
    "prepare_script",
    "validate_script",
]
