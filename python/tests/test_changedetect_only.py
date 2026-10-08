"""`--only` 按名重钉（#11 / G1）：不删未命中、index 合并、零命中报错。

背景：两个 `write_golden` 原先都是"全量重写 + unlink 未命中"，于是"重钉我的 3 条"
必然把别人在途的 6 条一起钉成新基线 ⇒ 只能二选一（卷别人 / 放弃重钉）。
本文件的四件事钉住 `only` 档的边界：**只动点名项、其余一律不碰、空匹配不许当成功**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.changedetect import surface, trace


def _art(name: str, text: str) -> surface.Artifact:
	return surface.Artifact(name=name, text=text, group=name.split("/")[0])


def _index(tmp_path: Path) -> dict:
	return json.loads((tmp_path / "surface_index.json").read_text(encoding="utf-8"))


def test_only_rewrites_hits_and_keeps_the_rest(tmp_path: Path) -> None:
	"""命中项重钉；未命中项的**文件字节不动**，未点名的新 artifact 不写。"""
	surface.write_golden([_art("tnow/registry", "a"), _art("tnow/hard_cap", "b")],
	                     directory=tmp_path)
	before = (tmp_path / "surface" / "tnow__hard_cap.txt").read_bytes()

	surface.write_golden(
		[_art("tnow/registry", "a2"), _art("tnow/hard_cap", "b"), _art("tools/Bash", "c")],
		directory=tmp_path,
		only=["tnow__registry"],
	)

	assert (tmp_path / "surface" / "tnow__registry.txt").read_text(encoding="utf-8") == \
		_art("tnow/registry", "a2").canonical
	assert (tmp_path / "surface" / "tnow__hard_cap.txt").read_bytes() == before
	assert not (tmp_path / "surface" / "tools__Bash.txt").exists()


def test_only_merges_index_without_dropping_others(tmp_path: Path) -> None:
	"""index 合并：未命中项条目原样保留，命中项更新，count 仍是总数。"""
	surface.write_golden([_art("tnow/registry", "a"), _art("tools/Bash", "c")],
	                     directory=tmp_path)
	old = _index(tmp_path)

	surface.write_golden([_art("tnow/registry", "a2"), _art("tools/Bash", "c")],
	                     directory=tmp_path, only=["tnow/*"])
	new = _index(tmp_path)

	assert new["artifacts"]["tools/Bash"] == old["artifacts"]["tools/Bash"]
	assert new["artifacts"]["tnow/registry"] != old["artifacts"]["tnow/registry"]
	assert new["artifact_count"] == 2


def test_only_with_no_hit_raises(tmp_path: Path) -> None:
	"""零命中 ⇒ 报错。静默当成功就是假阴：以为钉了，其实什么都没动。"""
	surface.write_golden([_art("tnow/registry", "a")], directory=tmp_path)
	with pytest.raises(ValueError):
		surface.write_golden([_art("tnow/registry", "a")], directory=tmp_path,
		                     only=["nope/*"])


def test_full_rewrite_still_cleans_stale(tmp_path: Path) -> None:
	"""正控：`only` 为空时行为与改动前一致——全量写 + 删 stale。"""
	surface.write_golden([_art("tnow/registry", "a"), _art("tools/Bash", "c")],
	                     directory=tmp_path)
	surface.write_golden([_art("tnow/registry", "a")], directory=tmp_path)
	assert not (tmp_path / "surface" / "tools__Bash.txt").exists()
	assert set(_index(tmp_path)["artifacts"]) == {"tnow/registry"}


def test_trace_only_keeps_unmatched_file(tmp_path: Path) -> None:
	"""L1 同口径：只重钉命中轨迹，未命中文件保持存在；零命中报错。"""
	trace.write_golden({"a": "1", "b": "2"}, directory=tmp_path)
	trace.write_golden({"a": "9"}, directory=tmp_path, only=["a"])
	assert (tmp_path / "trace" / "b.txt").exists()
	assert (tmp_path / "trace" / "a.txt").read_text(encoding="utf-8") == \
		trace.canon.canon_text("9")
	with pytest.raises(ValueError):
		trace.write_golden({"a": "9"}, directory=tmp_path, only=["zzz"])
