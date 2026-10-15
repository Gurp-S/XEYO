"""语言服务器客户端缓存与结果渲染（fail-open）。

纪律（与 ``XEYO.md`` 的索引类改动一致）：**任何失败都不得变成假阴**。
- 找不到服务器 → 返回 ``None``，由工具层给出中性事实（"LSP 不可用"），
  而不是"没有定义/没有引用"。
- 启动/请求失败 → 关掉该 client 并从缓存移除，下次调用重新尝试；
  调用方拿到中性事实。

缓存键 = ``(workspace_root, language)``，容量有上限（LSP 服务器进程重，不做无界缓存）。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from lsp.client import LspClient, LspError
from lsp.servers import ServerSpec, available_languages, find_server, language_for_path

_log = logging.getLogger(__name__)

#: 同时保留的服务器进程上限（超出按最旧淘汰）。
MAX_CLIENTS = 4

_clients: dict[tuple[str, str], LspClient] = {}
_order: list[tuple[str, str]] = []
_lock = threading.Lock()


def client_for(
    root: str | Path, language: str, *, timeout: float | None = None
) -> LspClient | None:
    """取（必要时启动）该工作区 + 语言的客户端；不可用返回 None。"""
    lang = str(language or "").strip().lower()
    if not lang:
        return None
    spec: ServerSpec | None = find_server(lang)
    if spec is None:
        return None
    resolved = str(Path(root).resolve())
    key = (resolved, lang)
    with _lock:
        existing = _clients.get(key)
    if existing is not None:
        return existing

    client = LspClient(spec, resolved, timeout=timeout or 20.0)
    try:
        client.start()
    except (LspError, OSError) as exc:
        _log.info("lsp server unavailable (%s): %s", spec.label, exc)
        try:
            client.stop()
        except Exception:  # noqa: BLE001
            pass
        return None
    with _lock:
        _clients[key] = client
        _order.append(key)
        while len(_order) > MAX_CLIENTS:
            evicted = _order.pop(0)
            victim = _clients.pop(evicted, None)
            if victim is not None:
                try:
                    victim.stop()
                except Exception:  # noqa: BLE001
                    pass
    return client


def drop_client(root: str | Path, language: str) -> None:
    """请求失败后主动丢弃，下次调用重建（避免一直用坏连接）。"""
    key = (str(Path(root).resolve()), str(language or "").strip().lower())
    with _lock:
        client = _clients.pop(key, None)
        if key in _order:
            _order.remove(key)
    if client is not None:
        try:
            client.stop()
        except Exception:  # noqa: BLE001
            pass


def shutdown_all() -> None:
    with _lock:
        clients = list(_clients.values())
        _clients.clear()
        _order.clear()
    for client in clients:
        try:
            client.stop()
        except Exception:  # noqa: BLE001
            pass


def running_languages() -> list[str]:
    with _lock:
        return sorted({lang for _, lang in _clients})


def status() -> dict[str, Any]:
    """机器可读状态（供 Lsp(status) 与诊断）。"""
    return {
        "running": running_languages(),
        "available": available_languages(),
        "max_clients": MAX_CLIENTS,
    }


def language_of(path: str) -> str:
    return language_for_path(path)


# -- 结果渲染（LSP 的三种返回形状都要认）--------------------------------------


def _path_from_uri(uri: str, root: str | Path) -> str:
    """uri → 相对工作区路径（不在工作区内则原样返回绝对路径）。"""
    try:
        parsed = urlparse(str(uri))
        raw = unquote(parsed.path or "")
    except Exception:  # noqa: BLE001
        return str(uri)
    if not raw:
        return str(uri)
    # Windows 上 file:///d:/x 的 path 是 /d:/x，需要剥掉前导斜杠。
    if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    candidate = Path(raw)
    base = Path(root).resolve()
    try:
        return str(candidate.resolve().relative_to(base)).replace("\\", "/")
    except (ValueError, OSError):
        return str(candidate)


def render_locations(result: Any, root: str | Path) -> list[str]:
    """definition / references 的返回 → ``path:line:col`` 文本行。

    认三种形状：``Location`` / ``Location[]`` / ``LocationLink[]``（后者用
    ``targetUri`` / ``targetSelectionRange``）。
    """
    if result is None:
        return []
    items = result if isinstance(result, list) else [result]
    out: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("targetUri") or ""
        if not uri:
            continue
        rng = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange") or {}
        start = rng.get("start") if isinstance(rng, dict) else None
        line = int((start or {}).get("line") or 0)
        char = int((start or {}).get("character") or 0)
        out.append(f"{_path_from_uri(str(uri), root)}:{line + 1}:{char + 1}")
    return out


def render_hover(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents")
    if isinstance(contents, str):
        return contents.strip()
    if isinstance(contents, dict):
        return str(contents.get("value") or "").strip()
    if isinstance(contents, list):
        parts: list[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("value") or ""))
        return "\n".join(p for p in parts if p).strip()
    return ""


def render_symbols(result: Any, root: str | Path, path: str) -> list[str]:
    """documentSymbol（含层级 DocumentSymbol 与扁平 SymbolInformation 两种）。"""
    if not isinstance(result, list):
        return []
    out: list[str] = []

    def walk(nodes: list[Any], depth: int) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name") or "")
            rng = node.get("selectionRange") or node.get("range") or {}
            start = rng.get("start") if isinstance(rng, dict) else {}
            line = int((start or {}).get("line") or 0)
            kind = int(node.get("kind") or 0)
            out.append(f"{'  ' * depth}{name} (kind={kind}) {path}:{line + 1}")
            children = node.get("children")
            if isinstance(children, list):
                walk(children, depth + 1)

    walk(result, 0)
    return out


__all__ = [
    "MAX_CLIENTS",
    "client_for",
    "drop_client",
    "language_of",
    "render_hover",
    "render_locations",
    "render_symbols",
    "running_languages",
    "shutdown_all",
    "status",
]
