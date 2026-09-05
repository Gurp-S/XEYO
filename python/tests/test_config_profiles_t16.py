"""T16: config profile + feature registry + env_key (no-plaintext).

Isolation follows the project convention: conftest already pins XEYO_HOME to a
per-test tmp dir, so ``config_path()`` points at an isolated ``config.toml``.
We still set XEYO_HOME explicitly in each test for clarity/robustness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.config_store import (
	CliConfig,
	config_path,
	load_config,
	resolve_api_key,
	resolve_profile,
	save_config,
)
from cli.feature_registry import FEATURE_SPECS, parse_features


def _write_config(text: str) -> Path:
	path = config_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")
	return path


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def test_profile_declared_keys_override_base_and_undeclared_keep_base(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	_write_config(
		'model = "base-model"\n'
		'permission_mode = "risk"\n'
		"output_compact = false\n"
		"reasoning_tail = false\n"
		"[profiles.dev]\n"
		'model = "dev-model"\n'
		"output_compact = true\n"
		"reasoning_tail = true\n"
	)
	base = load_config()
	assert base.model == "base-model"
	assert base.permission_mode == "risk"
	assert base.output_compact is False
	assert base.reasoning_tail is False

	dev = load_config(profile="dev")
	assert dev.model == "dev-model"          # declared → override
	assert dev.output_compact is True        # declared → override
	assert dev.reasoning_tail is True        # declared → override
	assert dev.permission_mode == "risk"     # undeclared → keeps base


def test_resolve_profile_only_declared_keys_override() -> None:
	base = CliConfig(model="base", permission_mode="never", output_compact=False)
	data = {"profiles": {"fast": {"model": "fast-model", "output_compact": True, "reasoning_tail": True}}}
	out = resolve_profile(base, data, "fast")
	assert out.model == "fast-model"
	assert out.output_compact is True
	assert out.reasoning_tail is True
	assert out.permission_mode == "never"  # undeclared keeps base


def test_resolve_profile_missing_is_fail_closed(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	base = CliConfig(model="base")
	out = resolve_profile(base, {"profiles": {}}, "nope")
	assert out.model == "base"
	assert "profile 'nope' not found" in capsys.readouterr().err


def test_resolve_profile_empty_name_returns_base() -> None:
	base = CliConfig(model="base")
	out = resolve_profile(base, {"profiles": {"dev": {"model": "dev"}}}, "")
	assert out is base
	assert out.model == "base"


def test_cli_profile_option_exposed() -> None:
	from typer.testing import CliRunner

	from cli.main import app

	res = CliRunner().invoke(app, ["chat", "--help"])
	assert res.exit_code == 0
	assert "--profile" in (res.stdout or "")


# ---------------------------------------------------------------------------
# Feature registry
# ---------------------------------------------------------------------------


def test_parse_features_known_returns_default_and_stage() -> None:
	parsed, warnings = parse_features({})
	assert parsed["XEYO_PERMISSION_MODE"] == "risk"
	assert parsed["XEYO_TOOL_AGING"] == "0"
	assert parsed["XEYO_C2_GATE"] == "1"
	assert warnings == []
	# Registry exposes key/stage/default/removed per switch.
	assert FEATURE_SPECS["XEYO_PERMISSION_MODE"].key == "XEYO_PERMISSION_MODE"
	assert FEATURE_SPECS["XEYO_PERMISSION_MODE"].stage == "stable"
	assert FEATURE_SPECS["XEYO_L5"].stage == "internal"
	assert FEATURE_SPECS["XEYO_MODEL_NAME"].default is None
	assert FEATURE_SPECS["XEYO_LEGACY_THING"].removed is True


def test_parse_features_known_value_overrides_default() -> None:
	parsed, warnings = parse_features({"XEYO_PERMISSION_MODE": "never"})
	assert parsed["XEYO_PERMISSION_MODE"] == "never"
	assert warnings == []


def test_parse_features_removed_key_emits_deprecation() -> None:
	parsed, warnings = parse_features({"XEYO_LEGACY_THING": "1"})
	assert any("removed" in w.lower() for w in warnings)
	assert "XEYO_LEGACY_THING" not in parsed


def test_parse_features_unknown_key_hints_without_exception() -> None:
	parsed, warnings = parse_features(
		{"XEYO_FUTURE_FLAG": "1", "XEYO_WHATEVER": "x"}
	)
	assert any("unknown" in w.lower() for w in warnings)
	assert "XEYO_FUTURE_FLAG" not in parsed
	assert "XEYO_WHATEVER" not in parsed


def test_parse_features_defaults_to_os_environ() -> None:
	# No mapping supplied → reads os.environ; must not raise and returns dict.
	parsed, warnings = parse_features()
	assert isinstance(parsed, dict)
	assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# env_key secret reference (no plaintext on disk)
# ---------------------------------------------------------------------------


def test_env_key_resolves_secret_from_env(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_MODEL_API_KEY", "sk-from-env")
	_write_config(
		'provider = "openai"\n'
		"[secrets]\n"
		'env_key = "XEYO_MODEL_API_KEY"\n'
	)
	cfg = load_config()
	assert cfg.api_key_env == "XEYO_MODEL_API_KEY"
	assert resolve_api_key(None, cfg=cfg) == "sk-from-env"


def test_env_key_reads_top_level_api_key_env(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_MODEL_API_KEY", "sk-top")
	_write_config('api_key_env = "XEYO_MODEL_API_KEY"\n')
	cfg = load_config()
	assert cfg.api_key_env == "XEYO_MODEL_API_KEY"
	assert resolve_api_key(None, cfg=cfg) == "sk-top"


def test_env_key_absent_returns_empty_not_plaintext(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.delenv("XEYO_MODEL_API_KEY", raising=False)
	# Env_key configured; even a legacy plaintext in the file must NOT be used.
	_write_config(
		'api_key = "sk-plaintext-legacy"\n'
		"[secrets]\n"
		'env_key = "XEYO_MODEL_API_KEY"\n'
	)
	cfg = load_config()
	assert cfg.api_key_env == "XEYO_MODEL_API_KEY"
	assert resolve_api_key(None, cfg=cfg) == ""


def test_save_config_never_writes_plaintext(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	cfg = CliConfig(provider="openai", api_key="sk-secret")
	save_config(cfg)
	text = config_path().read_text(encoding="utf-8")
	assert "sk-secret" not in text
	assert "api_key_env" in text
	reloaded = load_config()
	assert reloaded.api_key == ""                      # no plaintext round-trips
	assert reloaded.api_key_env == "XEYO_MODEL_API_KEY"


def test_save_config_writes_env_key_reference_only(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	cfg = CliConfig(api_key="secret-token", api_key_env="XEYO_MODEL_API_KEY")
	save_config(cfg)
	text = config_path().read_text(encoding="utf-8")
	assert "secret-token" not in text
	assert 'api_key_env = "XEYO_MODEL_API_KEY"' in text


def test_config_set_api_key_roundtrip_writes_reference_only(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	from typer.testing import CliRunner

	from cli.main import app

	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	res = CliRunner().invoke(app, ["config", "set", "api_key", "sk-supersecret"])
	assert res.exit_code == 0, (res.stdout or "") + str(res.exception)
	text = config_path().read_text(encoding="utf-8")
	assert "sk-supersecret" not in text
	assert "api_key_env" in text
