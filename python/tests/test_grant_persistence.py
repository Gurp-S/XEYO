"""grant（「不再询问此类命令」）跨进程持久化 —— 2026-09-20。

旧行为：无策略文件时 grant 全在**进程内存** ⇒ 服务重启即失忆 + 24h TTL，
GUI 勾选框「不再询问此类命令」的收益被结构性削掉一半（用户反馈点之一）。
新行为：落盘 `~/.xeyo/permission_grants.json`（XEYO_HOME / XEYO_GRANT_STORE 可覆盖），
TTL / workspace 维度语义不变，坏文件 fail-open（空存储 + 审计，绝不抛出）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from permissions.store import (
	PermissionGrantStore,
	default_grant_store,
	grant_fingerprint,
	grant_store_path,
)
from permissions.policy import evaluate_policy
from permissions.filesystem import PermissionDecision


def _store(tmp_path: Path, **kw) -> PermissionGrantStore:
	return PermissionGrantStore(**kw)


def test_grant_survives_restart(tmp_path: Path) -> None:
	fp = grant_fingerprint("Bash", {"command": "gh pr list"})
	first = _store(tmp_path)
	first.add(tool_name="Bash", fingerprint=fp, scope=str(tmp_path))
	assert Path(grant_store_path()).is_file()
	# 模拟重启：新实例从盘上恢复
	second = _store(tmp_path)
	assert second.match(tool_name="Bash", fingerprint=fp, scope=str(tmp_path)) is not None


def test_restored_grant_short_circuits_policy(tmp_path: Path) -> None:
	"""落盘后（重启后）同一条命令不再弹确认。"""
	cwd = str(tmp_path)
	fp = grant_fingerprint("Bash", {"command": "gh pr list"})
	_store(tmp_path).add(tool_name="Bash", fingerprint=fp, scope=cwd)
	import permissions.store as st

	st._default_grant_store = _store(tmp_path)  # 新进程的默认 store（已恢复）
	try:
		r = evaluate_policy("Bash", {"command": "gh pr list"}, cwd=cwd, allowed_paths=[cwd])
		assert r.decision == PermissionDecision.ALLOW
		assert r.matched_rule == "grant_store"
	finally:
		st._default_grant_store = None


def test_expired_grant_not_restored(tmp_path: Path) -> None:
	path = Path(grant_store_path())
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(
			{
				"version": 1,
				"grants": [
					{
						"tool_name": "Bash",
						"fingerprint": "gh pr",
						"scope": str(tmp_path),
						"created_at": time.time() - 10_000,
						"expires_at": time.time() - 1,
						"actor": "desktop",
					}
				],
			}
		),
		encoding="utf-8",
	)
	store = _store(tmp_path)
	assert store.match(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path)) is None


def test_ttl_preserved_across_restart(tmp_path: Path) -> None:
	store = _store(tmp_path)
	grant = store.add(tool_name="Bash", fingerprint="npm install", scope=str(tmp_path))
	assert grant is not None and grant.expires_at is not None
	reloaded = _store(tmp_path)
	restored = reloaded.match(tool_name="Bash", fingerprint="npm install", scope=str(tmp_path))
	assert restored is not None
	assert restored.expires_at == grant.expires_at


def test_scope_isolation_across_workspaces(tmp_path: Path) -> None:
	store = _store(tmp_path)
	other = tmp_path / "other"
	other.mkdir()
	store.add(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path))
	assert store.match(tool_name="Bash", fingerprint="gh pr", scope=str(other)) is None
	assert store.match(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path)) is not None


def test_revoke_persists(tmp_path: Path) -> None:
	store = _store(tmp_path)
	grant = store.add(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path))
	assert grant is not None
	assert store.revoke(grant.grant_id) is True
	assert _store(tmp_path).match(
		tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path)
	) is None


def test_corrupt_file_fails_open(tmp_path: Path) -> None:
	path = Path(grant_store_path())
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("{not json", encoding="utf-8")
	store = _store(tmp_path)  # 不抛
	assert store.list() == []
	# 坏文件不影响本次新增
	store.add(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path))
	assert store.match(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path)) is not None


def test_persist_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_GRANT_PERSIST", "off")
	store = _store(tmp_path)
	store.add(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path))
	assert not Path(grant_store_path()).exists()
	assert default_grant_store() is not None  # 进程内语义仍在


def test_unwritable_path_fails_open(tmp_path: Path, monkeypatch) -> None:
	blocker = tmp_path / "blocker"
	blocker.write_text("x", encoding="utf-8")  # 用文件占位，mkdir 必失败
	monkeypatch.setenv("XEYO_GRANT_STORE", str(blocker / "grants.json"))
	store = _store(tmp_path)
	grant = store.add(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path))
	assert grant is not None
	# 授权本次仍生效（落盘失败只记日志）
	assert store.match(tool_name="Bash", fingerprint="gh pr", scope=str(tmp_path)) is not None
