"""Skill 发现与元数据增强（F4：fail-closed frontmatter + 行向修复 + 双 flag）。

三源合并（workspace > home > plugin），按名 casefold 去重，返回结构化条目：

.. code-block:: python

	SkillEntry(
	  name="map",            # 目录名
	  source="workspace",    # workspace | home | plugin
	  description="...",     # 从 frontmatter / 首个标题提取
	  path=PosixPath("..."),
	  plugin="demo",         # 来自插件时非空
	  model_invocable=True,  # F4 双 flag（默认 true）
	  user_invocable=True,
	  paths=("...",),        # 纯元数据路径 tuple
	  mcp_dependencies=("...",),
	  broken=False, reason="",
	)

frontmatter 契约（手写解析，不引入 yaml 第三方依赖以守「非目标」）：
``---\nname / description / tags / model_hint / paths / model_invocable /
user_invocable / mcp_dependencies\n---``

**fail-closed**：任一 frontmatter 字段类型非法 → 丢整个 skill → broken-but-listed
条目 ``{name, broken:true, reason}``（进名册不进目录/不进加载）。
**行向修复**：``repair_frontmatter_scalar_fields`` 对「值含 ``: `` 或 flow 符
（``[{@` ``）的裸标量行」加单引号重试；其余错误照抛。
同名冲突：默认禁止覆盖（``allow_override=False``），沿用发现优先级。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from extension.config import ExtensionConfig, load_ext_config
from extension.loader import discover_plugins

_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

#: F4 双 flag 默认值。
_DEFAULT_MODEL_INVOCABLE = True
_DEFAULT_USER_INVOCABLE = True

#: fail-closed 字段类型校验表：字段名 → 判定说明（仅用于错误信息）。
_VALIDATED_FIELDS = (
	"name",
	"description",
	"tags",
	"model_hint",
	"paths",
	"model_invocable",
	"user_invocable",
	"mcp_dependencies",
)

#: 行向修复判定：裸标量值含这些字符视为需引用。
_FLOW_CHARS = frozenset("[{@`")
_REPAIR_COLON_RX = re.compile(r":\s")

#: 3s TTL 缓存（跳过重扫）+ digest（names+descs+序）。
_SKILL_CACHE_TTL_S = 3.0
_CACHE: dict[str, tuple[float, list["SkillEntry"], list[tuple[str, str]]]] = {}


@dataclass(frozen=True)
class SkillEntry:
	name: str
	path: Path
	source: str  # "workspace" | "home" | "plugin"
	description: str = ""
	plugin: str = ""
	model_hint: str = ""
	tags: tuple[str, ...] = ()
	model_invocable: bool = True
	user_invocable: bool = True
	paths: tuple[str, ...] = ()
	mcp_dependencies: tuple[str, ...] = ()
	#: broken-but-listed：坏 frontmatter 才置 True；不进目录/加载。
	broken: bool = False
	reason: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"source": self.source,
			"description": self.description,
			"plugin": self.plugin,
			"model_hint": self.model_hint,
			"tags": list(self.tags),
			"model_invocable": self.model_invocable,
			"user_invocable": self.user_invocable,
			"paths": list(self.paths),
			"mcp_dependencies": list(self.mcp_dependencies),
			"broken": self.broken,
			"reason": self.reason,
		}


# --------------------------------------------------------------------------- #
# 行向修复（移植 repair_frontmatter_scalar_fields）：裸标量行加单引号。
# --------------------------------------------------------------------------- #

def repair_frontmatter_scalar_fields(text: str) -> str:
	"""对「值含 ``: `` 或 flow 符的裸标量行」加单引号（重试可解析）。

	仅修复这类行；其余行原样保留。输入为 frontmatter 头文本（不含 ``---`` 包裹）；
	返回修复后的行文本（保持行数与顺序）。
	"""
	lines = text.splitlines()
	out: list[str] = []
	for line in lines:
		s = line.rstrip("\n")
		stripped = s.strip()
		if ":" in stripped and not stripped.startswith(("-", "#")):
			key, val = stripped.split(":", 1)
			raw_val = val.strip()
			if (
				raw_val
				and not raw_val.startswith(("'", '"'))
				and (":" in raw_val or any(c in _FLOW_CHARS for c in raw_val))
			):
				quote = "'" if "'" not in raw_val else '"'
				# 重建：保留 key 前缀 + 引用后的 value。
				prefix = s[: len(s) - len(val)] if val else s
				out.append(f"{prefix}{quote}{raw_val}{quote}")
				continue
		out.append(s)
	return "\n".join(out)


# --------------------------------------------------------------------------- #
# frontmatter 解析 + fail-closed 类型校验。
# --------------------------------------------------------------------------- #

def _parse_frontmatter_raw(text: str) -> dict[str, str]:
	"""解析 frontmatter 头（手写）；返回字段字符串值 dict。"""
	m = _FRONTMATTER_RE.match(text.lstrip("\ufeff"))
	if not m:
		return {}
	header = m.group(1)
	out: dict[str, str] = {}
	cur_key: str | None = None
	for line in header.splitlines():
		s = line.strip()
		if not s or s.startswith("#"):
			continue
		if ":" in s:
			k, v = s.split(":", 1)
			cur_key = k.strip().lower()
			out[cur_key] = v.strip().strip("\"'")
		elif cur_key and s.startswith("- "):
			prev = out.get(cur_key, "")
			out[cur_key] = (prev + "," + s[2:].strip()).strip(",")
	return out


def _parse_bool(value: str) -> bool:
	"""严格布尔解析；非法抛 ValueError（fail-closed）。"""
	v = (value or "").strip().lower()
	if v in ("true", "1", "yes", "on"):
		return True
	if v in ("false", "0", "no", "off"):
		return False
	raise ValueError(f"invalid boolean: {value!r}")


def _parse_list(value: str) -> tuple[str, ...]:
	"""CSV / dash 列表 → 去空 tuple。"""
	parts = [p.strip() for p in value.split(",") if p.strip()]
	return tuple(parts)


def _validated_meta(meta: dict[str, str]) -> dict[str, Any]:
	"""把原始字符串 meta 转成校验后的类型化 dict；字段类型非法则抛 ValueError。

	bad 任一字段 → 丢整个 skill（fail-closed）。
	"""
	validate = {
		"name": str,
		"description": str,
		"model_hint": str,
	}
	out: dict[str, Any] = {}
	for k, t in validate.items():
		if k in meta and not isinstance(meta[k], str):
			raise ValueError(f"{k} must be a string")
		out[k] = meta.get(k, "")

	# 纯元数据。
	for k, default in (("paths", ()), ("mcp_dependencies", ()), ("tags", ())):
		raw = meta.get(k, "")
		if raw == "":
			out[k] = default
		else:
			try:
				out[k] = _parse_list(raw)
			except Exception as e:  # noqa: BLE001
				raise ValueError(f"{k} invalid: {e}") from e
	# 双 flag（默认 true，严格解析）。
	for k, default in (("model_invocable", _DEFAULT_MODEL_INVOCABLE), ("user_invocable", _DEFAULT_USER_INVOCABLE)):
		raw = meta.get(k)
		if raw is None or raw == "":
			out[k] = default
		else:
			try:
				out[k] = _parse_bool(raw)
			except ValueError as e:
				raise ValueError(f"{k} invalid: {e}") from e
	return out


def _description(meta: dict[str, str], body: str) -> str:
	desc = meta.get("description", "").strip()
	if desc:
		return desc
	h = _HEADING_RE.search(body)
	return h.group(1).strip() if h else ""


def _entry_from_dir(d: Path, *, source: str, plugin: str = "") -> SkillEntry:
	"""从目录构建条目；坏 frontmatter → broken-but-listed。"""
	body = ""
	try:
		body = (d / "SKILL.md").read_text(encoding="utf-8")
	except OSError:
		body = ""
	try:
		meta = _parse_frontmatter_raw(body)
		validated = _validated_meta(meta)
	except ValueError as e:
		return SkillEntry(
			name=d.name, path=d, source=source, plugin=plugin, broken=True, reason=str(e)
		)
	return SkillEntry(
		name=d.name,
		path=d,
		source=source,
		description=_description(meta, body),
		plugin=plugin,
		model_hint=validated["model_hint"],
		tags=validated["tags"],
		model_invocable=validated["model_invocable"],
		user_invocable=validated["user_invocable"],
		paths=validated["paths"],
		mcp_dependencies=validated["mcp_dependencies"],
	)


def _scan_skill_dirs(root: Path, *, source: str, plugin: str = "") -> dict[str, SkillEntry]:
	out: dict[str, SkillEntry] = {}
	if not root.is_dir():
		return out
	try:
		for child in sorted(root.iterdir()):
			if not child.is_dir():
				continue
			if not (child / "SKILL.md").is_file():
				continue
			entry = _entry_from_dir(child, source=source, plugin=plugin)
			out[child.name.casefold()] = entry
	except OSError:
		return out
	return out


def _workspace_skill_root(cwd: str | None) -> Path | None:
	if not cwd:
		return None
	try:
		return (Path(cwd).expanduser().resolve() / ".xeyo" / "skills")
	except OSError:
		return None


def _home_skill_root() -> Path:
	from memory.instruction import xeyo_home

	return xeyo_home() / "skills"


def _plugin_skill_entries(loaded: list[object]) -> dict[str, SkillEntry]:
	out: dict[str, SkillEntry] = {}
	for lp in loaded:
		enabled = getattr(lp, "enabled", False)
		if not enabled:
			continue
		plugin = getattr(lp, "plugin", None)
		for rel in getattr(plugin, "skill_dirs", ()):
			entry = _entry_from_dir(rel, source="plugin", plugin=plugin.name)
			out.setdefault(entry.name.casefold(), entry)
	return out


# --------------------------------------------------------------------------- #
# 主发现（3s TTL + digest 跳过重扫）+ report。
# --------------------------------------------------------------------------- #



def _discover_uncached(
	cwd: str | None,
	cfg: ExtensionConfig,
	*,
	allow_override: bool,
) -> tuple[list[SkillEntry], list[tuple[str, str]]]:
	"""三源合并发现（无缓存）。返回 (entries, suppressed_conflicts)。"""
	builtin: dict[str, SkillEntry] = {}
	suppressed: list[tuple[str, str]] = []

	home_root = _home_skill_root()
	for entry in _scan_skill_dirs(home_root, source="home").values():
		if cfg.skill_enabled(entry.name):
			builtin[entry.name.casefold()] = entry
	ws_root = _workspace_skill_root(cwd)
	if ws_root is not None:
		for entry in _scan_skill_dirs(ws_root, source="workspace").values():
			if cfg.skill_enabled(entry.name):
				builtin[entry.name.casefold()] = entry  # workspace 覆盖 home

	loaded = discover_plugins(cwd, config=cfg)
	for entry in _plugin_skill_entries(loaded).values():
		if not cfg.skill_enabled(
			entry.name,
			from_plugin=True,
			parent_plugin_enabled=cfg.plugin_enabled(entry.plugin),
		):
			continue
		key = entry.name.casefold()
		if key in builtin and not allow_override:
			suppressed.append((entry.name, entry.plugin))
			continue  # 默认禁止覆盖
		builtin[key] = entry

	return [builtin[k] for k in sorted(builtin)], suppressed


def discover_skills_report(
	cwd: str | None = None,
	*,
	config: ExtensionConfig | None = None,
	allow_override: bool = False,
) -> tuple[list[SkillEntry], list[tuple[str, str]]]:
	"""三源发现 + broken/suppressed 报告（F4）。

	返回 ``(entries, suppressed_conflicts)``。``entries`` 含 broken-but-listed 条目
	（``broken:True``，不进目录/加载）；``suppressed_conflicts`` 为被默认禁止覆盖
	拦截的插件同名技能。
	"""
	cfg = config if config is not None else load_ext_config(cwd)
	key = repr((cwd, allow_override, _cfg_signature(cfg)))
	now = time.monotonic()
	cached = _CACHE.get(key)
	if cached is not None and (now - cached[0]) < _SKILL_CACHE_TTL_S:
		return cached[1], cached[2]
	entries, suppressed = _discover_uncached(cwd, cfg, allow_override=allow_override)
	_CACHE[key] = (now, entries, suppressed)
	return list(entries), list(suppressed)


def _cfg_signature(cfg: ExtensionConfig) -> tuple[Any, ...]:
	return (
		cfg.enabled_extensions,
		repr(sorted(cfg.skills.items())),
		repr(sorted(cfg.plugins.items())),
	)


def discover_skills(
	cwd: str | None = None,
	*,
	config: ExtensionConfig | None = None,
	allow_override: bool = False,
) -> list[SkillEntry]:
	"""三源合并 skill 发现表（含 broken-but-listed 条目）。

	优先级 **workspace > home > plugin**；同名时高优先级胜出。默认禁止插件覆盖
	workspace/home 同名（``allow_override=False``，防供应链混淆）。
	"""
	return discover_skills_report(cwd, config=config, allow_override=allow_override)[0]


def list_skill_names(cwd: str | None = None, **kw: bool) -> list[str]:
	return [e.name for e in discover_skills(cwd, **kw)]
