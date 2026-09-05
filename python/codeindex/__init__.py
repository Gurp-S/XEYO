"""codeindex — 按需符号解析 + 内容哈希缓存（零持久状态）。

公开 API（计划书 33 §2.2）：
- outline(path)                       单文件符号大纲
- locate(path, "Class.method")        点号路径定位（歧义返回 None，locate_all 列候选）
- iter_symbols(paths, pattern)        多文件流式过滤（惰性，供 Grep symbols 模式）
- build_workspace_graph(cwd)          文件/架构图（import 边 + 分层折叠）

设计红线：只缓存 Symbol 元数据，绝不保留 AST / 语法树 / 源码文本；
失效校验用内容哈希（blake2b），不依赖 mtime。
"""

from codeindex.symbols import (
	Symbol,
	locate,
	locate_all,
	outline,
	iter_symbols,
	clear_cache,
)
from codeindex.graph import build_workspace_graph, clear_graph_cache, infer_layer, package_id

__all__ = [
	"Symbol",
	"outline",
	"locate",
	"locate_all",
	"iter_symbols",
	"clear_cache",
	"build_workspace_graph",
	"clear_graph_cache",
	"infer_layer",
	"package_id",
]
