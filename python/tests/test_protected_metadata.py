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


def test_top_level_only_not_deep_names(ws: Path) -> None:
	# 只有顶层目录命中；深层同名目录不受影响。
	assert protected_metadata_reason(str(ws / "src" / ".git" / "x"), cwd=str(ws)) is None


def test_write_permission_for_path_denies(ws: Path) -> None:
	from permissions.filesystem import PermissionDecision, check_write_permission_for_path

	ctx = type("Ctx", (), {"cwd": str(ws), "allowed_working_paths": [str(ws)]})()
	decision = check_write_permission_for_path(
		str(ws / ".xeyo" / "settings.json"), context=ctx
	)
	assert decision == PermissionDecision.DENY
