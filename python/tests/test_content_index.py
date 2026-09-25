"""内容索引（字面量 trigram）单测：build / lookup / 超集 / 上限回退。"""

from __future__ import annotations

import os
import time


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


class _CountingBuild:
	"""数 `_build_index` 的真实调用次数——缓存是否生效只能这么看。"""

	def __init__(self) -> None:
		self.real = content_index._build_index
		self.calls: list[str] = []

	def __enter__(self) -> "_CountingBuild":
		def spy(root: str):
			self.calls.append(root)
			return self.real(root)

		content_index._build_index = spy
		content_index.clear_content_index()
		return self

	def __exit__(self, *exc) -> None:
		content_index._build_index = self.real
		content_index.clear_content_index()


def test_failed_build_is_cached_for_the_ttl(tmp_path) -> None:
	"""建不起来也必须只建一次。

	`_get_or_build` 早先要求 `item[1] is not None` 才算命中，缓存里的 None 从不
	短路：2026-09-25 实测 python/ 根（一个 2.1MB 文件就让整根放弃建索引）每次
	字面量 Grep 都重跑列文件+读全文+算 trigram，1556ms，然后照样落回 38ms 的全量
	rg —— 一个"加速"机制在最常用的根上变成永久 20× 税负。
	"""
	ws = str(tmp_path)
	_make(ws, "big.py", "x" * (content_index._SKIP_FILE_BYTES + 1))
	with _CountingBuild() as spy:
		assert content_index.lookup(ws, "small") is None
		assert content_index.lookup(ws, "other") is None
		assert content_index.lookup(ws, "third") is None
		assert spy.calls == [ws], spy.calls
		# 压的是 TTL，不是永久——否则"这次建不起来"会一直不说话。
		exp, cached = content_index._cache[ws]
		assert cached is None
		assert 0.0 < exp - time.monotonic() <= content_index._TTL_S


def test_negative_cache_expires(tmp_path) -> None:
	"""负缓存只压 TTL，过期后必须允许重试（目录可能已经变了）。"""
	ws = str(tmp_path)
	_make(ws, "big.py", "x" * (content_index._SKIP_FILE_BYTES + 1))
	with _CountingBuild() as spy:
		assert content_index.lookup(ws, "small") is None
		# 把这条负缓存的到期时间挪到过去，不去跟 monotonic 的时钟粒度较劲。
		content_index._cache[ws] = (time.monotonic() - 1.0, None)
		assert content_index.lookup(ws, "small") is None
		assert len(spy.calls) == 2, spy.calls


def test_successful_build_is_cached(tmp_path) -> None:
	ws = str(tmp_path)
	_make(ws, "a.py", "alpha beta gamma\n")
	with _CountingBuild() as spy:
		assert content_index.lookup(ws, "alpha") is not None
		assert content_index.lookup(ws, "beta") is not None
		assert spy.calls == [ws], spy.calls

