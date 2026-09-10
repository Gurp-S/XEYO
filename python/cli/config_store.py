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

VALID_PROVIDERS = frozenset({"deepseek", "openai", "anthropic", "local", "fake"})
VALID_PERMISSION_MODES = frozenset({"always", "risk", "never", "allow"})


@dataclass
class CliConfig:
	api_key: str = ""
	provider: str = "deepseek"
	model: str = ""
	base_url: str = ""
	permission_mode: str = "risk"
	server_base_url: str = "http://127.0.0.1:8000"
	# 上次成功使用的工作区（一键使用会记住它）。
	last_cwd: str = ""
	# Output-compact 随 profile 打包，其他处（CLI/server）也会读取。
	output_compact: bool = False
	# 上一轮思考回顾 T_now 注入（默认关；GUI 会话设置等价字段 reasoning_tail）。
	reasoning_tail: bool = False
	# 密钥只以环境变量名引用，绝不明文落盘。
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
	# 密钥引用（顶层 `api_key_env` 或 `[secrets] env_key`）会
	# 规范化到 `api_key_env` 字段，调用方只需读一处。
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
			# 绝不把明文密钥写盘。密钥只会在下方
			# 以环境变量引用（api_key_env）形式持久化。
			continue
		if key == "api_key_env":
			# 在下方显式写入为密钥引用。
			continue
		if isinstance(value, bool):
			lines.append(f"{key} = {str(value).lower()}")
		elif isinstance(value, (int, float)):
			lines.append(f"{key} = {value}")
		else:
			escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
			lines.append(f'{key} = "{escaped}"')
	# 密钥仅以环境变量引用持久化。若调用方设置了 api_key
	# 却未指明环境变量名，则回退到规范变量名，确保密钥
	# 绝不以明文写入 config.toml。
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
	# 配置了密钥环境变量引用时，只从该变量读取。
	# 若该变量未设置则返回空，而不是回退到文件里可能残留的
	# 任何明文值 —— 磁盘上不留密钥。
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
	# XEYO_MODEL 历史上指后端；忽略看起来像模型 id 的值。
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
