"""CLI config: ~/.xeyo/config.toml"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
	import tomllib
else:  # pragma: no cover
	tomllib = None  # type: ignore[assignment]

from session.workspace_path import xeyo_data_root

VALID_PROVIDERS = frozenset({"deepseek", "openai", "local", "fake"})
VALID_PERMISSION_MODES = frozenset({"always", "risk", "never", "allow"})


@dataclass
class CliConfig:
	api_key: str = ""
	provider: str = "deepseek"
	model: str = ""
	base_url: str = ""
	permission_mode: str = "risk"
	server_base_url: str = "http://127.0.0.1:8000"
	# Last successful workspace (click-to-use remembers it).
	last_cwd: str = ""
	# Output-compact is bundled in profiles and read elsewhere (CLI/server).
	output_compact: bool = False
	# 上一轮思考回顾 T_now 注入（默认关；GUI 会话设置等价字段 reasoning_tail）。
	reasoning_tail: bool = False
	# Secret is referenced by env-var name, never stored as plaintext on disk.
	api_key_env: str = ""
	# 41 号：goal round driver 全局默认轮次上限（per-goal max_rounds>0 时优先）。
	goal_round_cap: int = 32


def config_path() -> Path:
	return xeyo_data_root() / "config.toml"


def asdict_safe(cfg: CliConfig) -> dict[str, Any]:
	return asdict(cfg)


def _secret_env_ref(data: dict[str, Any]) -> str:
	"""A secret reference can live top-level (``api_key_env``) or in
	``[secrets] env_key``. Either form points at an env var; never a plaintext."""
	top = data.get("api_key_env")
	if isinstance(top, str) and top.strip():
		return top.strip()
	secrets = data.get("secrets")
	if isinstance(secrets, dict):
		ref = secrets.get("env_key")
		if isinstance(ref, str) and ref.strip():
			return ref.strip()
	return ""


def _profile_table(data: dict[str, Any], name: str) -> dict[str, Any] | None:
	profiles = data.get("profiles")
	if not isinstance(profiles, dict):
		return None
	table = profiles.get(name)
	return table if isinstance(table, dict) else None


def resolve_profile(base: CliConfig, data: dict[str, Any], name: str) -> CliConfig:
	"""Merge a named ``[profiles.<name>]`` table over ``base``.

	Only keys DECLARED in the profile override the base; undeclared keys keep
	the base value. Missing/empty ``name`` returns ``base`` unchanged, and a
	missing or non-table profile is fail-closed to ``base`` (with a warning),
	so ``load_config`` never crashes on a bad profile reference.
	"""
	if not name:
		return base
	table = _profile_table(data, name)
	if table is None:
		print(
			f"warning: profile '{name}' not found in {config_path()}; "
			"using base config",
			file=sys.stderr,
		)
		return base
	known = {f.name for f in fields(CliConfig)}
	merged = asdict(base)
	for k in known:
		if k in table and table[k] is not None:
			merged[k] = table[k]
	return CliConfig(**merged)  # type: ignore[arg-type]


def load_config(profile: str | None = None) -> CliConfig:
	path = config_path()
	data: dict[str, Any] = {}
	if path.is_file() and tomllib is not None:
		try:
			parsed = tomllib.loads(path.read_text(encoding="utf-8"))
			if isinstance(parsed, dict):
				data = parsed
		except Exception as exc:  # noqa: BLE001
			print(
				f"warning: failed to parse {path}: {exc}; using defaults",
				file=sys.stderr,
			)
			data = {}
	known = {f.name for f in fields(CliConfig)}
	kwargs = {k: data[k] for k in known if k in data and data[k] is not None}
	# A secret reference (top-level `api_key_env` or `[secrets] env_key`) is
	# normalized into the `api_key_env` field so callers read one place.
	ref = _secret_env_ref(data)
	if ref:
		kwargs["api_key_env"] = ref
	cfg = CliConfig(**kwargs)  # type: ignore[arg-type]
	if profile:
		cfg = resolve_profile(cfg, data, profile)
	return cfg


def save_config(cfg: CliConfig) -> Path:
	path = config_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = ["# XEYO CLI config", ""]
	for key, value in asdict(cfg).items():
		if key == "api_key":
			# NEVER write a plaintext secret to disk. The secret is persisted
			# only as an env-var reference (api_key_env) below.
			continue
		if key == "api_key_env":
			# Written explicitly as the secret reference below.
			continue
		if isinstance(value, bool):
			lines.append(f"{key} = {str(value).lower()}")
		elif isinstance(value, (int, float)):
			lines.append(f"{key} = {value}")
		else:
			escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
			lines.append(f'{key} = "{escaped}"')
	# Persist a secret as an env-var reference only. If caller left api_key set
	# without naming an env var, default to the canonical one so the secret is
	# never written to config.toml in clear.
	if cfg.api_key or cfg.api_key_env:
		ref = (cfg.api_key_env or "XEYO_MODEL_API_KEY").strip()
		if ref:
			lines.append(f'api_key_env = "{ref}"')
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	return path


def validate_config_value(key: str, value: str) -> str | bool:
	"""Normalize/validate a config set value; raise ValueError on bad input."""
	v = (value or "").strip()
	if key == "provider":
		low = v.lower()
		if low not in VALID_PROVIDERS:
			raise ValueError(
				f"provider must be one of: {', '.join(sorted(VALID_PROVIDERS))}"
			)
		return low
	if key == "permission_mode":
		low = v.lower()
		if low not in VALID_PERMISSION_MODES:
			raise ValueError(
				"permission_mode must be one of: always, risk, never"
			)
		return "never" if low == "allow" else low
	if key == "output_compact":
		low = v.lower()
		if low in ("1", "true", "yes", "on"):
			return True
		if low in ("0", "false", "no", "off"):
			return False
		raise ValueError("output_compact must be true/false (or 1/0, on/off)")
	if key == "reasoning_tail":
		low = v.lower()
		if low in ("1", "true", "yes", "on"):
			return True
		if low in ("0", "false", "no", "off"):
			return False
		raise ValueError("reasoning_tail must be true/false (or 1/0, on/off)")
	return v


def resolve_api_key(explicit: str | None = None, *, cfg: CliConfig | None = None) -> str:
	if explicit and explicit.strip():
		return explicit.strip()
	cfg = cfg or load_config()
	# When a secret env-var reference is configured, read ONLY from that var.
	# If it's unset we return empty rather than falling back to any plaintext
	# value that might still be in the file — no secret from disk.
	if cfg.api_key_env.strip():
		return os.environ.get(cfg.api_key_env.strip(), "").strip()
	for key in ("XEYO_MODEL_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
		val = os.environ.get(key, "").strip()
		if val:
			return val
	return (cfg.api_key or "").strip()


def resolve_provider(explicit: str | None = None, *, cfg: CliConfig | None = None) -> str:
	if explicit and explicit.strip():
		return explicit.strip().lower()
	env = os.environ.get("XEYO_MODEL", "").strip().lower()
	# XEYO_MODEL historically means backend; ignore values that look like model ids.
	if env and env in VALID_PROVIDERS:
		return env
	return ((cfg or load_config()).provider or "deepseek").strip().lower() or "deepseek"


def resolve_model(explicit: str | None = None, *, cfg: CliConfig | None = None) -> str:
	if explicit and explicit.strip():
		return explicit.strip()
	env = os.environ.get("XEYO_MODEL_NAME", "").strip()
	if env:
		return env
	return ((cfg or load_config()).model or "").strip()


def resolve_base_url(explicit: str | None = None, *, cfg: CliConfig | None = None) -> str:
	if explicit and explicit.strip():
		return explicit.strip()
	env = os.environ.get("XEYO_BASE_URL", "").strip()
	if env:
		return env
	return ((cfg or load_config()).base_url or "").strip()


def resolve_permission_mode(
	explicit: str | None = None, *, cfg: CliConfig | None = None
) -> str:
	if explicit and explicit.strip():
		return explicit.strip().lower()
	env = os.environ.get("XEYO_PERMISSION_MODE", "").strip().lower()
	if env:
		return "never" if env == "allow" else env
	return ((cfg or load_config()).permission_mode or "risk").strip().lower() or "risk"


def resolve_server_base_url(
	explicit: str | None = None, *, cfg: CliConfig | None = None
) -> str:
	if explicit and explicit.strip():
		return explicit.strip().rstrip("/")
	env = os.environ.get("XEYO_SERVER_URL", "").strip().rstrip("/")
	if env:
		return env
	return (
		(cfg or load_config()).server_base_url or "http://127.0.0.1:8000"
	).strip().rstrip("/")
