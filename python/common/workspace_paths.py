"""Workspace-contained path resolution shared by Git and HTTP files."""
from pathlib import Path


def resolve_in_workspace(cwd: str, rel: str) -> Path:
	root = Path(cwd).expanduser().resolve()
	if not root.is_dir():
		raise FileNotFoundError(f"workspace not found: {root}")
	raw = (rel or "").strip().replace("\\", "/")
	if raw in ("", ".", "/"):
		return root
	candidate = Path(raw)
	try:
		target = candidate.resolve() if candidate.is_absolute() else (root / raw).resolve()
	except (OSError, ValueError) as exc:
		# NUL / \n / \x1a 这类字符会让 resolve() 底层 stat 直接抛 ValueError。
		# 这里是所有调用方（HTTP 路由、git diff、outline 等）的必经点：向外抛
		# 出去就是每个入口一个 500，而"这个路径没法解析"本身是个拒绝事实。
		raise PermissionError("path cannot be resolved") from exc
	try:
		target.relative_to(root)
	except ValueError as e:
		raise PermissionError("path outside workspace") from e
	return target
