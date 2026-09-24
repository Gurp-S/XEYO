"""manifest 的不变量：单变量闸门、只写一次、易变字段不得混进可比面。"""

from __future__ import annotations

from pathlib import Path

import pytest

from diagnostics import store
from diagnostics.experiments import manifest as mf


def _context(**over: object) -> dict[str, object]:
	base: dict[str, object] = {
		"code": {"commit": "abc123", "worktree_state": "clean", "probed_at": 1.0},
		"runtime": {"name": "product-local", "profile_id": "p1"},
		"tools": {"hash": "sha:1", "count": 3},
		"permissions": {"permission_mode": "workspace-write"},
		"workspace": {"snapshot_commit": "s1", "probed_at": 2.0, "file_count": 5},
		"history": {"history_digest": "h1", "message_count": 2},
		"model": {"provider": "deepseek", "model": "m", "params": {"temperature": 0.3}, "captured_at": 3.0},
		"verifier": {"name": "pytest", "command": "py -3.11 -m pytest"},
		"budget": mf.budget_section(cap_cny=1.0, price={"status": "ok", "currency": "CNY"}),
	}
	base.update(over)
	return base


def test_flatten_expands_lists_and_mappings() -> None:
	flat = mf.flatten({"a": {"b": 1}, "tools": [{"name": "Read"}, {"name": "Write"}]})
	assert flat == {"a.b": 1, "tools.0.name": "Read", "tools.1.name": "Write"}


def test_compare_arms_accepts_exactly_one_declared_difference() -> None:
	arms = {
		"A": {"blocks": {"compact": "old"}, "model": "m"},
		"B": {"blocks": {"compact": "new"}, "model": "m"},
	}
	out = mf.compare_arms(arms, allowed_differences=["blocks.compact"])
	assert out["ok"] is True
	assert out["differences"] == ["blocks.compact"]
	assert out["undeclared"] == []


def test_compare_arms_rejects_second_differing_variable() -> None:
	arms = {
		"A": {"blocks": {"compact": "old"}, "params": {"temperature": 0.3}},
		"B": {"blocks": {"compact": "new"}, "params": {"temperature": 0.9}},
	}
	out = mf.compare_arms(arms, allowed_differences=["blocks.compact"])
	assert out["ok"] is False
	codes = [r["code"] for r in out["reasons"]]
	assert "single_variable_violation" in codes
	assert out["undeclared"][0]["path"] == "params.temperature"


def test_compare_arms_rejects_declared_path_that_did_not_change() -> None:
	arms = {"A": {"blocks": {"x": "1"}}, "B": {"blocks": {"x": "1"}}}
	out = mf.compare_arms(arms, allowed_differences=["blocks.y"])
	assert out["ok"] is False
	assert "no_difference" in [r["code"] for r in out["reasons"]]
	assert out["declared_but_identical"] == ["blocks.y"]


def test_compare_arms_rejects_non_two_arm_shape() -> None:
	out = mf.compare_arms({"A": {"x": 1}, "C": {"x": 2}}, allowed_differences=["x"])
	assert out["ok"] is False
	assert "arms_must_be_two" in [r["code"] for r in out["reasons"]]


def test_volatile_context_fields_never_reach_arm_docs() -> None:
	doc = mf.build_manifest(
		experiment_id="exp_v",
		mode="a1",
		task_id="t",
		pair_id="p1",
		repeat=0,
		context=_context(),
		variants={
			"A": {"blocks": {"compact": "old"}},
			"B": {"blocks": {"compact": "new"}},
		},
		allowed_differences=["variant.blocks.compact"],
	)
	assert doc["comparability"]["ok"] is True
	assert doc["context"]["code"]["probed_at"] == 1.0
	for arm in ("A", "B"):
		flat = mf.flatten(doc["arms"][arm])
		assert "context.code.probed_at" not in flat
		assert "context.model.captured_at" not in flat


def test_require_comparable_raises_machine_readable_reason() -> None:
	doc = mf.build_manifest(
		experiment_id="exp_r",
		mode="a1",
		task_id="t",
		pair_id="p1",
		repeat=0,
		context=_context(),
		variants={
			"A": {"blocks": {"compact": "old"}, "params": {"temperature": 0.3}},
			"B": {"blocks": {"compact": "new"}, "params": {"temperature": 0.9}},
		},
		allowed_differences=["variant.blocks.compact"],
	)
	with pytest.raises(mf.SingleVariableViolation) as exc:
		mf.require_comparable(doc)
	assert exc.value.comparability["ok"] is False
	assert "variant.params.temperature" in exc.value.comparability["undeclared"][0]["path"]


def test_manifest_is_written_once_and_immutable(tmp_path: Path) -> None:
	doc = mf.build_manifest(
		experiment_id="exp_w",
		mode="a0",
		task_id="t",
		pair_id="p1",
		repeat=0,
		context=_context(),
		variants={"A": {}, "B": {}},
		allowed_differences=["*"],
	)
	path = mf.write_manifest(doc, directory=tmp_path)
	assert path.is_file()
	# 同一份内容再写一次是幂等的（重启恢复要靠这一点）
	assert mf.write_manifest(doc, directory=tmp_path) == path
	changed = dict(doc)
	changed["note"] = "after-the-fact edit"
	with pytest.raises(mf.ManifestImmutableError):
		mf.write_manifest(changed, directory=tmp_path)


def test_unknown_mode_is_refused() -> None:
	with pytest.raises(mf.ManifestError):
		mf.build_manifest(
			experiment_id="e",
			mode="a3",
			task_id="t",
			pair_id="p",
			repeat=0,
			context=_context(),
			variants={"A": {}, "B": {}},
		)


def test_inventory_digest_tracks_every_file_and_content() -> None:
	inv_a = mf.file_inventory(_write_tree([("a.py", "1"), ("b/c.py", "2")]))
	inv_b = mf.file_inventory(_write_tree([("a.py", "1"), ("b/c.py", "2")]))
	inv_c = mf.file_inventory(_write_tree([("a.py", "1"), ("b/c.py", "3")]))
	inv_d = mf.file_inventory(_write_tree([("a.py", "1")]))
	assert mf.inventory_digest(inv_a) == mf.inventory_digest(inv_b)
	assert mf.inventory_digest(inv_a) != mf.inventory_digest(inv_c)
	assert mf.inventory_digest(inv_a) != mf.inventory_digest(inv_d)


def test_workspace_section_lists_ignored_files_that_are_not_included(tmp_path: Path) -> None:
	import subprocess

	(tmp_path / ".gitignore").write_text("secret.env\nbuild/\n", encoding="utf-8")
	(tmp_path / "tracked.py").write_text("x = 1\n", encoding="utf-8")
	(tmp_path / "secret.env").write_text("TOKEN=1\n", encoding="utf-8")
	for args in (["init", "-q"], ["add", ".gitignore", "tracked.py"], ["config", "user.email", "t@t"], ["config", "user.name", "t"], ["commit", "-qm", "base"]):
		subprocess.run(["git", "-C", str(tmp_path), *args], capture_output=True, timeout=60)
	section = mf.workspace_section(tmp_path, snapshot_commit="c1")
	assert section["is_git_repo"] is True
	assert "secret.env" in section["ignored"]
	assert section["ignored_not_included"] == ["secret.env"]
	supplied = mf.workspace_section(tmp_path, ignored_supplied=["secret.env"])
	assert supplied["ignored_not_included"] == []
	assert supplied["ignored_supplied"] == ["secret.env"]


def _write_tree(files: list[tuple[str, str]]) -> Path:
	import tempfile

	root = Path(tempfile.mkdtemp(prefix="xeyo_inv_"))
	for rel, text in files:
		target = root / rel
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_text(text, encoding="utf-8")
	return root


def test_price_from_pricing_never_invents_zero(tmp_path: Path, monkeypatch) -> None:
	row = mf.price_from_pricing(provider="deepseek", model="deepseek-v4-flash")
	assert row["status"] == "ok"
	assert row["currency"] == "CNY"
	assert row["rates"]["out"] > 0
	assert row["price_version"]
	monkeypatch.setattr(
		"usage.pricing.unit_prices_cny_per_mtoken",
		lambda **_kw: (_ for _ in ()).throw(RuntimeError("no table")),
	)
	bad = mf.price_from_pricing(provider="weird", model="m")
	assert bad["status"] == "unknown"
	assert bad.get("rates") is None
	section = mf.budget_section(price=bad, cap_cny=1.0)
	assert section["price_status"] == "unknown"
	assert section["basis"] == "按 usage 估算（非账单实付）"


def test_store_dirs_are_created_by_manifest_write(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_DIAGNOSTICS_DIR", str(tmp_path / "diag"))
	store.reset_store_caches()
	doc = mf.build_manifest(
		experiment_id="exp_dir",
		mode="a0",
		task_id="t",
		pair_id="p",
		repeat=0,
		context=_context(),
		variants={"A": {}, "B": {}},
		allowed_differences=["*"],
	)
	mf.write_manifest(doc)
	assert mf.load_manifest("exp_dir") is not None
