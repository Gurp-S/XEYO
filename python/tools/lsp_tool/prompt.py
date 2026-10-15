"""Lsp 工具文案。事实型：只列动作与参数，不给使用建议。"""

LSP_TOOL_NAME = "Lsp"

DESCRIPTION = (
    "Language server queries for one file: definition, references, hover, "
    "document symbols, and server diagnostics. Requires a language server on "
    "PATH (pyright/pylsp, typescript-language-server, gopls, clangd, ...); when "
    "none is available the result states that instead of reporting an empty "
    "answer. line/character are 1-based; character defaults to 1."
)

SHORT_DESCRIPTION = (
    "Language server: definition/references/hover/symbols/diagnostics "
    "(fails open when no server is installed)."
)
