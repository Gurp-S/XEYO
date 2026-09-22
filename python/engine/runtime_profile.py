"""显式运行档案。

XEYO 以前主要通过一组 ``XEYO_*`` 环境变量表达产品模式、评测模式和
执行后端。环境变量仍保留为兼容入口，但 runtime 内部需要一个稳定对象来
回答「这次运行属于哪种档案」。本模块只描述事实和策略身份，不直接执行
权限或调度动作；这样可以先作为旁路观测面接入，再逐项把行为迁移到档案。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeProfile:
	"""一次 agent runtime 的显式产品/评测档案。

	字段是机器可读的运行事实。``profile_id`` 对稳定字段做哈希，供
	checkpoint、trace 和 TB metadata 归因；不把 API key、路径或会话 id 放入
	档案身份。
	"""

	name: str
	tool_surface: str = "full"
	permission_policy: str = "interactive-risk"
	multi_agent: bool = True
	human_interaction: bool = True
	execution_backend: str = "local"
	process_policy: str = "managed"
	deadline_policy: str = "soft"

	@property
	def profile_id(self) -> str:
		payload = json.dumps(
			self._identity_payload(),
			ensure_ascii=False,
			sort_keys=True,
			separators=(",", ":"),
		)
		return "profile:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

	def _identity_payload(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"tool_surface": self.tool_surface,
			"permission_policy": self.permission_policy,
			"multi_agent": self.multi_agent,
			"human_interaction": self.human_interaction,
			"execution_backend": self.execution_backend,
			"process_policy": self.process_policy,
			"deadline_policy": self.deadline_policy,
		}

	def to_dict(self) -> dict[str, Any]:
		out = dict(self._identity_payload())
		out["profile_id"] = self.profile_id
		return out

	@classmethod
	def from_name(cls, name: str) -> "RuntimeProfile":
		key = str(name or "").strip().lower().replace("_", "-")
		if key in {"terminal-bench", "terminal-bench-2", "terminal-bench-2.1", "tb2.1"}:
			return cls(
				name="terminal-bench-2.1",
				tool_surface="minimal",
				permission_policy="benchmark",
				multi_agent=False,
				human_interaction=False,
				execution_backend="docker",
				process_policy="timeout-map",
				deadline_policy="agent-timeout",
			)
		if key in {"ci", "continuous-integration"}:
			return cls(
				name="ci",
				tool_surface="minimal",
				permission_policy="noninteractive",
				multi_agent=False,
				human_interaction=False,
				execution_backend="local",
				process_policy="managed",
				deadline_policy="hard",
			)
		if key in {"remote", "ssh"}:
			return cls(
				name="remote",
				tool_surface="full",
				permission_policy="interactive-risk",
				multi_agent=True,
				human_interaction=True,
				execution_backend="ssh",
				process_policy="managed",
				deadline_policy="soft",
			)
		return cls(
			name="product-local",
			tool_surface="full",
			permission_policy="interactive-risk",
			multi_agent=True,
			human_interaction=True,
			execution_backend="local",
			process_policy="managed",
			deadline_policy="soft",
		)

	@classmethod
	def from_value(cls, value: Any) -> "RuntimeProfile":
		if isinstance(value, cls):
			return value
		if isinstance(value, Mapping):
			base = cls.from_name(str(value.get("name") or "product-local"))
			updates: dict[str, Any] = {}
			for field_name in (
				"name",
				"tool_surface",
				"permission_policy",
				"multi_agent",
				"human_interaction",
				"execution_backend",
				"process_policy",
				"deadline_policy",
			):
				if field_name in value:
					updates[field_name] = value[field_name]
			return replace(base, **updates)
		return cls.from_name(str(value or "product-local"))


def resolve_runtime_profile(
	value: Any = None,
	*,
	runtime: str | None = None,
) -> RuntimeProfile:
	"""解析显式档案；旧环境变量只作为兼容回退。"""
	if value is not None and str(value).strip():
		return RuntimeProfile.from_value(value)
	env = os.environ.get("XEYO_RUNTIME_PROFILE", "").strip()
	if env:
		return RuntimeProfile.from_name(env)
	if str(runtime or "").strip().lower() == "docker":
		# Docker 是执行后端，不等于 benchmark；TB adapter 必须显式传
		# terminal-bench-2.1，产品容器则保留产品权限/交互语义。
		base = RuntimeProfile.from_name("product-local")
		return replace(base, name="product-docker", execution_backend="docker")
	return RuntimeProfile.from_name("product-local")


__all__ = ["RuntimeProfile", "resolve_runtime_profile"]
