"""内容索引（字面量 trigram）单测：build / lookup / 超集 / 上限回退。"""

from __future__ import annotations

import os

import pytest

from tools.fileio import content_index


def _make(ws: str, rel: str, text: str) -> None:
	p = os.path.join(ws, rel)
	os.makedirs(os.path.dirname(p), exist_ok=True)
	with open(p, "w", encoding="utf-8") as f:
		f.write(text)


def test_is_literal_boundaries() -> None:
	assert content_index.is_literal("alpha")
	assert content_index.is_literal("some_func_name")
	assert not content_index.is_literal("alpha.py")
	assert not content_index.is_literal("a.*b")
	assert not content_index.is_literal("a.b")
	assert not content_index.is_literal("ab")
	assert not content_index.is_literal("")
	assert not content_index.is_literal("with space")


def test_lookup_returns_superset(tmp_path) -> None:
	ws = str(tmp_path)
	_make(ws, "src/a.py", "the needle1 marker here\n")
	_make(ws, "src/b.txt", "nothing at all\n")
	_make(ws, "sub/c.rs", "needle1 again\n")
	_make(ws, "other/D.txt", "needle1 too\n")

	cands = content_index.lookup(ws, "needle1")
	assert cands is not None
	norm = {c.replace("\\", "/") for c in cands}
	# 超集：三个含 needle1 的文件必在；不带无关文件。
	assert "src/a.py".replace("/", "/") in {x.lstrip("./") for x in norm}
	assert {x.lstrip("./") for x in norm} == {"src/a.py", "sub/c.rs", "other/D.txt"}
	# 库里不存在的 trigram → 零候选
	assert content_index.lookup(ws, "zzzzzz") == []


def test_bailout_on_large_file(tmp_path) -> None:
	ws = str(tmp_path)
	_make(ws, "a.py", "small\n")
	# 超单文件上限 → 放弃建索引（保超集完整），回退全量 rg。
	_make(ws, "big.py", "x" * (content_index._SKIP_FILE_BYTES + 1))
	assert content_index.lookup(ws, "small") is None


def test_bailout_on_too_many_files(tmp_path, monkeypatch) -> None:
	ws = str(tmp_path)
	monkeypatch.setattr(content_index, "_MAX_INDEXED_FILES", 2)
	for i in range(3):
		_make(ws, f"f{i}.py", "hello world\n")
	assert content_index.lookup(ws, "hello") is None


def test_lookup_cached(tmp_path) -> None:
	ws = str(tmp_path)
	_make(ws, "a.py", "alpha beta gamma\n")
	assert content_index.lookup(ws, "alpha") is not None
	# 不触发建索引重建：命中缓存路径仍正常返回候选。
	assert content_index.lookup(ws, "beta") is not None
