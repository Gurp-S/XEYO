"""插件 manifest 解析与校验。

契约（名称对齐主流 agent / MCP）：
``<root>/.xeyo/plugins/<name>/plugin.json``

.. code-block:: jsonc

	{
	  "name": "my-plugin",
	  "version": "0.1.0",
	  "description": "...",
	  "min_xeyo": "0.1.0",
	  "skills": ["skills/map"],          // 指向含 SKILL.md 的目录
	  "mcp_servers": [                    // MCP server 声明
	    {"id": "filesystem", "transport": "stdio", "command": "npx",
	     "args": [...], "env": {}, "auto_start": true,
	     "tools_policy": "outbound_ask"}
	  ],
	  "prompts": ["prompt.md"],           // 可选：注入 T_now
	  "enabled": true
	}

坏清单抛 :class:`ManifestError`；调用方应捕获并跳过该插件。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from extension.errors import ManifestError

# 允许的 MCP 权限分类：与 tools.meta PolicyKind 对齐（outbound_ask 为默认企业级）。
McpPolicy = Literal["always_allow", "outbound_ask", "ui_ask"]

# 生命周期钩子事件（子代理/UserPromptSubmit/PrePostCompact 预留）。
HookEvent = Literal[
	"PreToolUse",
	"PostToolUse",
	"PermissionRequest",
	"SessionStart",
	"SessionEnd",
]
#: 钩子失败策略：continue = 记入附件上下文放行；abort = 终止本轮/短路该工具。
HookFailPolicy = Literal["continue", "abort"]

# 版本号宽松匹配（0.1.0 / v0.1.0 / 0.1）。
_VERSION_RX = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", re.I)


def _parse_version(value: str) -> tuple[int, int, int]:
	m = _VERSION_RX.match((value or "").strip())
	if not m:
		return (0, 0, 0)
	parts = [int(g) for g in m.groups() if g is not None]
	parts += [0] * (3 - len(parts))
	return (parts[0], parts[1], parts[2])


def version_at_least(current: str, minimum: str) -> bool:
	"""``current >= minimum``（0.1.0-alpha 等后缀视为等于基版）。"""
	cur = _parse_version(current)
	need = _parse_version(minimum)
	return cur >= need


class McpServerSpec(BaseModel):
	"""MCP server 声明（本期仅 stdio；HTTP/SSE 预留）。"""

	id: str
	transport: Literal["stdio"] = "stdio"
	command: str
	args: list[str] = Field(default_factory=list)
	env: dict[str, str] = Field(default_factory=dict)
	#: 是否随会话创建自动 spawn；False 则仅注册工具 schema，不启动进程。
	auto_start: bool = True
	#: 权限分类；outbound_ask = 调用一律 ASK（企业级默认）。
	tools_policy: McpPolicy = "outbound_ask"
	#: 可选：显式给某个 tool 覆盖权限分类。
	tool_policies: dict[str, McpPolicy] = Field(default_factory=dict)

	@field_validator("id")
	@classmethod
	def _id_ok(cls, v: str) -> str:
		v = (v or "").strip()
		if not v or re.search(r"[^a-zA-Z0-9_.-]", v):
			raise ValueError("mcp server id must be [a-zA-Z0-9_.-]+")
		return v

	@field_validator("command")
	@classmethod
	def _command_ok(cls, v: str) -> str:
		if not (v or "").strip():
			raise ValueError("mcp command is required")
		return v.strip()


class HookSpec(BaseModel):
	"""一个生命周期钩子声明（脚本相对插件根；子进程执行）。

	结果三分：Success / FailedContinue / FailedAbort。PermissionRequest 未批准
	一律 fail-closed（DENY）。``timeout_s`` 失败按 ``fail_policy`` 归类。
	"""

	event: HookEvent
	command: str
	args: list[str] = Field(default_factory=list)
	timeout_s: float = 600.0
	fail_policy: HookFailPolicy = "continue"

	@field_validator("command")
	@classmethod
	def _command_ok(cls, v: str) -> str:
		s = (v or "").strip().replace("\\", "/")
		if not s:
			raise ValueError("hook command is required")
		if s.startswith("/") or ".." in s.split("/"):
			raise ValueError(f"hook command must be relative & confined: {s}")
		return s


class PluginManifest(BaseModel):
	"""一个插件的清单。"""

	name: str
	version: str = "0.0.0"
	description: str = ""
	min_xeyo: str = ""
	skills: list[str] = Field(default_factory=list)
	mcp_servers: list[McpServerSpec] = Field(default_factory=list)
	prompts: list[str] = Field(default_factory=list)
	hooks: list[HookSpec] = Field(default_factory=list)
	enabled: bool = True
	#: 来源元数据（本地路径 / github 等），企业级信任链用。
	source: str = ""
	source_type: str = "local"

	@field_validator("name")
	@classmethod
	def _name_ok(cls, v: str) -> str:
		v = (v or "").strip()
		if not v or re.search(r"[^a-zA-Z0-9_.-]", v):
			raise ValueError("plugin name must be [a-zA-Z0-9_.-]+")
		return v

	@field_validator("skills", "prompts")
	@classmethod
	def _clean_paths(cls, v: list[str]) -> list[str]:
		out: list[str] = []
		for p in v:
			s = (p or "").strip().replace("\\", "/")
			if not s:
				continue
			if s.startswith("/") or ".." in s.split("/"):
				raise ValueError(f"path must be relative & confined: {s}")
			out.append(s)
		return out

	@model_validator(mode="after")
	def _at_least_one(self) -> "PluginManifest":
		if not (self.skills or self.mcp_servers or self.prompts or self.hooks):
			raise ValueError(
				"plugin must declare at least one of skills / mcp_servers / prompts / hooks"
			)
		return self


@dataclass(frozen=True)
class Plugin:
	"""已加载且校验通过的插件（磁盘目录 + 解析后的 manifest）。"""

	name: str
	root: Path
	manifest: PluginManifest
	#: 从 manifest 解析出的 skill 相对目录 path（指向含 SKILL.md 的目录）。
	skill_dirs: tuple[Path, ...] = ()
	#: 提示文件绝对路径列表。
	prompt_paths: tuple[Path, ...] = ()


def _abs(plugin_root: Path, rel: str) -> Path:
	"""把 manifest 内相对路径解析为绝对路径，并确认在插件根内（防 .. 逃逸）。"""
	return (plugin_root / rel).resolve()


def load_manifest(plugin_root: Path) -> Plugin:
	"""读取并校验一个插件的 manifest；失败抛 :class:`ManifestError`。"""
	root = (plugin_root or Path(".")).expanduser().resolve()
	manifest_path = root / "plugin.json"
	if not manifest_path.is_file():
		raise ManifestError(f"missing plugin.json", name=root.name)
	try:
		raw = json.loads(manifest_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as e:
		raise ManifestError(f"bad plugin.json: {e}", name=root.name) from e
	try:
		m = PluginManifest.model_validate(raw)
	except Exception as e:  # pydantic ValidationError
		raise ManifestError(f"invalid manifest: {e}", name=root.name) from e

	skill_dirs: list[Path] = []
	for rel in m.skills:
		dirp = _abs(root, rel)
		# skill 目录必须含 SKILL.md；没有则该 skill 无效但插件可继续。
		if (dirp / "SKILL.md").is_file():
			skill_dirs.append(dirp)

	prompt_paths: list[Path] = []
	for rel in m.prompts:
		pp = _abs(root, rel)
		if pp.is_file():
			prompt_paths.append(pp)

	return Plugin(
		name=m.name,
		root=root,
		manifest=m,
		skill_dirs=tuple(skill_dirs),
		prompt_paths=tuple(prompt_paths),
	)
