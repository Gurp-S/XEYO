"""Lsp — 语言服务器查询（只读）。

六个动作：``status`` / ``definition`` / ``references`` / ``hover`` / ``symbols``
/ ``diagnostics``。

fail-open 纪律（``XEYO.md``：索引类改动必须 fail-open）：
- 该语言没有服务器 → **不是错误**，返回中性事实 + 当前可用语言列表；
- 启动/请求失败 → 丢弃该客户端并返回中性事实；
- 两者都**不**报"没有定义/没有引用"——那是假阴。
"""

from __future__ import annotations

import os
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.lsp_tool.prompt import DESCRIPTION, LSP_TOOL_NAME

_ACTIONS = ("status", "definition", "references", "hover", "symbols", "diagnostics")
_NEEDS_POSITION = ("definition", "references", "hover")


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class LspTool:
    name = LSP_TOOL_NAME

    def __init__(self, *, cwd: str = ".") -> None:
        self._cwd = os.path.abspath(cwd or ".")

    # -- 契约 ---------------------------------------------------------------

    @staticmethod
    def is_read_only() -> bool:
        return True

    @staticmethod
    def is_concurrency_safe() -> bool:
        # 服务器进程内部自行串行化请求；同批多个查询无副作用。
        return True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": DESCRIPTION,
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(_ACTIONS),
                        "description": "Query to run.",
                    },
                    "path": {
                        "type": "string",
                        "description": "File to query (workspace-relative or absolute).",
                    },
                    "line": {
                        "type": "integer",
                        "description": "1-based line for position queries.",
                    },
                    "character": {
                        "type": "integer",
                        "description": "1-based column; default 1.",
                    },
                    "include_declaration": {
                        "type": "boolean",
                        "description": "references: include the declaration. Default true.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        }

    # -- 执行 ---------------------------------------------------------------

    async def execute(
        self, input: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        raw = input if isinstance(input, dict) else {}
        action = str(raw.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                content=(
                    f"unknown action: {action or '(empty)'}; "
                    f"supported: {', '.join(_ACTIONS)}"
                ),
                is_error=True,
            )
        from lsp import manager

        if action == "status":
            return ToolResult(content=_render_status(manager.status()))

        path = str(raw.get("path") or "").strip()
        if not path:
            return ToolResult(
                content=f"path is required for action={action}", is_error=True
            )
        target = path if os.path.isabs(path) else os.path.join(self._cwd, path)
        if not os.path.exists(target):
            return ToolResult(content=f"no such file: {path}", is_error=True)

        # 参数校验先于服务器可用性：模型用法错误必须**确定性**报错，不能被
        # "没装服务器"这条 fail-open 路径吞掉（否则同一份错参数在不同机器上
        # 得到两种结论）。
        line = _as_int(raw.get("line"), 0)
        character = _as_int(raw.get("character"), 1)
        if action in _NEEDS_POSITION and line < 1:
            return ToolResult(
                content=f"line (1-based) is required for action={action}", is_error=True
            )

        language = manager.language_of(target)
        if not language:
            return ToolResult(
                content=(
                    f"no language server mapping for {os.path.splitext(path)[1] or '(no extension)'}; "
                    f"available languages: {', '.join(manager.status()['available']) or '(none)'}"
                )
            )
        client = manager.client_for(self._cwd, language)
        if client is None:
            available = manager.status()["available"]
            return ToolResult(
                content=(
                    f"no language server for {language} is installed; "
                    f"available: {', '.join(available) or '(none)'}. "
                    "Read/Grep still work."
                )
            )

        try:
            body = self._dispatch(
                manager, client, action, target, language, line, character, raw
            )
        except Exception as exc:  # noqa: BLE001 — LSP 失败一律 fail-open
            manager.drop_client(self._cwd, language)
            return ToolResult(
                content=(
                    f"language server query failed ({type(exc).__name__}: {exc}); "
                    "Read/Grep still work."
                )
            )
        return ToolResult(content=body)

    @staticmethod
    def _dispatch(
        manager: Any,
        client: Any,
        action: str,
        target: str,
        language: str,
        line: int,
        character: int,
        raw: dict[str, Any],
    ) -> str:
        if action == "diagnostics":
            client.ensure_open(target, language)
            items = client.diagnostics(target)
            rel = _relative(client.root, target)
            if not items:
                return (
                    f"{rel}: no diagnostics published yet "
                    "(the server reports them after opening and analysing the file)"
                )
            return "\n".join(item.render(rel) for item in items)

        uri = client.ensure_open(target, language)
        rel = _relative(client.root, target)

        if action == "symbols":
            lines = manager.render_symbols(
                client.document_symbols(uri), manager_root(client), rel
            )
            if not lines:
                return f"{rel}: no symbols reported"
            return "\n".join(lines)

        zero_line = max(0, line - 1)
        zero_char = max(0, character - 1)
        if action == "definition":
            found = manager.render_locations(
                client.definition(uri, zero_line, zero_char), manager_root(client)
            )
            return "\n".join(found) if found else f"{rel}:{line}: no definition found"
        if action == "references":
            include = raw.get("include_declaration")
            found = manager.render_locations(
                client.references(
                    uri,
                    zero_line,
                    zero_char,
                    include_declaration=True if include is None else bool(include),
                ),
                manager_root(client),
            )
            return "\n".join(found) if found else f"{rel}:{line}: no references found"
        if action == "hover":
            text = manager.render_hover(client.hover(uri, zero_line, zero_char))
            return text or f"{rel}:{line}: no hover information"
        return f"unsupported action: {action}"


def _relative(root: Any, target: str) -> str:
    """尽量给相对工作区的路径（模型可见面用相对路径更省 token）。"""
    try:
        from pathlib import Path

        return str(Path(target).resolve().relative_to(Path(root).resolve())).replace(
            "\\", "/"
        )
    except Exception:  # noqa: BLE001 — 不在工作区内就用文件名
        return os.path.basename(target)


def _manager_root(client: Any) -> str:
    return str(getattr(client, "root", "."))


def _render_status(payload: dict[str, Any]) -> str:
    running = payload.get("running") or []
    available = payload.get("available") or []
    return (
        f"running servers: {', '.join(running) or '(none)'}\n"
        f"available on PATH: {', '.join(available) or '(none)'}\n"
        f"max cached servers: {payload.get('max_clients')}"
    )


__all__ = ["LspTool"]
