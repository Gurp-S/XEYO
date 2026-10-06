"""BOM 开头的源文件必须照样进代码索引——否则"查不到"会被当成"没有"。

实测（2026-10-03，产品自己的公开入口 `codeindex.symbols.outline`）：仓库里**已提交**
四个带 UTF-8 BOM 的 .py 在索引里是**空的**：

    model/chunks.py            符号数 0     import 边 0
    model/client.py            符号数 0     import 边 0
    model/fake.py              符号数 0
    tools/echo/echo_tool.py    符号数 0
  （无 BOM 对照：codeindex/symbols.py 21 个符号、engine/budget.py 34 个）

链路：`_decode()` 用 ``decode("utf-8", errors="replace")`` ⇒ BOM 变成一个正常的
``\\ufeff`` 字符留在正文首位；`ast.parse` 对它抛
``invalid non-printable character U+FEFF``；而两个解析器都
``except SyntaxError: return ()`` ⇒ **静默变成"这个文件没有任何符号"**。
症状不是报错，是 Grep/符号视图/定义跳转对这些文件集体失明。

⇒ 反向校同样重要：不能把"剥 BOM"做成"剥首字符"，正常文件的首字符必须原样保留。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codeindex import graph, symbols

PY_HEAD = "from __future__ import annotations\n\n\ndef alpha(x):\n    return x\n\n\nclass Beta:\n    pass\n"


@pytest.fixture(autouse=True)
def _clear_caches():
	symbols.clear_cache()
	graph.clear_graph_cache()
	yield
	symbols.clear_cache()
	graph.clear_graph_cache()


def _write(root: Path, name: str, raw: bytes) -> Path:
	p = root / name
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_bytes(raw)
	return p


def test_utf8_bom_file_is_indexed(tmp_path: Path) -> None:
	"""正向：UTF-8 BOM + 源码 ⇒ 符号必须被解析出来。"""
	_write(tmp_path, "pkg/mod.py", b"\xef\xbb\xbf" + PY_HEAD.encode("utf-8"))
	target = tmp_path / "pkg" / "mod.py"
	names = [s.name for s in symbols.outline(str(target))]
	assert "alpha" in names and "Beta" in names, f"BOM 文件仍被当成空索引：{names}"
	assert all("\ufeff" not in n for n in names), f"符号名混进了 BOM 字符：{names}"


def test_utf16le_bom_file_is_indexed(tmp_path: Path) -> None:
	"""utf-16-le 分支同罪：FF FE 解出来的正文首字符就是 BOM 本身。"""
	raw = b"\xff\xfe" + PY_HEAD.encode("utf-16-le")
	target = _write(tmp_path, "u16/mod.py", raw)
	names = [s.name for s in symbols.outline(str(target))]
	assert "alpha" in names, f"utf-16-le BOM 文件索引为空：{names}"


def test_no_bom_file_first_line_untouched(tmp_path: Path) -> None:
	"""反向校：只剥 BOM，不剥首字符。"""
	target = _write(tmp_path, "plain/mod.py", PY_HEAD.encode("utf-8"))
	decoded = symbols._decode(target.read_bytes())
	assert decoded == PY_HEAD, "无 BOM 的文件正文被改了 ⇒ 行号/偏移全会错位"
	assert [s.name for s in symbols.outline(str(target))][:1] == ["alpha"]


def test_graph_import_resolution_sees_bom_file(tmp_path: Path) -> None:
	"""import 图侧同一条 bug：带 BOM 的文件解析不出任何 import ⇒ 图里没有它的边。

	测 `_imports_of`（它自己读字节 → 解码 → 解析 → 查索引，正是 BOM 失效那一段）。
	夹具两个坑都记在这：`_resolve_spec` 把**裸单段** import（`import dep`）一律当
	外部包返回 None，必须写成分段名 `pkg.dep` 才会去查工作区索引；而边本身的生成
	还另有包结构要求，所以断言只建在"同一份内容只因 BOM 就解析不同"这一点上。
	"""
	src = b"import pkg.dep\n"
	_write(tmp_path, "pkg/dep.py", b"VALUE = 1\n")
	plain = _write(tmp_path, "pkg/plain_ref.py", src)
	bom = _write(tmp_path, "pkg/bom_ref.py", b"\xef\xbb\xbf" + src)

	rels = ["pkg/dep.py", "pkg/plain_ref.py", "pkg/bom_ref.py"]
	index = graph._build_file_index(tmp_path, rels)
	control = graph._imports_of(str(plain), "pkg/plain_ref.py", index)
	got = graph._imports_of(str(bom), "pkg/bom_ref.py", index)

	assert control == ["pkg/dep.py"], f"夹具自证：无 BOM 的引用应解析出目标，实际 {control}"
	assert got == control, f"同一份内容只因前导 BOM 就解析不同：bom={got} plain={control}"


def test_committed_bom_files_are_not_invisible() -> None:
	"""钉住真实回归：仓库里带 BOM 的已提交 .py 必须在索引里非空。

	这些文件是谁造的、以后会不会去掉 BOM 都不影响本断言——去 BOM 后照样非空。
	"""
	py_root = Path(symbols.__file__).resolve().parents[1]
	targets = [
		py_root / "model" / "chunks.py",
		py_root / "model" / "client.py",
		py_root / "model" / "fake.py",
		py_root / "tools" / "echo" / "echo_tool.py",
	]
	checked = 0
	for p in targets:
		if not p.is_file():
			continue
		checked += 1
		names = [s.name for s in symbols.outline(str(p))]
		assert names, f"{os.fspath(p.relative_to(py_root))} 在代码索引里是空的"
	assert checked, "四个 BOM 文件都不在树上——本断言失去意义，请改判据"
