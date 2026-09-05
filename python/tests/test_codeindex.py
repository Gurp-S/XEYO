"""codeindex.symbols 单测（33号计划 Step 1）。

覆盖：解析正确性（py/TS）、内容哈希缓存失效、LRU 淘汰、语法错误防御、
点号定位与歧义、目录展开排除与截断。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import codeindex.symbols as sym_mod
from codeindex.symbols import (
	Symbol,
	clear_cache,
	locate,
	locate_all,
	outline,
	iter_symbols,
	_parse_ts_regex,
)


@pytest.fixture(autouse=True)
def _clean_cache():
	clear_cache()
	yield
	clear_cache()


PY_SRC = '''\
import os


def top_level(a, b=1):
	return a + b


async def async_fn():
	pass


class Widget:
	x = 1

	def __init__(self, name):
		self.name = name

	async def handle(self, req):
		return req

	class Inner:
		def deep(self):
			return 1


def top_level(a, b):
	return b
'''

PY_EXPECTED = {
	("function", "top_level", None),
	("function", "async_fn", None),
	("class", "Widget", None),
	("method", "__init__", "Widget"),
	("method", "handle", "Widget"),
	("class", "Inner", "Widget"),
	("method", "deep", "Inner"),
}


class TestOutlinePython:
	def test_symbols_and_parents(self, tmp_path: Path) -> None:
		f = tmp_path / "mod.py"
		f.write_text(PY_SRC, encoding="utf-8")
		syms = outline(str(f))
		got = {(s.kind, s.name, s.parent) for s in syms}
		assert PY_EXPECTED <= got
		# 签名与行号范围
		widget = next(s for s in syms if s.name == "Widget")
		assert widget.start == 12 and widget.end == 23
		assert widget.signature.startswith("class Widget")
		handle = next(s for s in syms if s.name == "handle")
		assert handle.start > widget.start and handle.end < widget.end

	def test_unsupported_extension(self, tmp_path: Path) -> None:
		f = tmp_path / "note.md"
		f.write_text("# not code", encoding="utf-8")
		assert outline(str(f)) == ()

	def test_missing_file(self, tmp_path: Path) -> None:
		assert outline(str(tmp_path / "nope.py")) == ()

	def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
		f = tmp_path / "bad.py"
		f.write_text("def broken(:\n", encoding="utf-8")
		assert outline(str(f)) == ()

	def test_decorator_lines_excluded_from_range(self, tmp_path: Path) -> None:
		f = tmp_path / "dec.py"
		f.write_text("@decorator\ndef fn():\n	pass\n", encoding="utf-8")
		syms = outline(str(f))
		assert len(syms) == 1 and syms[0].start == 2 and syms[0].end == 3


class TestHashCache:
	def test_content_change_invalidates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
		f = tmp_path / "m.py"
		f.write_text("def a():\n	pass\n", encoding="utf-8")
		assert len(outline(str(f))) == 1

		calls = {"n": 0}
		real = sym_mod._parse_python

		def counting(text: str):
			calls["n"] += 1
			return real(text)

		monkeypatch.setattr(sym_mod, "_parse_python", counting)

		# 内容未变 → 命中缓存，不重解析
		assert outline(str(f))[0].name == "a"
		assert calls["n"] == 0

		# 内容变化 → 重解析
		f.write_text("def a():\n	pass\n\ndef b():\n	pass\n", encoding="utf-8")
		assert len(outline(str(f))) == 2
		assert calls["n"] == 1

		# 内容改回原样 → 哈希不匹配缓存里的新内容 → 重解析一次，但结果必须正确
		#（mtime 同秒改回的场景下，基于内容的键不可能给出过期的 B 内容）
		f.write_text("def a():\n	pass\n", encoding="utf-8")
		syms = outline(str(f))
		assert len(syms) == 1 and syms[0].name == "a"
		assert calls["n"] == 2

	def test_lru_evicts_oldest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
		monkeypatch.setattr(sym_mod, "MAX_CACHED_FILES", 2)
		files = []
		for i in range(3):
			f = tmp_path / f"f{i}.py"
			f.write_text(f"def fn{i}():\n	pass\n", encoding="utf-8")
			files.append(f)

		calls = {"n": 0}
		real = sym_mod._parse_python

		def counting(text: str):
			calls["n"] += 1
			return real(text)

		monkeypatch.setattr(sym_mod, "_parse_python", counting)

		for f in files:
			outline(str(f))
		assert calls["n"] == 3
		# f0 已被淘汰（容量 2），f1/f2 仍命中
		outline(str(files[1]))
		outline(str(files[2]))
		assert calls["n"] == 3
		outline(str(files[0]))
		assert calls["n"] == 4


class TestLocate:
	@pytest.fixture()
	def py_file(self, tmp_path: Path) -> str:
		f = tmp_path / "mod.py"
		f.write_text(PY_SRC, encoding="utf-8")
		return str(f)

	def test_class_method_path(self, py_file: str) -> None:
		sym = locate(py_file, "Widget.handle")
		assert sym is not None and sym.kind == "method"

	def test_deep_chain(self, py_file: str) -> None:
		sym = locate(py_file, "Widget.Inner.deep")
		assert sym is not None and sym.parent == "Inner"

	def test_top_level_name(self, py_file: str) -> None:
		assert locate(py_file, "async_fn") is not None

	def test_ambiguous_returns_none(self, py_file: str) -> None:
		# top_level 在源码里定义了两次
		assert locate(py_file, "top_level") is None
		assert len(locate_all(py_file, "top_level")) == 2

	def test_parent_disambiguates_same_name(self, tmp_path: Path) -> None:
		f = tmp_path / "m.py"
		f.write_text(
			"class A:\n"
			"	def foo(self):\n"
			"		pass\n"
			"\n"
			"class B:\n"
			"	def foo(self):\n"
			"		pass\n",
			encoding="utf-8",
		)
		assert locate(str(f), "A.foo") is not None
		sym = locate(str(f), "B.foo")
		assert sym is not None and sym.parent == "B"
		assert locate(str(f), "C.foo") is None

	def test_unknown_symbol(self, py_file: str) -> None:
		assert locate(py_file, "NoSuch.thing") is None


class TestTsJs:
	def test_regex_fallback_declarations(self) -> None:
		src = (
			"export function alpha(a) { return a }\n"
			"\n"
			"export default class Beta {\n"
			"	handle(req) { return req }\n"
			"}\n"
			"\n"
			"interface Gamma { x: number }\n"
			"\n"
			"const delta = async (x: number): Promise<void> => {\n"
			"	await x\n"
			"}\n"
		)
		syms = _parse_ts_regex(src)
		by_name = {s.name: s for s in syms}
		assert by_name["alpha"].kind == "function"
		assert by_name["Beta"].kind == "class"
		assert by_name["Gamma"].kind == "interface"
		assert by_name["delta"].kind == "function"
		assert all(s.approximate for s in syms)
		# 缩进回推的块尾覆盖到体内容
		assert by_name["Beta"].end >= 4

	def test_outline_ts_file(self, tmp_path: Path) -> None:
		f = tmp_path / "m.ts"
		f.write_text(
			"export class Store {\n"
			"	apply(x: number): void {}\n"
			"}\n"
			"export function helper(): number { return 1 }\n",
			encoding="utf-8",
		)
		syms = outline(str(f))
		names = {s.name for s in syms}
		assert "Store" in names and "helper" in names
		if any(s.kind == "method" for s in syms):
			# tree-sitter 已安装：方法归属与行号精确
			method = next(s for s in syms if s.kind == "method")
			assert method.name == "apply" and method.parent == "Store"
			assert not method.approximate

	def test_outline_tsx_file(self, tmp_path: Path) -> None:
		f = tmp_path / "C.tsx"
		f.write_text(
			"export const C = () => {\n"
			"	return <div onClick={() => go()} />\n"
			"}\n",
			encoding="utf-8",
		)
		syms = outline(str(f))
		assert any(s.name == "C" for s in syms)


class TestIterSymbols:
	def test_walk_filter_and_exclusion(self, tmp_path: Path) -> None:
		(tmp_path / "pkg").mkdir()
		(tmp_path / "pkg" / "a.py").write_text("def wanted():\n	pass\n", encoding="utf-8")
		(tmp_path / "pkg" / "b.py").write_text("def other():\n	pass\n", encoding="utf-8")
		nm = tmp_path / "pkg" / "node_modules"
		nm.mkdir()
		(nm / "dep.js").write_text("function wanted() {}\n", encoding="utf-8")
		(tmp_path / "pkg" / "c.ts").write_text("function wanted() {}\n", encoding="utf-8")

		results = list(iter_symbols([str(tmp_path)], r"wanted"))
		paths = {os.path.normpath(p) for p, _ in results}
		assert os.path.normpath(str(tmp_path / "pkg" / "a.py")) in paths
		assert os.path.normpath(str(tmp_path / "pkg" / "c.ts")) in paths
		assert not any("node_modules" in p for p in paths)
		# 隐藏目录不进
		hidden = tmp_path / ".git"
		hidden.mkdir()
		(hidden / "h.py").write_text("def wanted():\n	pass\n", encoding="utf-8")
		assert not any(".git" in p for p, _ in iter_symbols([str(tmp_path)], "wanted"))

	def test_max_symbols_truncates(self, tmp_path: Path) -> None:
		for i in range(10):
			(tmp_path / f"f{i}.py").write_text(f"def sym{i}():\n	pass\n", encoding="utf-8")
		results = list(iter_symbols([str(tmp_path)], r"sym\d", max_symbols=3))
		assert len(results) == 3

	def test_bad_pattern_falls_back_to_literal(self, tmp_path: Path) -> None:
		# 坏正则不崩：回退为字面量匹配（标识符里不可能含 "("，故结果为空而非异常）
		f = tmp_path / "x.py"
		f.write_text("def a_b():\n	pass\n", encoding="utf-8")
		assert list(iter_symbols([str(f)], "a(b")) == []
		# 合法正则路径不受影响
		assert len(list(iter_symbols([str(f)], "a_b"))) == 1

	def test_ignore_case_flag(self, tmp_path: Path) -> None:
		f = tmp_path / "x.py"
		f.write_text("def ABC():\n	pass\n", encoding="utf-8")
		assert len(list(iter_symbols([str(f)], "abc", ignore_case=True))) == 1
		assert len(list(iter_symbols([str(f)], "abc", ignore_case=False))) == 0


class TestSymbolDataclass:
	def test_frozen(self) -> None:
		s = Symbol(kind="function", name="f", start=1, end=2, parent=None, signature="def f()")
		with pytest.raises(Exception):
			s.name = "g"  # type: ignore[misc]
