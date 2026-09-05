"""P0 自检预览：打印指定工作区的 Memory index T_now 块（一行化 + 围栏后）。

用法（无需运行 server / 引擎，只读 ~/.xeyo/memory）：
    py -3.11 scripts/preview_memory_index_block.py [workspace_path]

不传参时默认取当前目录作为工作区。配合仓库根目录 check-memory-index-p0.bat 使用。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.memdir import load_index_text, workspace_id  # noqa: E402
from memory.runtime import _memory_index_block  # noqa: E402


def main() -> int:
	root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
	wsid = workspace_id(str(root))
	raw = load_index_text(wsid) or ""
	entry_lines = [
		line
		for line in raw.splitlines()
		if line.strip() and not line.strip().startswith("#")
	]
	block = _memory_index_block(raw)
	print(f"workspace     = {root}")
	print(f"workspace_id  = {wsid}")
	print(f"MEMORY.md     = {len(entry_lines)} entries, {len(raw)} chars")
	print("---- T_now Memory index block (what the model sees) ----")
	print(block if block else "(no entries -> block omitted this turn)")
	print("---- end ----")
	print(f"block chars   = {len(block)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
