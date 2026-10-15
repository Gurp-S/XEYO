"""语言服务器发现：文件后缀 → 候选命令，PATH 探测，env 覆盖。

设计取向：**只做发现，不做安装**。找不到服务器时返回 ``None``，由上层 fail-open
（回退到 Read / Grep / 符号浏览）——与 ``XEYO.md`` 里「索引类改动必须 fail-open」
同一条纪律：不假阴、不假装能力存在。

env 覆盖（运维/测试用）：``XEYO_LSP_SERVER_<LANG>``，值形如
``pyright-langserver --stdio``（空格分隔的命令行）。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

#: 语言标识（LSP languageId + 我们内部的键）。
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".mts": "typescript",
    ".cts": "typescript",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".json": "json",
    ".jsonc": "jsonc",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shellscript",
    ".bash": "shellscript",
}

#: 语言 → 候选服务器命令行（按优先级）。命令不存在则试下一个。
CANDIDATES: dict[str, tuple[tuple[str, ...], ...]] = {
    "python": (
        ("pyright-langserver", "--stdio"),
        ("basedpyright-langserver", "--stdio"),
        ("pylsp",),
        ("python", "-m", "pylsp"),
    ),
    "typescript": (("typescript-language-server", "--stdio"),),
    "typescriptreact": (("typescript-language-server", "--stdio"),),
    "javascript": (("typescript-language-server", "--stdio"),),
    "javascriptreact": (("typescript-language-server", "--stdio"),),
    "go": (("gopls",),),
    "rust": (("rust-analyzer",),),
    "c": (("clangd",),),
    "cpp": (("clangd",),),
    "java": (("jdtls",),),
    "json": (
        ("vscode-json-language-server", "--stdio"),
        ("vscode-json-languageserver", "--stdio"),
    ),
    "jsonc": (
        ("vscode-json-language-server", "--stdio"),
        ("vscode-json-languageserver", "--stdio"),
    ),
    "yaml": (("yaml-language-server", "--stdio"),),
    "shellscript": (("bash-language-server", "start"),),
}


@dataclass(frozen=True)
class ServerSpec:
    """一个可用的语言服务器。"""

    language: str
    command: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return " ".join(self.command)


def language_for_path(path: str) -> str:
    """按后缀判定语言标识；未知返回空串。"""
    _, suffix = os.path.splitext(str(path or "").lower())
    return LANGUAGE_BY_SUFFIX.get(suffix, "")


def _env_override(language: str) -> tuple[str, ...] | None:
    raw = os.environ.get(f"XEYO_LSP_SERVER_{language.upper()}", "").strip()
    if not raw:
        return None
    parts = tuple(p for p in raw.split(" ") if p)
    return parts or None


def _resolvable(command: tuple[str, ...]) -> bool:
    """命令的首个 token 能否在 PATH 上解析（``python -m x`` 形式看 python）。"""
    if not command:
        return False
    return shutil.which(command[0]) is not None


def find_server(language: str) -> ServerSpec | None:
    """为该语言找一个可用服务器；找不到返回 None（调用方 fail-open）。"""
    lang = str(language or "").strip().lower()
    if not lang:
        return None
    override = _env_override(lang)
    if override is not None:
        return ServerSpec(language=lang, command=override)
    for candidate in CANDIDATES.get(lang, ()):
        if _resolvable(candidate):
            return ServerSpec(language=lang, command=candidate)
    return None


def available_languages() -> list[str]:
    """当前 PATH 上真的能起的语言（用于 status 与失败时的中性事实）。"""
    return sorted(lang for lang in CANDIDATES if find_server(lang) is not None)


__all__ = [
    "CANDIDATES",
    "LANGUAGE_BY_SUFFIX",
    "ServerSpec",
    "available_languages",
    "find_server",
    "language_for_path",
]
