"""T12 受保护元数据回归：workspace 内 .git/.xeyo/.agents 默认只读。"""

from __future__ import annotations

from pathlib import Path

import pytest

from permissions.filesystem import (
	ENV_ALLOW_PROTECTED_METADATA,
	protected_metadata_reason,
)


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
	ws = tmp_path / "ws"
	ws.mkdir()
	return ws


def test_git_hooks_write_blocked(ws: Path) -> None:
	reason = protected_metadata_reason(str(ws / ".git" / "hooks" / "pre-commit"), cwd=str(ws))
	assert reason is not None
	assert "protected metadata" in reason


def test_xeyo_settings_write_blocked(ws: Path) -> None:
	# 治理#3：agent 静默改 .xeyo/settings.json 必须被堵。
	assert protected_metadata_reason(str(ws / ".xeyo" / "settings.json"), cwd=str(ws)) is not None


def test_agents_write_blocked(ws: Path) -> None:
	assert protected_metadata_reason(str(ws / ".agents" / "foo.toml"), cwd=str(ws)) is not None


def test_normal_source_write_unaffected(ws: Path) -> None:
	assert protected_metadata_reason(str(ws / "src" / "main.py"), cwd=str(ws)) is None
	assert protected_metadata_reason(str(ws / "README.md"), cwd=str(ws)) is None


def test_env_relaxation(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv(ENV_ALLOW_PROTECTED_METADATA, "1")
	assert protected_metadata_reason(str(ws / ".git" / "config"), cwd=str(ws)) is None


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows 大小写语义")
def test_case_insensitive_on_windows(ws: Path) -> None:
	assert protected_metadata_reason(str(ws / ".GIT" / "config"), cwd=str(ws)) is not None


def test_outside_workspace_not_flagged(tmp_path: Path, ws: Path) -> None:
	other = tmp_path / "other"
	other.mkdir()
	assert protected_metadata_reason(str(other / ".git" / "config"), cwd=str(ws)) is None


def test_nested_metadata_components_denied(ws: Path) -> None:
	# G78: 任一路径组件命中即 DENY——嵌套仓库/子模块 .git 与顶层同等保护。
	assert (
		protected_metadata_reason(str(ws / "src" / ".git" / "x"), cwd=str(ws))
		is not None
	)
	assert (
		protected_metadata_reason(str(ws / "sub" / "mod" / ".xeyo" / "a.json"), cwd=str(ws))
		is not None
	)
	assert (
		protected_metadata_reason(str(ws / "packages" / ".agents" / "t.toml"), cwd=str(ws))
		is not None
	)


def test_write_permission_for_path_denies(ws: Path) -> None:
	from permissions.filesystem import PermissionDecision, check_write_permission_for_path

	ctx = type("Ctx", (), {"cwd": str(ws), "allowed_working_paths": [str(ws)]})()
	decision = check_write_permission_for_path(
		str(ws / ".xeyo" / "settings.json"), context=ctx
	)
	assert decision == PermissionDecision.DENY


def test_secret_path_new_entries(tmp_path: Path) -> None:
	"""G77: .netrc/.git-credentials/.kube/config/.gnupg/id_dsa/.env 变体全 DENY。"""
	from permissions.filesystem import is_secret_path

	for rel in (
		"home/.netrc",
		"home/.git-credentials",
		"home/.kube/config",
		"home/.gnupg/id_dsa",
		"home/.env.staging",
		"home/.env.local",
		"app/.aws/credentials",
	):
		assert is_secret_path(str(tmp_path / rel), cwd=str(tmp_path)), rel
	assert not is_secret_path(str(tmp_path / "src" / "readme.md"), cwd=str(tmp_path))
	assert not is_secret_path(str(tmp_path / ".env.example"), cwd=str(tmp_path))
	assert not is_secret_path(str(tmp_path / ".env.sample"), cwd=str(tmp_path))
