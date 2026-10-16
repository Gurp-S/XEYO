"""Discover response envelopes from source, including direct helper delegation.

This test utility never imports application modules. It follows return expressions
through named functions and explicit imports inside the source root, with a cycle
guard. Dynamic dispatch and arbitrary data flow are outside this scanner's scope.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator
from pathlib import Path

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _scope_nodes(body: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Walk one scope, without attributing nested function/class returns to it."""
    for node in body:
        if isinstance(node, (*FUNCTIONS, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        yield from _scope_nodes(ast.iter_child_nodes(node))


class _Scanner:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.modules: dict[Path, ast.Module] = {}

    def module(self, path: Path) -> ast.Module:
        if path not in self.modules:
            self.modules[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return self.modules[path]

    def imports(self, nodes: Iterable[ast.AST]) -> dict[str, tuple[Path, str]]:
        bindings = {}
        for node in nodes:
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            target = self.root.joinpath(*node.module.split(".")).with_suffix(".py").resolve()
            if not target.is_relative_to(self.root) or not target.is_file():
                continue
            for alias in node.names:
                bindings[alias.asname or alias.name] = (target, alias.name)
        return bindings

    def envelope(self, path: Path, name: str, visiting: frozenset[tuple[Path, str]]) -> str | None:
        key = (path, name)
        if key in visiting:
            return None
        tree = self.module(path)
        functions = {node.name: node for node in tree.body if isinstance(node, FUNCTIONS)}
        function = functions.get(name)
        if function is None:
            return None
        nodes = list(_scope_nodes(function.body))
        targets = {}
        for node in tree.body:
            if isinstance(node, FUNCTIONS):
                targets[node.name] = (path, node.name)
            elif isinstance(node, ast.ClassDef):
                targets.pop(node.name, None)
            else:
                targets.update(self.imports([node]))
                for binding in _scope_nodes([node]):
                    if isinstance(binding, ast.Name) and isinstance(binding.ctx, ast.Store):
                        targets.pop(binding.id, None)
        targets.update(self.imports(nodes))
        # Arguments and local bindings can shadow an imported function. Never
        # follow a different function merely because it shares that name.
        arguments = function.args
        shadowed = {arg.arg for arg in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]}
        shadowed.update(arg.arg for arg in (arguments.vararg, arguments.kwarg) if arg)
        shadowed.update(node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
        shadowed.update(node.name for node in function.body if isinstance(node, (*FUNCTIONS, ast.ClassDef)))
        targets = {symbol: target for symbol, target in targets.items() if symbol not in shadowed}
        returns = [node for node in nodes if isinstance(node, ast.Return)]
        # Inspect direct responses first: there is no reason to parse helper
        # dependencies once this function already proves a possible rejection.
        for node in returns:
            value = node.value
            if isinstance(value, ast.Dict):
                for field, result in zip(value.keys, value.values):
                    if isinstance(field, ast.Constant) and field.value == "ok":
                        if not (isinstance(result, ast.Constant) and result.value is True):
                            return f"{path.relative_to(self.root)}:{node.lineno} ({name})"
        for node in returns:
            value = node.value.value if isinstance(node.value, ast.Await) else node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                target = targets.get(value.func.id)
                if target:
                    evidence = self.envelope(*target, visiting | {key})
                    if evidence:
                        return f"{path.relative_to(self.root)}:{node.lineno} ({name}) -> {evidence}"
        return None


def envelope_endpoints(routers: Path, source_root: Path) -> dict[str, str]:
    scanner = _Scanner(source_root)
    found = {}
    for path in sorted(routers.resolve().glob("*.py")):
        for function in scanner.module(path).body:
            if not isinstance(function, FUNCTIONS):
                continue
            routes = []
            for decorator in function.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)):
                    continue
                owner = decorator.func.value
                if not (isinstance(owner, ast.Name) and owner.id == "router"):
                    continue
                if decorator.func.attr not in {"get", "post", "put", "delete", "patch", "head", "options"}:
                    continue
                route = decorator.args[0] if decorator.args else next(
                    (kw.value for kw in decorator.keywords if kw.arg == "path"), None,
                )
                if isinstance(route, ast.Constant) and isinstance(route.value, str):
                    routes.append(route.value)
            if routes:
                evidence = scanner.envelope(path, function.name, frozenset())
                if evidence:
                    for route in routes:
                        found.setdefault(route, evidence)
    return found
