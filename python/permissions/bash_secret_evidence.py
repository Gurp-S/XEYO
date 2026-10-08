"""Credential-token evidence excludes proven Python attributes in literal payloads."""
from __future__ import annotations
import ast
import re

_LITERAL = re.compile(r"@'\r?\n(.*?)\r?\n'@", re.S)


def match(command):
    from permissions.bash_policy import _SECRET_TOKEN_RX, _normalize_command
    from engine.execution_facts import enabled
    text = str(command or "")
    if enabled():
        chars = list(text)
        for payload in _LITERAL.finditer(text):
            source = payload.group(1)
            if len(source) > 32000:
                continue
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError, RecursionError):
                continue
            lines = source.splitlines(keepends=True)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute) or node.attr != "key":
                    continue
                # AST columns are UTF-8 bytes. Convert before mapping into shell text.
                line = lines[node.end_lineno - 1]
                column = len(line.encode("utf-8")[:node.end_col_offset].decode("utf-8"))
                dot = sum(len(row) for row in lines[:node.end_lineno - 1]) + column - 4
                if source[dot:dot + 4] == ".key":
                    chars[payload.start(1) + dot] = "_"
        text = "".join(chars)
    return _SECRET_TOKEN_RX.search(_normalize_command(text))
