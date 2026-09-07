"""Feature-spec registry for XEYO_* switches (T16).

Declarative table mapping every known ``XEYO_*`` environment switch to its
staging / default / removal state, plus a fail-closed parser that callers can
consult instead of scattering raw ``os.environ.get(...)`` calls across the
codebase.

Contract:

* ``FEATURE_SPECS`` — ``dict[str, FeatureSpec]``; each spec carries
  ``key``/``stage``/``default``/``removed``.
* ``parse_features(env_or_dict) -> (parsed, warnings)`` — recognizes known
  switches (default when unset, raw value when set), emits a deprecation hint
  for ``removed`` keys and a non-fatal "unknown" hint for any ``XEYO_*`` key
  not in the registry. It never raises on unrecognized input.

Fail-closed and non-breaking: this is the declarative source of truth; the
parser is something callers *may* use. No existing call site is rewritten
here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

# stage 仅作信息展示；只有 "removed" 会改变
# 解析行为（该开关会被识别、丢弃并上报）。
_STAGE_STABLE = "stable"
_STAGE_INTERNAL = "internal"
_STAGE_DEPRECATED = "deprecated"
_STAGE_REMOVED = "removed"


@dataclass(frozen=True)
class FeatureSpec:
	key: str
	stage: str = _STAGE_STABLE
	default: Any = None
	removed: bool = False


FEATURE_SPECS: dict[str, FeatureSpec] = {
	# --- 核心用户开关 --------------------------------------
	"XEYO_MODEL": FeatureSpec("XEYO_MODEL", stage=_STAGE_STABLE),
	"XEYO_MODEL_NAME": FeatureSpec("XEYO_MODEL_NAME", stage=_STAGE_STABLE),
	"XEYO_MODEL_API_KEY": FeatureSpec("XEYO_MODEL_API_KEY", stage=_STAGE_STABLE),
	"XEYO_PERMISSION_MODE": FeatureSpec(
		"XEYO_PERMISSION_MODE", stage=_STAGE_STABLE, default="risk"
	),
	"XEYO_BASE_URL": FeatureSpec("XEYO_BASE_URL", stage=_STAGE_STABLE),
	"XEYO_CWD": FeatureSpec("XEYO_CWD", stage=_STAGE_STABLE),
	"XEYO_L5": FeatureSpec("XEYO_L5", stage=_STAGE_INTERNAL, default="project"),
	"XEYO_C2_GATE": FeatureSpec("XEYO_C2_GATE", stage=_STAGE_INTERNAL, default="1"),
	"XEYO_REWIND_ENABLED": FeatureSpec(
		"XEYO_REWIND_ENABLED", stage=_STAGE_STABLE, default="1"
	),
	"XEYO_TOOL_AGING": FeatureSpec(
		"XEYO_TOOL_AGING", stage=_STAGE_STABLE, default="0"
	),
	"XEYO_MAX_TURNS": FeatureSpec("XEYO_MAX_TURNS", stage=_STAGE_STABLE),
	"XEYO_MAX_TOOL_CALLING": FeatureSpec(
		"XEYO_MAX_TOOL_CALLING", stage=_STAGE_STABLE
	),
	"XEYO_HTTP_PORT": FeatureSpec(
		"XEYO_HTTP_PORT", stage=_STAGE_STABLE, default="8000"
	),
	"XEYO_HTTP_HOST": FeatureSpec(
		"XEYO_HTTP_HOST", stage=_STAGE_STABLE, default="127.0.0.1"
	),
	"XEYO_CONTEXT_LIMIT_TOKENS": FeatureSpec(
		"XEYO_CONTEXT_LIMIT_TOKENS", stage=_STAGE_STABLE
	),
	"XEYO_NO_SESSION_PERSISTENCE": FeatureSpec(
		"XEYO_NO_SESSION_PERSISTENCE", stage=_STAGE_STABLE, default="0"
	),
	# --- 已移除占位（识别、上报、永不生效） ------
	"XEYO_LEGACY_THING": FeatureSpec(
		"XEYO_LEGACY_THING", stage=_STAGE_REMOVED, removed=True
	),
}


def _looks_like_switch(name: Any) -> bool:
	return isinstance(name, str) and name.startswith("XEYO_")


def parse_features(
	env_or_dict: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
	"""Parse feature switches from an env-like mapping.

	``env_or_dict`` defaults to ``os.environ``. Returns ``(parsed, warnings)``:

	* ``parsed`` — effective value per known switch: the spec default when the
	  switch is unset/blank, otherwise the raw value present in the mapping.
	  Removed switches are never present in ``parsed``.
	* ``warnings`` — human-readable hints appended in scan order: a deprecation
	  for each ``removed`` switch and an "unknown" notice for each ``XEYO_*``
	  key that is not in the registry. Never raises on missing/bad input.
	"""
	env = os.environ if env_or_dict is None else env_or_dict

	parsed: dict[str, Any] = {}
	warnings: list[str] = []

	for key, spec in FEATURE_SPECS.items():
		if spec.removed:
			if key in env:
				warnings.append(
					f"XEYO: switch {key} has been removed and is ignored; "
					"remove it from your environment"
				)
			continue
		raw = env.get(key) if hasattr(env, "get") else None
		if raw is None or str(raw) == "":
			parsed[key] = spec.default
		else:
			parsed[key] = raw

	for key in env:
		if _looks_like_switch(key) and key not in FEATURE_SPECS:
			warnings.append(
				f"XEYO: unknown switch {key} is ignored "
				"(not a recognized feature flag)"
			)

	return parsed, warnings




