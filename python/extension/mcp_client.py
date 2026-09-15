"""MCP stdio 客户端（XEYO 扩展层，T11）。

本模块实现一个*自包含*的 Model Context Protocol (MCP) 客户端，走 stdio
（JSON-RPC 2.0，换行分帧），可安全作为 XEYO 插件基础设施的底座。默认关闭
（扩展层仅在 ``.xeyo/settings.json`` 设置 ``enabled_extensions`` 时启用）；
单个坏服务器绝不能拖垮发现/启动流程（fail closed + skip-and-log）。

设计目标：

* **skip-and-log** — 生成/握手/列举失败的服务器只记日志并跳过；
  ``start()`` 绝不抛异常。
* **有界崩溃循环** — 指数退避重连 500ms -> 30s，单次故障最多
  ``MAX_RECONNECT_ATTEMPTS``（10）次；若上一次存活超过
  ``RESET_UPTIME_S`` 则重置换行预算。
* **不折叠工具名** — 两个服务器可暴露同名原始工具；每个工具获得唯一名
  ``mcp__<server_id>__<normalized_raw>__<12hex>``。
* **权限三向门禁不可绕过** — 动态工具经 ``tools.tool_registry.ToolRegistry``
  注册，默认 ``outbound_ask``（必 ASK）；仅 manifest 声明时才 ``always_allow``。
* **超时拆分** — 启动 30s / 单次工具调用 300s（常量上提）。
* **schema 清洗 + 5KB 分级降级**。
* **list_changed 整代替换**，冲突时回滚。
* **settings HMR** — 供配置层调用的断连+重连钩子。

缩进与 ``extension/`` 其余部分一致：tab。
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from engine.abort import AbortController
from permissions.filesystem import PermissionDecision
from permissions.policy import PolicyDecision
from tools.base_tool import ToolResult

_log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 提升到模块级、便于测试的调优常量（"超时拆分" + 退避边界）。
# --------------------------------------------------------------------------- #

#: 启动握手预算（initialize + 首次 tools/list），单位秒。
STARTUP_TIMEOUT_S = 30.0
#: Per tool call budget, seconds.
TOOL_TIMEOUT_S = 300.0
#: Base reconnect backoff (ms -> seconds).
BACKOFF_BASE_S = 0.5
#: Backoff ceiling.
BACKOFF_MAX_S = 30.0
#: Max reconnect attempts per outage.
MAX_RECONNECT_ATTEMPTS = 10
#: If a run survived longer than this, reset the backoff budget.
RESET_UPTIME_S = 30.0
#: Schema token budget (5KB layer), in bytes.
SCHEMA_BUDGET_BYTES = 5120
#: MCP protocol version we advertise.
MCP_PROTOCOL_VERSION = "2024-11-05"
#: Transport hardening: drop a single inbound line longer than this (bytes).
MAX_MCP_STDIO_LINE = 8 * 1024 * 1024  # 8 MiB
#: stderr ring-buffer length (human-readable logs, ``/mcp logs``).
STDERR_RING_SIZE = 100

# -- F2 可见性预算（P0b）------------------------------------------- #
#: 单工具 spec 上限（字节）：超限 → hidden（仍注册，幻觉调用走权限 ASK）。
MAX_TOOL_SCHEMA_BYTES = 8000
#: 每 server 工具 spec 总量上限（字节）：溢出部分 → hidden。
MAX_SERVER_SCHEMA_BYTES = 64000
#: 每 server 可见工具数兜底（env ``XEYO_MCP_TOOL_MAX_VISIBLE`` 覆盖，<=0 不设上限）。
DEFAULT_MAX_VISIBLE_TOOLS = 32
#: 注册名长度上限（字节）：超限截断 norm/server 段（12hex 身份钉保留）。
MAX_TOOL_NAME_BYTES = 128


def max_visible_tools() -> int:
	"""F2 cap 32 的 env 覆盖读取（非法值回默认；<=0 = 不设上限）。"""
	raw = (os.environ.get("XEYO_MCP_TOOL_MAX_VISIBLE") or "").strip()
	if not raw:
		return DEFAULT_MAX_VISIBLE_TOOLS
	try:
		return int(raw)
	except ValueError:
		return DEFAULT_MAX_VISIBLE_TOOLS


def tool_is_model_visible(raw_schema: Mapping[str, Any]) -> bool:
	"""F2 层②：server 声明 ``_meta.ui.visibility`` 不含 "model" → hidden。

	缺省（无 _meta/ui/visibility）→ 可见；声明即权威（server 自标注）。
	"""
	if not isinstance(raw_schema, Mapping):
		return True
	meta = raw_schema.get("_meta")
	if not isinstance(meta, dict):
		return True
	ui = meta.get("ui")
	if not isinstance(ui, dict):
		return True
	vis = ui.get("visibility")
	if vis is None:
		return True
	items = [vis] if isinstance(vis, str) else list(vis)
	return "model" in [str(v).strip().lower() for v in items]


class McpError(Exception):
	"""Base MCP error."""


class McpSpawnError(McpError):
	"""Subprocess failed to spawn."""


class McpTimeoutError(McpError):
	"""A request exceeded its timeout."""


class McpProtocolError(McpError):
	"""A malformed / unexpected JSON-RPC exchange."""


# --------------------------------------------------------------------------- #
# 工具名规范化 + 防碰撞命名。
# --------------------------------------------------------------------------- #

_RAW_NORM_RX = re.compile(r"[^a-z0-9._-]+")
#: env-name tokens considered secret-ish; stripped before merging the whitelist.
_SECRET_TOKENS = frozenset({"secret", "token", "password", "passwd", "pwd", "credential", "key"})


def _is_secret_env_name(name: str) -> bool:
	if not name:
		return False
	if name.upper().startswith("XEYO_"):
		return True
	tokens = re.split(r"[_\-.]+", name.lower())
	return any(token in _SECRET_TOKENS for token in tokens)


def normalize_raw_tool_name(raw: str) -> str:
	"""Lowercase + collapse runs of invalid chars to ``_`` for the name segment."""
	s = (raw or "").strip().lower()
	s = _RAW_NORM_RX.sub("_", s)
	s = s.strip("_")
	return s or "tool"


def _hash12(key: str) -> str:
	"""12-hex sha256 tag of a canonical key."""
	return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _humanize_spawn_error(server_id: str, command: str, exc: OSError) -> str:
	"""人话化 spawn 错误（仿 ``mcp_init_error_display``）：ENOENT → 「命令不存在」。"""
	code = getattr(exc, "errno", None)
	if code == 2 or (os.name == "nt" and code == 2):  # ENOENT
		return (
			f"cannot spawn mcp server {server_id}: 命令不存在 "
			f"(command={command!r})"
		)
	if code == 13:  # EACCES
		return f"cannot spawn mcp server {server_id}: 权限不足 (command={command!r})"
	return f"cannot spawn mcp server {server_id}: {exc}"


def mcp_tool_name(server_id: str, raw_name: str) -> str:
	"""Unique registered tool name: ``mcp__<server>__<normalized_raw>__<12hex>``.

	The 12-hex tag is keyed on ``server_id + raw_name`` so two servers exposing the
	same raw name, or two raw names that normalize identically, still never collide.

	F2（§F2）：注册名总长 ≤128 字节 —— 超限先截 norm 段（保 server 前缀与 hex 钉），
	仍超再截 server 段（norm 至少 1 字符）。截断是确定性的：同一 (server, raw)
	恒产出同一名字（指纹/授权对称性不受影响）。
	"""
	norm = normalize_raw_tool_name(raw_name)
	key = server_id + "\x00" + raw_name
	name = f"mcp__{server_id}__{norm}__{_hash12(key)}"
	over = len(name) - MAX_TOOL_NAME_BYTES  # 全段 ASCII，len == 字节数
	if over > 0:
		norm_budget = len(norm) - over
		if norm_budget >= 1:
			norm = norm[:norm_budget]
			name = f"mcp__{server_id}__{norm}__{_hash12(key)}"
		if len(name) > MAX_TOOL_NAME_BYTES:
			keep = MAX_TOOL_NAME_BYTES - 5 - 2 - 1 - 2 - 12  # mcp__ + __ + norm1 + __ + hex
			if keep >= 1:
				name = f"mcp__{server_id[:keep]}__{norm[:1]}__{_hash12(key)}"
	return name


# --------------------------------------------------------------------------- #
# spec / 配置面。
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class McpClientSpec:
	"""Runtime representation of one stdio MCP server declaration.

	Mirrors the manifest ``McpServerSpec`` fields we need (id, command, args, env,
	auto_start, tools_policy, tool_policies) plus the timeout split, without pulling
	in pydantic. Build it from a plugin manifest via :meth:`from_manifest`.
	"""

	id: str
	command: str
	args: tuple[str, ...] = ()
	env: dict[str, str] = field(default_factory=dict)
	auto_start: bool = True
	tools_policy: str = "outbound_ask"
	tool_policies: dict[str, str] = field(default_factory=dict)
	startup_timeout_s: float = STARTUP_TIMEOUT_S
	tool_timeout_s: float = TOOL_TIMEOUT_S
	#: 环境白名单：按名继承进程环境（无 ${VAR} 展开；``env`` 是字面 K/V）。
	env_vars: tuple[str, ...] = ()
	#: 按名引用的密钥环境变量（由 manager 从 ``os.environ`` 读取并按名注入）。
	bearer_token_env_var: str = ""
	#: env 策略：``scrub``（默认，strip 密钥/XEYO_*）+ ``minimal``（env_clear + allowlist）。
	env_mode: str = "scrub"
	#: true → 启动失败不挡会话、工具不进快照、挂 T_now 警告 + 审计。
	required: bool = False
	#: P1 elicitation 开关（P0a 仅承载默认 false）。
	elicit: bool = False
	#: 仅当显式 ``trust_annotations=true`` 才信任 server 的 readOnlyHint。
	trust_annotations: bool = False
	#: 实例级只读判定：manifest ``read_only_tools`` 显式声明（或 trust_annotations+readOnlyHint）。
	read_only_tools: tuple[str, ...] = ()
	#: ``None``=全部；否则只注册 ``enabled_tools`` 命名的 raw 工具（未勾选流程经权限 ASK）。
	enabled_tools: tuple[str, ...] | None = None
	#: per-tool 输出预算（字符）覆盖。
	output_token_limits: dict[str, int] = field(default_factory=dict)

	@classmethod
	def from_manifest(cls, manifest_spec: Any) -> "McpClientSpec":
		"""Adapt a ``manifest.McpServerSpec`` (pydantic) to this dataclass."""
		return cls(
			id=str(getattr(manifest_spec, "id", "") or ""),
			command=str(getattr(manifest_spec, "command", "") or ""),
			args=tuple(getattr(manifest_spec, "args", ()) or ()),
			env=dict(getattr(manifest_spec, "env", {}) or {}),
			auto_start=bool(getattr(manifest_spec, "auto_start", True)),
			tools_policy=str(getattr(manifest_spec, "tools_policy", "outbound_ask")),
			tool_policies=dict(getattr(manifest_spec, "tool_policies", {}) or {}),
		)


#: The only permitted policy classifications (mirror manifest.McpPolicy).
MCP_POLICIES = ("always_allow", "outbound_ask", "ui_ask")


def mcp_default_policy() -> str:
	"""Every dynamic MCP tool defaults to ``outbound_ask`` (hard rule: always ASK)."""
	return "outbound_ask"


def resolve_mcp_policy(spec: Any, raw_tool_name: str) -> str:
	"""Resolve the effective policy for one tool.

	Precedence: per-tool ``tool_policies[raw_name]`` -> server ``tools_policy`` ->
	``outbound_ask``. ``always_allow`` is honoured **only** when the manifest
	explicitly declares it.
	"""
	overrides = getattr(spec, "tool_policies", None) or {}
	if raw_tool_name in overrides:
		return str(overrides[raw_tool_name]) if overrides[raw_tool_name] in MCP_POLICIES else mcp_default_policy()
	server_policy = getattr(spec, "tools_policy", None) or ""
	if server_policy in MCP_POLICIES:
		return server_policy
	return mcp_default_policy()


def mcp_policy_decision(name: str, policy: str) -> PolicyDecision:
	"""The permission 3-way decision for a dynamic MCP tool.

	Used by the routing helper and by tests. ``always_allow`` -> ALLOW only when the
	manifest declared it; everything else defaults to ASK (``outbound_ask`` /
	``ui_ask``), i.e. the register-through-ToolRegistry path is never bypassed.
	"""
	if policy == "always_allow":
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="mcp_always_allow",
			matched_rule="mcp_always_allow",
		)
	rule = "mcp_ui_ask" if policy == "ui_ask" else "mcp_outbound_ask"
	return PolicyDecision(
		decision=PermissionDecision.ASK,
		reason="needs_confirmation",
		matched_rule=rule,
		prompt=f"Allow MCP tool {name}?",
	)


# --------------------------------------------------------------------------- #
# Schema 清洗 + 5KB 分层降级。
# --------------------------------------------------------------------------- #

def sanitize_tool_schema(raw: Mapping[str, Any], *, budget_bytes: int = SCHEMA_BUDGET_BYTES) -> dict[str, Any]:
	"""Convert an MCP tool object into the engine's ``{name, description, input_schema}`` shape.

	Only a fixed allow-list of fields survives (sanitise), and if the serialized size
	exceeds ``budget_bytes`` it is progressively degraded (tiered) to fit.
	"""
	mcp_input = raw.get("inputSchema") if isinstance(raw, Mapping) else None
	if not isinstance(mcp_input, dict):
		mcp_input = {"type": "object", "properties": {}}
	schema = {
		"name": str(raw.get("name") or ""),
		"description": str(raw.get("description") or ""),
		"input_schema": _degrade(mcp_input, budget_bytes),
	}
	if not schema["name"]:
		schema["name"] = "tool"
	return schema


def _degrade(obj: Any, budget_bytes: int) -> Any:
	"""Tiered JSON-schema degradation to fit ``budget_bytes``."""
	import copy

	current = copy.deepcopy(obj)
	if _size(current) <= budget_bytes:
		return current

	# 第 1 层：去掉所有面向人的 description。
	tier1 = _strip_keys(current, {"description"})
	if _size(tier1) <= budget_bytes:
		return tier1

	# 第 2 层：去掉可选噪音（defaults / examples / additionalProperties）。
	tier2 = _strip_keys(tier1, {"default", "examples", "additionalProperties", "enum"})
	if _size(tier2) <= budget_bytes:
		return tier2

	# 第 3 层：收敛为裸 object schema。
	return {"type": "object", "properties": {}}


def _size(obj: Any) -> int:
	try:
		return len(json.dumps(obj, ensure_ascii=False))
	except Exception:  # noqa: BLE001
		return 1 << 30


def _strip_keys(obj: Any, keys: set[str]) -> Any:
	if isinstance(obj, dict):
		return {
			k: _strip_keys(v, keys)
			for k, v in obj.items()
			if k not in keys
		}
	if isinstance(obj, list):
		return [_strip_keys(v, keys) for v in obj]
	return obj


# --------------------------------------------------------------------------- #
# 重连退避 500ms -> 30s，尝试次数有上限。
# --------------------------------------------------------------------------- #

class ReconnectBackoff:
	"""Exponential backoff with a per-outage attempt budget.

	``next_delay()`` returns the sleep for the next attempt and increments the
	attempt counter. When the counter reaches ``max_attempts`` the policy is
	``exhausted`` and the caller gives up (no infinite hot loop). ``maybe_reset_for_uptime``
	re-arm a fresh budget when the previous run survived longer than the reset
	threshold.
	"""

	def __init__(
		self,
		*,
		base: float = BACKOFF_BASE_S,
		maximum: float = BACKOFF_MAX_S,
		max_attempts: int = MAX_RECONNECT_ATTEMPTS,
		reset_uptime: float = RESET_UPTIME_S,
	) -> None:
		self.base = float(base)
		self.maximum = float(maximum)
		self.max_attempts = int(max_attempts)
		self.reset_uptime = float(reset_uptime)
		self._attempts = 0

	@property
	def attempts(self) -> int:
		"""How many reconnect attempts have been made so far in this outage."""
		return self._attempts

	def next_delay(self) -> float:
		"""Return the delay for the upcoming attempt and consume one attempt."""
		delay = min(self.base * (2.0 ** self._attempts), self.maximum)
		self._attempts += 1
		return delay

	def exhausted(self) -> bool:
		return self._attempts >= self.max_attempts

	def reset(self) -> None:
		self._attempts = 0

	def maybe_reset_for_uptime(self, uptime: float) -> bool:
		"""If the previous run survived >= reset_uptime, reset the budget. Returns True if reset."""
		if uptime >= self.reset_uptime:
			self.reset()
			return True
		return False


# --------------------------------------------------------------------------- #
# 传输抽象（可打桩的进程接口）。
# --------------------------------------------------------------------------- #

@runtime_checkable
class McpTransport(Protocol):
	"""The process boundary. Tests inject a fake; production uses :class:`StdioMcpTransport`."""

	def spawn(self) -> None:
		"""Start the server subprocess. Raises McpSpawnError on failure."""
		...

	def send(self, message: dict[str, Any]) -> None:
		"""Write one JSON-RPC message to the server stdin."""
		...

	def recv(self, timeout: float | None = None) -> dict[str, Any] | None:
		"""Read one JSON-RPC message. Returns None on idle timeout / EOF."""
		...

	def alive(self) -> bool:
		"""Whether the process is currently alive."""
		...

	def wait(self, timeout: float | None = None) -> int | None:
		"""Exit code (or None if still running after timeout)."""
		...

	def close(self) -> None:
		"""Tear down the subtree."""
		...


def _resolve_bearer_token(name: str) -> dict[str, str]:
	"""按 ``bearer_token_env_var`` 名从进程环境取密钥并回写同名 K/V。

	不做 ${VAR} 展开：整名即密钥源，若进程环境缺该名则返回空（宁可 no-op，
	绝不把空串/明文密钥写进 spec）。密钥按名引用、不落盘明文。
	"""
	name = (name or "").strip()
	if not name:
		return {}
	value = os.environ.get(name)
	if not value:
		return {}
	return {name: value}


def sanitize_env(
	whitelist: Mapping[str, str] | None = None,
	*,
	env_vars: Mapping[str, str] | None = None,
	bearer_token_env_var: str = "",
	env_mode: str = "scrub",
) -> dict[str, str]:
	"""Build the subprocess env for one stdio server (container hygiene).

	- ``scrub`` (default): strip ``XEYO_*`` / secret-ish vars, then merge the literal
	  ``whitelist`` (spec ``env``) and the ``env_vars`` allowlist on top.
	- ``minimal``: ``env_clear`` + allowlist (``env_vars`` + literal ``env``) only.
	- ``bearer_token_env_var``: resolve by name and inject (overrides secret-strip).

	No ``${VAR}`` expansion: only an explicit, by-name allowlist / bearer token is
	forwarded. Passing ``whitelist`` as positional keeps the legacy signature.
	"""
	av = dict(env_vars or {})
	out: dict[str, str] = {}
	if env_mode == "minimal":
		# env_clear + 白名单：仅保留 env_vars 名称（+ 字面 env）。
		for name in (av or {}):
			val = os.environ.get(name)
			if val is not None:
				out[str(name)] = str(val)
	else:
		for k, v in os.environ.items():
			if _is_secret_env_name(k):
				continue
			out[str(k)] = str(v)
		if av:
			for name, _val in av.items():
				actual = os.environ.get(name)
				if actual is not None:
					out[str(name)] = str(actual)
	if whitelist:
		out.update({str(k): str(v) for k, v in whitelist.items()})
	# bearer token 按名注入（最严胜出：显式密钥覆盖 strip）。
	out.update(_resolve_bearer_token(bearer_token_env_var))
	return out


def _kill_tree(proc: subprocess.Popen | None, job_handle: int | None) -> None:
	"""Best-effort subtree kill.

	Tries the Windows Job Object ``TerminateJobObject`` first (via ctypes), then
	falls back to ``taskkill /T /F``, then to ``proc.terminate()``. On POSIX uses
	``process_group`` if available.
	"""
	if proc is None:
		return
	if job_handle:
		try:
			import ctypes

			ctypes.windll.kernel32.TerminateJobObject(job_handle, 1)
			return
		except Exception:  # noqa: BLE001
			job_handle = None
	if os.name == "nt":
		try:
			subprocess.call(
				["taskkill", "/T", "/F", "/PID", str(proc.pid)],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			return
		except Exception:  # noqa: BLE001
			pass
	try:
		proc.terminate()
	except Exception:  # noqa: BLE001
		pass


class StdioMcpTransport:
	"""Real subprocess stdio transport with Windows-subtree handling."""

	def __init__(self, spec: McpClientSpec, *, logger: Any = None) -> None:
		self._spec = spec
		self._logger = logger or _log
		self._proc: subprocess.Popen | None = None
		self._reader: threading.Thread | None = None
		self._stderr_reader: threading.Thread | None = None
		self._inbound: queue.Queue[dict | None] = queue.Queue()
		self._send_lock = threading.Lock()
		self._job_handle: int | None = None
		self._closed = False
		#: stderr 环形缓冲（100 行），供 /mcp logs 人话化 / 排障。
		self._stderr_ring: collections.deque[str] = collections.deque(
			maxlen=STDERR_RING_SIZE
		)

	@property
	def stderr_lines(self) -> tuple[str, ...]:
		"""最近 <STDERR_RING_SIZE> 行 stderr（只读副本）。"""
		return tuple(self._stderr_ring)

	def spawn(self) -> None:
		"""Spawn the server subprocess and attach its stdout/stderr reader threads."""
		if self._proc is not None and self._proc.poll() is None:
			return  # already running
		cmd = [self._spec.command, *self._spec.args]
		env = sanitize_env(
			self._spec.env,
			env_vars={n: "" for n in self._spec.env_vars},
			bearer_token_env_var=self._spec.bearer_token_env_var,
			env_mode=self._spec.env_mode,
		)
		creationflags = 0
		if os.name == "nt":
			creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
		try:
			self._proc = subprocess.Popen(
				cmd,
				stdin=subprocess.PIPE,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				env=env,
				text=True,
				encoding="utf-8",
				errors="replace",
				bufsize=1,
				creationflags=creationflags,
			)
		except OSError as e:
			raise McpSpawnError(_humanize_spawn_error(self._spec.id, self._spec.command, e)) from e
		except ValueError as e:
			raise McpSpawnError(
				f"cannot spawn mcp server {self._spec.id} (command {self._spec.command!r}): {e}"
			) from e
		self._job_handle = self._assign_job(self._proc)
		self._reader = threading.Thread(target=self._read_loop, daemon=True)
		self._reader.start()
		self._stderr_reader = threading.Thread(target=self._read_stderr_loop, daemon=True)
		self._stderr_reader.start()

	def _assign_job(self, proc: subprocess.Popen) -> int | None:
		"""Try to assign the child to a Job Object we can kill later (Windows best-effort).

		If Job Objects are unavailable (or nested-job constraints reject it) we return
		None and fall back to ``taskkill /T`` during teardown. This is a safe fallback
		and is not asserted on this host (see the report).
		"""
		if os.name != "nt":
			return None
		try:
			import ctypes
			from ctypes import wintypes

			JOBOBJECT_EXTENDED_LIMIT_INFORMATION = type(
				"JOBOBJECT_EXTENDED_LIMIT_INFORMATION",
				(ctypes.Structure,),
				{"_fields_": [
					("PerProcessUserTimeLimit", ctypes.c_longlong),
					("PerJobUserTimeLimit", ctypes.c_longlong),
					("LimitFlags", wintypes.DWORD),
					("MinWorkingSetSize", ctypes.c_size_t),
					("MaxWorkingSetSize", ctypes.c_size_t),
					("ActiveProcessLimit", wintypes.DWORD),
					("Affinity", ctypes.c_size_t),
					("PriorityClass", wintypes.DWORD),
					("SchedulingClass", wintypes.DWORD),
				]},
			)
			kernel32 = ctypes.windll.kernel32
			job = kernel32.CreateJobObjectW(None, None)
			if not job:
				return None
			info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
			info.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
			kernel32.SetInformationJobObject(
				job, 9, ctypes.byref(info), ctypes.sizeof(info)
			)
			handle = int(proc._handle)  # noqa: SLF001
			if not kernel32.AssignProcessToJobObject(job, handle):
				kernel32.CloseHandle(job)
				return None
			return int(job)
		except Exception:  # noqa: BLE001
			return None

	def send(self, message: dict[str, Any]) -> None:
		if self._proc is None or self._proc.stdin is None:
			raise McpProtocolError(f"mcp server {self._spec.id} stdin not available")
		line = json.dumps(message, ensure_ascii=False) + "\n"
		with self._send_lock:
			try:
				self._proc.stdin.write(line)
				self._proc.stdin.flush()
			except (BrokenPipeError, OSError, ValueError) as e:
				raise McpProtocolError(f"mcp server {self._spec.id} write failed: {e}") from e

	def recv(self, timeout: float | None = None) -> dict[str, Any] | None:
		try:
			return self._inbound.get(timeout=timeout if timeout is not None else 0.25)
		except queue.Empty:
			return None

	def alive(self) -> bool:
		return bool(self._proc is not None and self._proc.poll() is None)

	def wait(self, timeout: float | None = None) -> int | None:
		if self._proc is None:
			return None
		try:
			return self._proc.wait(timeout=timeout)
		except subprocess.TimeoutExpired:
			return None

	def _read_loop(self) -> None:
		proc = self._proc
		if proc is None or proc.stdout is None:
			return
		for raw in proc.stdout:
			raw = raw.strip()
			if not raw:
				continue
			if len(raw) > MAX_MCP_STDIO_LINE:
				# 8MB 单行丢弃（拒绝服务防护）：记一次，跳过不解析。
				self._logger.warning(
					"mcp server %s dropped %d-byte line (> %d)",
					self._spec.id,
					len(raw),
					MAX_MCP_STDIO_LINE,
				)
				continue
			try:
				msg = json.loads(raw)
			except json.JSONDecodeError:
				continue
			self._inbound.put(msg)
		self._inbound.put(None)  # EOF marker

	def _read_stderr_loop(self) -> None:
		"""捕获 stderr → logger + 100 行环形缓冲（人话化排障）。"""
		proc = self._proc
		if proc is None or proc.stderr is None:
			return
		for raw in proc.stderr:
			line = raw.rstrip("\n")
			if not line:
				continue
			self._stderr_ring.append(line)
			self._logger.warning("mcp server %s stderr: %s", self._spec.id, line)

	def close(self) -> None:
		if self._closed:
			return
		self._closed = True
		_kill_tree(self._proc, self._job_handle)
		if self._proc is not None:
			for stream in (
				self._proc.stdin,
				self._proc.stdout,
				self._proc.stderr,
			):
				try:
					if stream:
						stream.close()
				except Exception:  # noqa: BLE001
					pass
		if self._reader is not None:
			self._reader.join(timeout=1.0)
		if self._stderr_reader is not None:
			self._stderr_reader.join(timeout=1.0)
		self._proc = None
		self._reader = None
		self._stderr_reader = None


# --------------------------------------------------------------------------- #
# stdio 客户端：JSON-RPC 驱动、重连、工具列表生成。
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class McpGeneration:
	"""A snapshot of one server's tool list + whether it was applied."""

	generation: int
	tools: Mapping[str, dict]  # tool_name (mcp__..) -> raw MCP schema dict
	applied: bool = True
	rolled_back: bool = False


class McpStdioClient:
	"""Drives one stdio MCP server living behind a :class:`McpTransport`."""

	def __init__(
		self,
		spec: McpClientSpec,
		*,
		transport_factory: Any = None,
		logger: Any = None,
		sleep: Any = time.sleep,
		clock: Any = time.monotonic,
	) -> None:
		self.spec = spec
		self._log = logger or _log
		self._sleep = sleep
		self._clock = clock
		if transport_factory is None:
			self._transport: McpTransport = StdioMcpTransport(spec, logger=self._log)
		else:
			self._transport = transport_factory(spec, logger=self._log)
		self._next_id = 1
		self._tools: dict[str, dict] = {}
		self._generation = 0
		self._ready = False
		self._server_info: dict[str, Any] = {}
		self._protocol_version = MCP_PROTOCOL_VERSION
		self._backoff = ReconnectBackoff()
		self._spawn_time: float | None = None

	@property
	def ready(self) -> bool:
		return self._ready

	@property
	def generation(self) -> int:
		return self._generation

	def tool_schemas(self) -> Mapping[str, dict]:
		"""Current generation: tool_name -> raw MCP schema (name/inputSchema)."""
		return dict(self._tools)

	def current_generation(self) -> McpGeneration:
		"""Snapshot of the in-memory tool list without a fresh fetch."""
		return McpGeneration(self._generation, dict(self._tools), applied=True)

	# -- 生命周期（lifecycle） ----------------------------------------------------------

	def start(self, *, fetch: bool = True, force: bool = False) -> bool:
		"""生成子进程 + 握手 + 列举工具。绝不抛异常（skip-and-log）。

		服务器就绪返回 True；被跳过则返回 False（auto_start 关、
		生成失败、握手/列举失败、重连次数耗尽）。
		"""
		if self._ready:
			return True
		if not self.spec.auto_start and not force:
			self._log.debug(
				"mcp server %s auto_start=%s; not spawning (schemas only)",
				self.spec.id,
				self.spec.auto_start,
			)
			return False
		try:
			self._spawn_and_init(fetch=fetch)
			return True
		except McpError as e:
			self._log.warning(
				"mcp server %s failed to start, skipping: %s", self.spec.id, e
			)
			return False

	def stop(self) -> None:
		self._ready = False
		try:
			self._transport.close()
		finally:
			self._log.info("mcp server %s stopped", self.spec.id)

	def reconnect(self, *, fetch: bool = True) -> bool:
		"""Settings HMR hook: disconnect + reconnect. Returns True on success."""
		self.stop()
		return self.start(fetch=fetch, force=True)

	def _spawn_and_init(self, *, fetch: bool = True) -> None:
		self._transport.spawn()  # raises McpSpawnError
		self._handshake()
		self._spawn_time = self._clock()
		if fetch:
			gen = self.reload_tools(fetch=True)
			if not gen.applied:
				raise McpProtocolError(
					f"mcp server {self.spec.id} initial tools/list failed"
				)
		self._ready = True

	# -- JSON-RPC -----------------------------------------------------------

	def _handshake(self) -> None:
		result = self._request(
			"initialize",
			{
				"protocolVersion": MCP_PROTOCOL_VERSION,
				"capabilities": {},
				"clientInfo": {"name": "xeyo-mcp-client", "version": "0.1.0"},
			},
			timeout=self.spec.startup_timeout_s,
		)
		self._protocol_version = str(result.get("protocolVersion") or MCP_PROTOCOL_VERSION)
		self._server_info = dict(result.get("serverInfo") or {})
		self._notify("notifications/initialized", {})

	def _request(
		self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
	) -> Any:
		timeout = float(timeout) if timeout is not None else self.spec.tool_timeout_s
		req_id = self._next_id
		self._next_id += 1
		self._transport.send(
			{"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
		)
		deadline = self._clock() + timeout
		while True:
			remaining = deadline - self._clock()
			if remaining <= 0:
				raise McpTimeoutError(
					f"mcp request {method} timed out after {timeout}s"
				)
			resp = self._transport.recv(min(remaining, 0.25))
			if resp is None:
				if not self._transport.alive():
					raise McpProtocolError(
						f"mcp server {self.spec.id} exited during {method}"
					)
				continue
			# 通知（无 id）-> 直接分发；继续循环等待本次响应。
			if "id" not in resp:
				self._dispatch_notification(resp)
				continue
			if resp.get("id") == req_id:
				if "error" in resp and resp["error"] is not None:
					raise McpError(f"mcp {method} error: {resp['error']}")
				if "result" in resp:
					return resp["result"]
				raise McpProtocolError(f"mcp {method} missing result")

	def _notify(self, method: str, params: dict[str, Any]) -> None:
		self._transport.send(
			{"jsonrpc": "2.0", "method": method, "params": params}
		)

	def _dispatch_notification(self, resp: dict[str, Any]) -> None:
		method = resp.get("method")
		if method == "notifications/tools/list_changed":
			self._log.info(
				"mcp server %s tools/list_changed; reloading generation", self.spec.id
			)
			try:
				self.reload_tools(fetch=True)
			except McpError as e:
				self._log.warning(
					"mcp server %s list_changed reload failed: %s", self.spec.id, e
				)

	# -- 工具列表（整代替换） ----------------------------

	def reload_tools(
		self, *, fetch: bool = True, reserved_names: frozenset[str] = frozenset()
	) -> McpGeneration:
		"""Fetch ``tools/list`` and replace the whole generation.

		Failure semantics (skip-and-log / fail-closed):
		* fetch error -> keep the old generation (``applied=False``).
		* registration conflict (a new name is already reserved by another server, or
		  two tools map to the same name) -> roll back the whole generation.
		"""
		if not fetch:
			return McpGeneration(self._generation, dict(self._tools), applied=False)
		try:
			result = self._request("tools/list", {}, timeout=self.spec.startup_timeout_s)
		except McpError as e:
			self._log.warning(
				"mcp server %s tools/list failed: %s; keeping generation %s",
				self.spec.id,
				e,
				self._generation,
			)
			return McpGeneration(self._generation, dict(self._tools), applied=False)
		raw_tools = result.get("tools") or []
		new: dict[str, dict] = {}
		for t in raw_tools:
			if not isinstance(t, dict):
				continue
			raw_name = str(t.get("name") or "").strip()
			if not raw_name:
				continue
			name = mcp_tool_name(self.spec.id, raw_name)
			if name in new:
				# 两个原始名在本代内折叠成同一个工具名。
				self._log.warning(
					"mcp server %s generation conflict on %s; rolling back",
					self.spec.id,
					name,
				)
				return McpGeneration(
					self._generation, dict(self._tools), applied=False, rolled_back=True
				)
			new[name] = t
		overlap = sorted(set(new) & set(reserved_names))
		if overlap:
			self._log.warning(
				"mcp server %s generation conflict (reserved=%s); rolling back",
				self.spec.id,
				overlap,
			)
			return McpGeneration(
				self._generation, dict(self._tools), applied=False, rolled_back=True
			)
		self._tools = new
		self._generation += 1
		return McpGeneration(self._generation, dict(new), applied=True)

	# -- 工具执行 ------------------------------------------------------

	def _ensure_running(self, *, fetch: bool = False) -> bool:
		"""Bounded reconnect loop. Returns True if connected, False after exhausting."""
		if self._ready and self._transport.alive():
			return True
		if self._backoff.exhausted():
			return False
		lost_uptime = (self._clock() - self._spawn_time) if self._spawn_time else 0.0
		if self._backoff.maybe_reset_for_uptime(lost_uptime):
			self._log.info(
				"mcp server %s was up %.1fs; resetting backoff budget", self.spec.id, lost_uptime
			)
		while not self._backoff.exhausted():
			delay = self._backoff.next_delay()
			self._log.info(
				"mcp server %s reconnect attempt %d/%d in %.1fs",
				self.spec.id,
				self._backoff.attempts,
				self._backoff.max_attempts,
				delay,
			)
			self._sleep(delay)
			try:
				self._transport.spawn()
				self._handshake()
				self._spawn_time = self._clock()
				if fetch:
					self.reload_tools(fetch=True)
				self._ready = True
				# 这里不要重置预算：先连上随即死掉的服务器
				# （存活 < reset_uptime）必须继续消耗单次故障预算，因此
				# 快速崩溃循环会在 max_attempts 次后终止。预算只能
				# 在运行足够久后由 maybe_reset_for_uptime() 重新装填。
				return True
			except (McpSpawnError, McpTimeoutError, McpProtocolError) as e:
				self._log.warning(
					"mcp server %s reconnect attempt failed: %s", self.spec.id, e
				)
		self._log.error("mcp server %s reconnect exhausted; giving up", self.spec.id)
		return False

	def call_tool(
		self, raw_name: str, arguments: dict[str, Any] | None = None, *, timeout: float | None = None
	) -> ToolResult:
		"""Invoke ``tools/call`` on the server and deserialize to :class:`ToolResult`."""
		if not (self._ready and self._transport.alive()):
			if not self._ensure_running(fetch=False):
				raise McpError(f"mcp server {self.spec.id} not connected")
		result = self._request(
			"tools/call",
			{"name": raw_name, "arguments": arguments or {}},
			timeout=timeout if timeout is not None else self.spec.tool_timeout_s,
		)
		return _result_from_mcp_call(result)

	def list_resources(
		self, *, cursor: str | None = None, timeout: float | None = None
	) -> dict[str, Any]:
		"""F6b：``resources/list``（分页）→ ``{"resources": [...], "nextCursor"?}``。

		server 不支持 resources 能力 → JSON-RPC error → 调用方（网关）转 error 结果。
		"""
		if not (self._ready and self._transport.alive()):
			if not self._ensure_running(fetch=False):
				raise McpError(f"mcp server {self.spec.id} not connected")
		params: dict[str, Any] = {}
		if cursor:
			params["cursor"] = cursor
		result = self._request(
			"resources/list",
			params,
			timeout=timeout if timeout is not None else self.spec.tool_timeout_s,
		)
		return result if isinstance(result, dict) else {}

	def read_resource(self, uri: str, *, timeout: float | None = None) -> dict[str, Any]:
		"""F6b：``resources/read``（按 uri）→ ``{"contents": [...]}``。"""
		if not (self._ready and self._transport.alive()):
			if not self._ensure_running(fetch=False):
				raise McpError(f"mcp server {self.spec.id} not connected")
		result = self._request(
			"resources/read",
			{"uri": uri},
			timeout=timeout if timeout is not None else self.spec.tool_timeout_s,
		)
		return result if isinstance(result, dict) else {}


def _image_data_url(mime: str, data: str) -> str:
	"""MCP ``image`` content block → ``data:<mime>;base64,<data>`` data URL."""
	mime = (mime or "image/png").strip()
	return f"data:{mime};base64,{data}"


def _result_from_mcp_call(result: Any) -> ToolResult:
	"""Deserialize an MCP ``tools/call`` result into a :class:`ToolResult`.

	- ``text`` blocks → ``content``（维持现状）。
	- ``image`` blocks → ``ToolResult.images``（data URL；vision 门控在
	  ``McpTool`` 执行层按 ``apply_read_vision`` 能力开关决定保留/降级占位）。
	- ``resource`` blocks → ``metadata["_mcp_resources"]``（供 spill 落盘 + 路径引用）。
	"""
	if not isinstance(result, dict):
		return ToolResult(
			content=f"mcp tools/call returned non-object: {result!r}", is_error=True
		)
	is_error = bool(result.get("isError", False))
	content = result.get("content") or []
	texts: list[str] = []
	images: list[str] = []
	resources: list[dict[str, Any]] = []
	for block in content:
		if not isinstance(block, dict):
			continue
		bt = block.get("type")
		if bt == "text":
			texts.append(str(block.get("text") or ""))
		elif bt == "resource":
			res = block.get("resource") or {}
			if isinstance(res, dict):
				resources.append(dict(res))
			else:
				texts.append(str(block.get("text") or ""))
		elif bt == "image":
			data = str(block.get("data") or "")
			if data:
				images.append(_image_data_url(str(block.get("mimeType") or ""), data))
			else:
				texts.append(f"[image data:{block.get('mimeType')}]")
	body = "\n".join(texts) if texts else (str(result.get("text") or ""))
	meta: dict[str, Any] = {}
	if resources:
		meta["_mcp_resources"] = resources
	return ToolResult(content=body or "ok", is_error=is_error, images=images or None, metadata=meta or None)


# --------------------------------------------------------------------------- #
# 工具适配器（Tool 协议）+ 为一代构建工具。
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# 工具适配器（Tool 协议）+ 内容融合（F6a）。
# --------------------------------------------------------------------------- #

def _mcp_session_id() -> str:
	"""从会话级 workspace 上下文取 session_id（spill 命名空间用）。"""
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		return (ctx.session_id if ctx is not None else "") or ""
	except Exception:  # noqa: BLE001
		return ""


def _audit_mcp_call(server_id: str, raw_name: str, is_error: bool, duration_ms: int, error: str | None) -> None:
	"""写入端保证的 MCP 审计（F16 硬字段：server/raw_tool/duration/is_error）。"""
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"mcp.tool.call",
			server=server_id,
			raw_tool=raw_name,
			duration_ms=duration_ms,
			is_error=is_error,
			error=(error or "")[:500],
		)
	except Exception:  # noqa: BLE001 — 审计失败不阻断调用
		logging.getLogger(__name__).debug("mcp.tool.call audit failed", exc_info=True)


def _finalize_mcp_result(
	result: ToolResult,
	*,
	apply_vision: bool,
	session_id: str,
) -> ToolResult:
	"""F6a 内容融合：image 块视觉门控 + resource 块 spill 落盘。

	- 视觉关（``apply_read_vision`` 能力开关 false）→ image 降级为占位文本，
	  ``images`` 置空（不再进视觉链路）。
	- resource 块 → ``spill`` 落盘 + 路径引用（模型可见路径，可 Read 回读）。
	"""
	meta = dict(result.metadata or {})
	images = list(result.images or [])
	resources = meta.pop("_mcp_resources", None)
	content = result.content or ""
	if images and not apply_vision:
		content = (
			(content.rstrip() + "\n" if content else "")
			+ "[image 块已返回，但当前模型不支持视觉输入；已降级为占位。]"
		)
		images = []
	if resources:
		for res in resources:
			uri = str(res.get("uri") or "")
			res_text = str(res.get("text") or res.get("blob") or "")
			path: str | None = None
			if res_text:
				try:
					from tools.spill import save_text

					ref = save_text(session_id or "mcp", res_text)
					path = ref.path
				except Exception:  # noqa: BLE001 — spill 失败：路径引用降级
					path = None
			if path:
				content += f"\n[resource {uri} spilled: {path} — use Read to continue]"
			else:
				content += f"\n[resource {uri}]"
	final_meta = dict(meta)
	if images:
		final_meta["has_images"] = True
	if resources:
		final_meta["has_resources"] = True
	return ToolResult(
		content=content or "ok",
		is_error=result.is_error,
		images=images or None,
		metadata=final_meta or None,
	)


class McpTool:
	"""A dynamic MCP tool exposed through :class:`ToolRegistry`.

	It carries the unique ``mcp__<server>__<name>__<12hex>`` name and a sanitized
	schema, and forwards execution to the owning client. Permission is *not* checked
	here — the registry's 3-way gate decides (default ``outbound_ask``).

	``is_read_only``/``is_concurrency_safe`` are **instance-level** (F3): they are
	True only when the manifest declares ``read_only_tools`` (or
	``trust_annotations`` + server ``readOnlyHint``), so readonly_gate / Plan mode /
	early speculative batch automatically apply.
	"""

	_id_counter = 0

	def __init__(
		self,
		client: McpStdioClient,
		spec: McpClientSpec,
		*,
		server_id: str,
		raw_name: str,
		tool_name: str,
		raw_schema: Mapping[str, Any],
		policy: str,
		read_only: bool = False,
		concurrency_safe: bool = False,
		apply_vision: bool = True,
		output_budget: int | None = None,
	) -> None:
		self._client = client
		self._spec = spec
		self.server_id = server_id
		self.raw_name = raw_name
		self.name = tool_name
		self._raw_schema = dict(raw_schema)
		self._policy = policy
		self._sanitized = sanitize_tool_schema(raw_schema)
		self._read_only = bool(read_only)
		self._concurrency_safe = bool(concurrency_safe)
		self._apply_vision = bool(apply_vision)
		self._output_budget = output_budget
		#: F2（P0b）：normal=进 schemas；hidden=仅注册不进 schemas。
		#: 由 manager 注册期统一判定（勾选/_meta/cap/尺寸三层）；实例默认 normal。
		self.exposure = "normal"
		#: F2.5 移除→DENY 门：manager 注入的「此刻是否可用」探针（None=不设门）。
		self.enabled_probe: Any = None
		McpTool._id_counter += 1
		self._tool_id = McpTool._id_counter

	@property
	def policy(self) -> str:
		return self._policy

	@property
	def read_only(self) -> bool:
		return self._read_only

	@property
	def concurrency_safe(self) -> bool:
		return self._concurrency_safe

	@property
	def output_token_limit(self) -> int | None:
		return self._output_budget

	#: registry._apply_output_budget 读的 T1 seam 名（实例级覆盖优先于 ToolMeta）。
	@property
	def output_budget(self) -> int | None:
		return self._output_budget

	@property
	def raw_schema(self) -> Mapping[str, Any]:
		return dict(self._raw_schema)

	def schema(self) -> dict[str, Any]:
		# schema 必须以注册名（mcp__server__raw__hex）呈现，模型才能按此名调用
		# （dispatch 以 tool.name 为键）；不能用 raw 工具名（会跨 server 冲突）。
		out = dict(self._sanitized)
		out["name"] = self.name
		return out

	def is_read_only(self) -> bool:
		"""Instance-level read-only flag（F3）。"""
		return self._read_only

	def is_concurrency_safe(self) -> bool:
		"""Instance-level concurrency flag（F3）。"""
		return self._concurrency_safe

	async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
		if abort is not None:
			abort.raise_if_aborted()
		started = time.monotonic()
		try:
			result = await asyncio.to_thread(
				self._client.call_tool, self.raw_name, input or {}
			)
		except McpError as e:
			# fail-closed：断连 / 崩溃的服务器返回错误结果，而不是
			# 让工具循环崩溃（与 skip-and-log 哲学一致）。
			_audit_mcp_call(self.server_id, self.raw_name, True, int((time.monotonic() - started) * 1000), str(e))
			return ToolResult(
				content=f"MCP tool {self.raw_name} error: {e}", is_error=True
			)
		final = _finalize_mcp_result(
			result,
			apply_vision=self._apply_vision,
			session_id=_mcp_session_id(),
		)
		_audit_mcp_call(self.server_id, self.raw_name, bool(final.is_error), int((time.monotonic() - started) * 1000), None)
		return final


def spec_read_only(spec: Any, raw_name: str, *, raw_schema: Mapping[str, Any] | None = None) -> bool:
	"""F3 实例级只读判定：manifest ``read_only_tools`` 显式声明，
	或 ``trust_annotations`` + server ``readOnlyHint``（且非 destructive）。"""
	declared = tuple(getattr(spec, "read_only_tools", ()) or ())
	if raw_name in declared:
		return True
	if not bool(getattr(spec, "trust_annotations", False)):
		return False
	if raw_schema is None:
		return False
	ann = raw_schema.get("annotations") or {}
	if not isinstance(ann, dict):
		return False
	if ann.get("readOnlyHint") and not ann.get("destructiveHint"):
		return True
	return False


def spec_output_budget(spec: Any, raw_name: str) -> int | None:
	"""per-tool 输出预算覆盖（字符）；None=默认。"""
	limits = getattr(spec, "output_token_limits", None) or {}
	val = limits.get(raw_name)
	try:
		return int(val) if val is not None else None
	except (TypeError, ValueError):
		return None


def spec_tool_enabled(spec: Any, raw_name: str) -> bool:
	"""F2 层①（勾选）：``enabled_tools`` None=全部；否则命中才可见。

	P0b 起「未勾选」= exposure hidden（仍注册，幻觉调用走权限 ASK，fail-safe），
	不再是不注册 —— 判定本身不变，语义由 manager 落 exposure。
	"""
	enabled = getattr(spec, "enabled_tools", None)
	if enabled is None:
		return True
	return raw_name in tuple(enabled)


def make_mcp_tool(
	client: McpStdioClient,
	spec: McpClientSpec,
	raw_schema: Mapping[str, Any],
	tool_name: str,
	*,
	apply_vision: bool = True,
) -> McpTool:
	"""Build one :class:`McpTool` with instance-level flags derived from the spec."""
	raw_tool_name = str(raw_schema.get("name") or "")
	policy = resolve_mcp_policy(spec, raw_tool_name)
	return McpTool(
		client,
		spec,
		server_id=spec.id,
		raw_name=raw_tool_name,
		tool_name=tool_name,
		raw_schema=raw_schema,
		policy=policy,
		read_only=spec_read_only(spec, raw_tool_name, raw_schema=raw_schema),
		concurrency_safe=spec_read_only(spec, raw_tool_name, raw_schema=raw_schema),
		apply_vision=apply_vision,
		output_budget=spec_output_budget(spec, raw_tool_name),
	)


def build_tools(client: McpStdioClient, generation: McpGeneration) -> list[McpTool]:
	"""Build :class:`McpTool` adapters for one generation."""
	spec = client.spec
	out: list[McpTool] = []
	for name, raw_schema in generation.tools.items():
		raw_tool_name = str(raw_schema.get("name") or "")
		if not raw_tool_name:
			continue
		out.append(make_mcp_tool(client, spec, raw_schema, name))
	return out


# --------------------------------------------------------------------------- #
# 运行时：把客户端接到真实 ToolRegistry，支持整代替换。
# --------------------------------------------------------------------------- #

class McpServerRuntime:
	"""Owns one stdio MCP server + its dynamic tools, and keeps a ToolRegistry in sync.

	The runtime never checks permission itself — it registers tools through the
	registry so the registry's 3-way gate (default ``outbound_ask``) is always the
	decision point. On ``tools/list_changed`` it replaces the whole generation and
	rolls back on conflict.
	"""

	def __init__(
		self,
		spec: McpClientSpec,
		*,
		registry: Any = None,
		client: McpStdioClient | None = None,
		transport_factory: Any = None,
		logger: Any = None,
		sleep: Any = time.sleep,
	) -> None:
		self.spec = spec
		self._log = logger or _log
		self.client = (
			client
			if client is not None
			else McpStdioClient(
				spec, transport_factory=transport_factory, logger=self._log, sleep=sleep
			)
		)
		self.registry = registry
		self._tools: dict[str, McpTool] = {}
		self._applied_generation = 0

	@property
	def tools(self) -> dict[str, McpTool]:
		return dict(self._tools)

	def tool_names(self) -> list[str]:
		return sorted(self._tools)

	def start(self, *, fetch: bool = True, force: bool = False) -> bool:
		if not self.client.start(fetch=fetch, force=force):
			return False
		gen = self.client.current_generation()
		if gen.applied:
			self._apply_generation(gen)
			return True
		return False

	def stop(self) -> None:
		self._unregister_all()
		self.client.stop()

	def reload(self, *, fetch: bool = True, force: bool = True) -> bool:
		"""Settings HMR hook: disconnect + reconnect (provided for the config layer)."""
		self.stop()
		return self.start(fetch=fetch, force=True)

	def on_list_changed(self) -> McpGeneration:
		"""Handle an MCP ``tools/list_changed`` notification: wholesale replacement."""
		gen = self.client.reload_tools(fetch=True)
		if gen.applied:
			self._apply_generation(gen)
		return gen

	# -- 代际同步 -----------------------------------------------------

	def _apply_generation(self, gen: McpGeneration) -> None:
		if not gen.applied:
			return
		# 冲突：新名字已被占用（属于其他服务器或陈旧条目）。
		if self.registry is not None:
			for name in gen.tools:
				existing = self.registry.get(name)
				if existing is not None and name not in self._tools:
					self._log.warning(
						"mcp server %s registration conflict on %s; rolling back generation",
						self.spec.id,
						name,
					)
					return
		# 注销陈旧名称（整代替换）。
		for old_name in list(self._tools):
			if old_name not in gen.tools:
				self._unregister(old_name)
		# 注册 / 刷新当前工具。
		built = build_tools(self.client, gen)
		new_map: dict[str, McpTool] = {}
		for tool in built:
			if self.registry is not None:
				self._register(tool)
			new_map[tool.name] = tool
		self._tools = new_map
		self._applied_generation = gen.generation

	# -- registry 辅助方法（只增不改；不动 tool_registry.py） ---------

	def _register(self, tool: McpTool) -> None:
		reg = self.registry
		if reg is None:
			return
		try:
			reg.register(tool)
		except Exception:  # noqa: BLE001
			# 若名字已被占用，注册会覆盖其他服务器的
			# 工具——按冲突处理并丢弃该工具（fail-closed）。
			self._log.warning(
				"mcp server %s could not register %s", self.spec.id, tool.name
			)

	def _unregister(self, name: str) -> None:
		reg = self.registry
		if reg is None:
			return
		try:
			current = reg.get(name)
			if current is not None and current is self._tools.get(name):
				reg._tools.pop(name, None)  # noqa: SLF001 — private dict access, additive
				reg._schemas_cache = None  # noqa: SLF001 — invalidate schema cache
			self._tools.pop(name, None)
		except Exception:  # noqa: BLE001
			self._tools.pop(name, None)

	def _unregister_all(self) -> None:
		for name in list(self._tools):
			self._unregister(name)


def register_mcp_server(
	registry: Any,
	spec: McpClientSpec,
	*,
	transport_factory: Any = None,
	logger: Any = None,
) -> McpServerRuntime | None:
	"""Integration entry point the config layer calls.

	Starts the server and registers its tools into ``registry``. Returns the runtime
	on success; returns None (and logs a skip) if the server failed to start so a bad
	server never crashes extension discovery/startup.
	"""
	runtime = McpServerRuntime(
		spec, registry=registry, transport_factory=transport_factory, logger=logger
	)
	ok = runtime.start()
	if not ok:
		return None
	return runtime
