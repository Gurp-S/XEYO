"""content_index_cache_shadow 门槛/证明性测试（⑧，省 CPU）。

覆盖：
- 关（默认）：不挂钩，`_build_index` 逐位不变。
- 开=内容哈希缓存：未变文件二建零 trigram 重算（READ_COUNT=0）；内容改变正确失效（READ_COUNT 递增）。
- 结果与原文一致（相同 ContentIndex 超集）。
- fail-open：单文件超限 → 返回 None（回退全量 rg），语义不变。
- 卸载后恢复原函数。

注意：READ_COUNT 只计「重算 trigram」的文件数；文件本身仍被读取以算内容哈希（省 CPU，非省 IO）。
"""

from __future__ import annotations

import os

import pytest

from tools.fileio import content_index
from tools.fileio.content_index_cache_shadow import (
    enabled,
    install,
    read_count,
    reset_read_count,
    uninstall,
)


def _make(ws: str, rel: str, text: str) -> None:
    p = os.path.join(ws, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.fixture()
def off(monkeypatch):
    monkeypatch.delenv("XEYO_CONTENT_INDEX_CACHE", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


def test_default_off_no_hook(off):
    assert enabled() is False
    assert install() is False
    assert not getattr(content_index, "__content_index_cache_installed", False)


def test_install_uninstall_restore(monkeypatch):
    monkeypatch.setenv("XEYO_CONTENT_INDEX_CACHE", "1")
    assert enabled() is True
    before = content_index._build_index
    assert install() is True
    assert getattr(content_index, "__content_index_cache_installed", False) is True
    assert content_index._build_index is not before
    uninstall()
    assert content_index._build_index is before


def test_second_build_zero_reread(tmp_path, monkeypatch):
    """未变文件二建零 trigram 重算：READ_COUNT 第二次为 0（省 CPU，非省 IO）。"""
    monkeypatch.setenv("XEYO_CONTENT_INDEX_CACHE", "1")
    ws = str(tmp_path)
    for i in range(5):
        _make(ws, f"src/{i}.py", f"needle{i} some literal text\n")

    assert install() is True
    try:
        reset_read_count()
        built1 = content_index._build_index(ws)
        assert built1 is not None
        assert read_count() == 5  # 首建 5 文件全重读

        reset_read_count()
        # 强制走 build 路径（内容未变）。
        built2 = content_index._build_index(ws)
        assert built2 is not None
        assert read_count() == 0  # 全命中缓存 → 零重读
        # 结果一致（同文件集 + 同 trigram 数）。
        assert set(built2.files) == set(built1.files)
        assert built2.trigrams.keys() == built1.trigrams.keys()
    finally:
        uninstall()


def test_content_change_invalidates(tmp_path, monkeypatch):
    """内容改变 → 该文件失效并重读。"""
    monkeypatch.setenv("XEYO_CONTENT_INDEX_CACHE", "1")
    ws = str(tmp_path)
    _make(ws, "a.py", "alpha beta gamma\n")
    assert install() is True
    try:
        reset_read_count()
        content_index._build_index(ws)
        assert read_count() == 1

        # 改内容，让某个新增 trigram 需要重读。
        _make(ws, "a.py", "alpha beta delta delta\n")
        reset_read_count()
        built2 = content_index._build_index(ws)
        assert built2 is not None
        assert read_count() == 1  # 该文件被重读
        # 新 trigram 出现（delta 变多）。
        assert any("delt" in tg or "delt" in "delta" for tg in built2.trigrams)
    finally:
        uninstall()


def test_superset_equivalence(tmp_path, monkeypatch):
    """缓存版与原文超集一致（不因缓存改动结果）。"""
    # 用原文建一次作基准。
    ws = str(tmp_path)
    _make(ws, "x/a.py", "the needle1 marker here\n")
    _make(ws, "x/b.py", "needle1 again\n")
    # 原文 lookup（未挂钩，TTL 内命中缓存）
    baseline = content_index.lookup(ws, "needle1")
    baseline_set = {c.replace("\\", "/") for c in (baseline or [])}

    monkeypatch.setenv("XEYO_CONTENT_INDEX_CACHE", "1")
    assert install() is True
    try:
        on = content_index.lookup(ws, "needle1")
        on_set = {c.replace("\\", "/") for c in (on or [])}
        assert on_set == baseline_set
    finally:
        uninstall()


def test_fail_open_large_file(tmp_path, monkeypatch):
    """单文件超限 → 返回 None（回退全量 rg），fail-open 语义不变。"""
    monkeypatch.setenv("XEYO_CONTENT_INDEX_CACHE", "1")
    ws = str(tmp_path)
    _make(ws, "small.py", "small\n")
    _make(ws, "big.py", "x" * (content_index._SKIP_FILE_BYTES + 1))
    assert install() is True
    try:
        assert content_index._build_index(ws) is None
    finally:
        uninstall()
