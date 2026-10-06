"""spill 保留期清理的作用域门（数据丢失类缺陷的回归锁）。

缺陷：``_prune_old`` 原来按"目录里任何超过保留期的文件"删除，而
``spill_root()`` 是可被 ``XEYO_SPILL_DIR`` 指到任何地方的。实测把变量指到
``~/.xeyo``（用户会自然地把"spill 放哪"理解成 xeyo 根目录）后，第一次
``save_text`` 就把 40 天前的 ``usage/ledger.jsonl`` 与 ``memory/MEMORY.md``
删掉了 —— 引擎在没有任何提示的情况下吃掉用户的会话账本与记忆。

修法：清理只认 ``save_text`` 自己的产物名。

本文件双向都钉：
- 正向：非产物名必须**不被删**（缺陷回归）；
- 反向：产物名必须**照旧被删**（防止把修法改成"干脆不删"，那会让保留期机制
  静默失效、盘上无限膨胀）。
"""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path

import pytest

import tools.spill as spill_mod
from tools.spill import _SPILL_NAME, save_text

PAST = 40 * 86400.0


@pytest.fixture()
def spill_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
	root = tmp_path / "xeyo_home"
	root.mkdir()
	monkeypatch.setenv("XEYO_SPILL_DIR", str(root))
	monkeypatch.delenv("XEYO_SPILL_RETENTION_DAYS", raising=False)
	return root


def _age_days(path: Path, days: float = 40.0) -> Path:
	past = time.time() - days * 86400.0
	os.utime(path, (past, past))
	return path


def _sibling_data(root: Path) -> list[Path]:
	"""模拟"清理根目录被指到 xeyo 数据根"时同树里的真实用户数据。"""
	kept: list[Path] = []
	for rel in (
		"sessions/20260101/session.jsonl",
		"usage/ledger.jsonl",
		"memory/MEMORY.md",
		"journal/2026-01-01.jsonl",
		"audit/audit.jsonl",
	):
		p = root / rel
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text("user data", encoding="utf-8")
		kept.append(_age_days(p))
	return kept


def test_non_spill_files_under_the_root_survive(spill_at: Path) -> None:
	"""缺陷回归：用户数据不得被保留期清理带走。"""
	kept = _sibling_data(spill_at)
	save_text("s1", "evidence")
	for p in kept:
		assert p.is_file(), f"prune deleted non-spill file: {p}"
		assert p.read_text(encoding="utf-8") == "user data"


def test_real_spill_files_are_still_pruned(spill_at: Path) -> None:
	"""反向：产物名照旧清理，修法不许把保留期改成"永不删"。"""
	ref = save_text("s1", "old evidence")
	old = Path(ref.path)
	assert _SPILL_NAME.match(old.name), old.name
	_age_days(old)
	fresh = save_text("s1", "new evidence")
	assert not old.exists(), "旧 spill 仍应被清理"
	assert Path(fresh.path).is_file()


def test_prune_reaches_nested_session_namespaces(spill_at: Path) -> None:
	"""清理是递归的：产物名散在会话子目录里也必须被删（否则改动只是把漏洞换成泄漏）。"""
	nested = spill_at / "sess_old" / "deeper"
	nested.mkdir(parents=True)
	dead = nested / "20260101-000000-dead0001.txt"
	dead.write_text("old evidence", encoding="utf-8")
	_age_days(dead)
	alive = nested / "20260101-000000-dead0002.txt"
	alive.write_text("keep", encoding="utf-8")
	save_text("s1", "trigger")
	assert not dead.exists()
	assert alive.is_file()


def test_name_guard_covers_what_save_text_actually_writes(spill_at: Path) -> None:
	"""双向门的另一半：``save_text`` 的产物名必须被守卫认出。

	若以后有人改文件名格式而忘了改 ``_SPILL_NAME``，清理会**静默失效**
	（盘上无限膨胀，且没有任何测试变红）——这条把它钉住。
	"""
	names = [Path(save_text(f"s{i}", "x" * 16).path).name for i in range(4)]
	for n in names:
		assert _SPILL_NAME.match(n), n


@pytest.mark.parametrize(
	"look_alike",
	[
		"MEMORY.md",
		"ledger.jsonl",
		"20260101-000000-notes.txt",
		"20260101-000000-deadbeef.txt.bak",
		"20260101-000000-DEADBEEF.txt",  # 大写十六进制不是本模块的产物
		"20260101000000-deadbeef.txt",
		"notes.txt",
	],
)
def test_look_alikes_are_never_unlinked(spill_at: Path, look_alike: str) -> None:
	"""守卫是逐名判定：近似名一律不动，哪怕它们真的老了 40 天。"""
	p = spill_at / "s1" / look_alike
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text("do not touch", encoding="utf-8")
	_age_days(p)
	save_text("s1", "trigger")
	assert p.is_file(), look_alike


def test_prune_predicate_is_applied_before_unlink() -> None:
	"""结构门：删除必须发生在名字判定之后（顺序反了就等于没有守卫）。"""
	src = Path(spill_mod.__file__).read_text(encoding="utf-8")
	tree = ast.parse(src)
	fn = next(
		n for n in tree.body
		if isinstance(n, ast.FunctionDef) and n.name == "_prune_old"
	)
	lines = src.splitlines()
	unlink_at = [
		n.lineno
		for n in ast.walk(fn)
		if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "unlink"
	]
	assert unlink_at, "_prune_old 里应当存在删除动作"
	guard_at = [
		i + 1
		for i, line in enumerate(lines)
		if "_SPILL_NAME.match" in line
	]
	assert guard_at, "_prune_old 必须有名字守卫"
	assert min(guard_at) < max(unlink_at), (guard_at, unlink_at)
