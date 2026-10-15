"""LSP 接入层（旁路能力，默认关：``XEYO_LSP``）。

只覆盖文本搜索给不了的那几件事：定义跳转、引用查找、悬停签名、文档符号、
服务器诊断。找不到服务器时一律 **fail-open**（返回中性事实，回退到
Read / Grep / 符号浏览），绝不报"没有定义"这种假阴。
"""

from lsp.client import Diagnostic, LspClient, LspError
from lsp.manager import (
    client_for,
    drop_client,
    language_of,
    render_hover,
    render_locations,
    render_symbols,
    running_languages,
    shutdown_all,
    status,
)
from lsp.servers import available_languages, find_server, language_for_path

__all__ = [
    "Diagnostic",
    "LspClient",
    "LspError",
    "available_languages",
    "client_for",
    "drop_client",
    "find_server",
    "language_for_path",
    "language_of",
    "render_hover",
    "render_locations",
    "render_symbols",
    "running_languages",
    "shutdown_all",
    "status",
]
