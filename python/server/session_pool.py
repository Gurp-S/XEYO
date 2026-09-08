from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from engine.budget import max_tool_calling_from_env, max_turns_from_env
from engine.query_engine import QueryEngine, QueryEngineConfig
from model.openai_compat import OpenAICompatClient
from msgtypes.message import Message
from prompt.assembler import PromptAssembler

class CwdConflictError(ValueError):
	"""Session is already pinned to a different workspace root."""

	def __init__(self, session_id: str, pinned: str, requested: str) -> None:
		self.session_id = session_id
		self.pinned = pinned
		self.requested = requested
		super().__init__(
			f"session {session_id} is pinned to {pinned}, not {requested}"
		)


# 若 stream 的 finally 未执行（断连等边界情况），在此时间后回收。
# 活 turn 由 TurnRunner 逐帧心跳（touch_busy）续租；chat 提交入口另以
# TurnRunner.is_running 判活兜底，因此租约丢失不会导致叠跑，可取较短窗。
# 须 ≥ 权限面板 TTL（180s）——等待审批期间无事件帧，靠 stale 窗覆盖。
_DEFAULT_BUSY_STALE_SEC = 300.0
# 常驻 engine 数上限：超限按 LRU 逐出最久未用的空闲会话（历史转 stash，可从磁盘恢复）。
_DEFAULT_MAX_ENGINES = 64


def _busy_stale_sec() -> float:
	raw = os.environ.get("XEYO_BUSY_STALE_SEC", "").strip()
	if not raw:
		return _DEFAULT_BUSY_STALE_SEC
	try:
		return max(30.0, float(raw))
	except ValueError:
		return _DEFAULT_BUSY_STALE_SEC


def _max_engines() -> int:
	raw = os.environ.get("XEYO_MAX_SESSION_ENGINES", "").strip()
	if not raw:
		return _DEFAULT_MAX_ENGINES
	try:
		return max(8, int(raw))
	except ValueError:
		return _DEFAULT_MAX_ENGINES


def _load_disk_messages(session_id: str) -> list[Message]:
	from session.hydrate import load_session_messages

	return load_session_messages(session_id)


@dataclass(frozen=True)
class ModelConfig:
	provider: str
	api_key: str
	base_url: str
	model: str
	thinking: str = "disabled"
	reasoning_effort: str = ""
	#: L1.2：单次 submit 的 USD 上限；None 表示不限额（可读 XEYO_MAX_BUDGET_USD）。
	max_budget_usd: float | None = None
	#: 供应商模型元数据给出的上下文上限；未知时保持 None。
	context_limit: int | None = None
	#: 最大输出 tokens（可选）；None = 不限制，不发送该字段。
	max_tokens: int | None = None


@dataclass(frozen=True)
class _BusyLease:
	lease_id: int
	started_at: float


class SessionPool:
	def __init__(
		self,
		cwd: str,
		*,
		busy_stale_sec: float | None = None,
		max_engines: int | None = None,
	) -> None:
		self._ui_cwd = (cwd or "").strip()
		self._lock = threading.Lock()
		self._engines: dict[str, tuple[ModelConfig, QueryEngine]] = {}
		self._session_cwd: dict[str, str] = {}
		# T31 workspace SSOT：workspace id → 服务端权威路径映射（客户端只发 id）。
		self._workspace_ids: dict[str, str] = {}
		# T10：会话创建时 pin 的权限 preset；后续请求不得改写（切换只影响新会话）。
		self._profiles: dict[str, str] = {}
		self._write_stores: dict[str, Any] = {}
		self._history_stash: dict[str, list[Message]] = {}
		self._busy: dict[str, _BusyLease] = {}
		# engine 尚未创建时收到 interrupt（busy 窗口）— #4。
		self._pending_interrupt: set[str] = set()
		# 回溯提交时恰逢 busy（提交与新 turn 并发的窗口）：置位延迟重同步，
		# 由 try_begin 在下一 turn 开始前消费，绝不截断进行中的回合。
		self._pending_resync: set[str] = set()
		self._lease_seq = 0
		self._busy_stale_sec = (
			busy_stale_sec if busy_stale_sec is not None else _busy_stale_sec()
		)
		self._max_engines = (
			max_engines if max_engines is not None else _max_engines()
		)
		# LRU 时钟：每次使用刷新，逐出时挑最久未用的空闲会话。
		self._last_use: dict[str, float] = {}
		# 多 Agent：per-session 调度器（延迟创建）；侧链 GC 复用。
		self._schedulers: dict[str, Any] = {}
		self._todo_stores: dict[str, Any] = {}
		self._batch_aborts: dict[str, Any] = {}

	@property
	def cwd(self) -> str:
		return self._ui_cwd

	def session_cwd(self, session_id: str) -> str | None:
		with self._lock:
			return self._session_cwd.get(session_id)

	def _register_workspace_id(self, physical: str) -> None:
		"""T31：把规范化路径登记为其 workspace id → 路径映射（服务端权威）。"""
		from memory.memdir import workspace_id

		try:
			wsid = workspace_id(physical)
			if wsid:
				self._workspace_ids[wsid] = physical
		except Exception:
			pass

	def resolve_workspace(self, value: str | None) -> str:
		"""T31 workspace SSOT：把客户端发的 workspace id（或路径）解析成真实路径。

		服务端是权威源：
		- 空 → 回落服务端默认工作区（``_ui_cwd``）。
		- 命中已登记的 workspace id → 返回其权威路径（客户端不可覆写）。
		- 否则按路径（向后兼容）解析。
		"""
		raw = (value or "").strip()
		if not raw:
			return self._ui_cwd or ""
		with self._lock:
			if raw in self._workspace_ids:
				return self._workspace_ids[raw]
		from session.workspace_path import resolve_physical_cwd

		physical = resolve_physical_cwd(raw)
		with self._lock:
			self._register_workspace_id(physical)
		return physical

	def set_cwd(self, path: str) -> str:
		"""切换资源管理器 / UI 工作区。不驱逐已钉死 cwd 的 session engine。"""
		from session.workspace_path import is_python_package_root, resolve_physical_cwd

		physical = resolve_physical_cwd(path)
		if is_python_package_root(physical):
			raise ValueError("python package root cannot be a workspace")
		with self._lock:
			self._ui_cwd = physical
			self._register_workspace_id(physical)
		return physical

	def _evict_locked(self) -> None:
		"""调用方必须已持有 _lock。引擎超限时按 LRU 逐出空闲会话。

		被逐出的会话历史转存 stash（磁盘 transcript 兜底），下次访问照常恢复。
		busy 会话绝不逐出；stash 同步限幅（FIFO，重新入队即刷新）。
		"""
		if len(self._engines) <= self._max_engines:
			return
		candidates = sorted(
			self._engines.keys(), key=lambda s: self._last_use.get(s, 0.0)
		)
		for sid in candidates:
			if len(self._engines) <= self._max_engines:
				break
			if sid in self._busy:
				continue
			item = self._engines.pop(sid)
			self._last_use.pop(sid, None)
			# 旧 registry 的 Scheduler 引用会阻止 engine GC，且钉死旧
			# ReadFileState；下次 scheduler_for 会按新 engine 重建/对齐。
			self._schedulers.pop(sid, None)
			try:
				msgs = item[1].mutable_messages
			except Exception:  # noqa: BLE001
				msgs = []
			if msgs:
				self._history_stash[sid] = msgs
			self._pending_interrupt.discard(sid)
			try:
				item[1].interrupt()
			except Exception:  # noqa: BLE001
				logging.getLogger(__name__).debug(
					"engine interrupt on evict failed", exc_info=True
				)
		while len(self._history_stash) > self._max_engines * 2:
			self._history_stash.pop(next(iter(self._history_stash)))

	def get_or_create(
		self,
		session_id: str,
		cfg: ModelConfig,
		*,
		initial_messages: list[Message] | None = None,
		cwd: str | None = None,
		permission_preset: str | None = None,
	) -> QueryEngine:
		"""返回该 session 的 engine。

		- 相同 ModelConfig → 复用 engine；仅当为空时从客户端 hydrate（#2）。
		- 配置变更 → 重建但保留 mutable_messages（#6）。
		- 首次创建钉死 cwd；之后请求不同仓则 CwdConflictError。
		- T10：首次创建同时钉死权限 preset（readonly/workspace-write/full）；
		  后续请求传入不同 preset 不溯及既有会话。
		"""
		from permissions.presets import normalize_preset
		from session.workspace_path import resolve_physical_cwd

		requested = (cwd or "").strip()
		physical: str | None = None
		if requested:
			physical = resolve_physical_cwd(requested)

		with self._lock:
			pinned = self._session_cwd.get(session_id)
			if pinned and physical and os.path.realpath(pinned) != os.path.realpath(
				physical
			):
				raise CwdConflictError(session_id, pinned, physical)
			if pinned:
				use_cwd = pinned
			elif physical:
				use_cwd = physical
				self._session_cwd[session_id] = physical
				self._register_workspace_id(physical)
			elif self._ui_cwd:
				use_cwd = self._ui_cwd
				self._session_cwd[session_id] = self._ui_cwd
				self._register_workspace_id(self._ui_cwd)
			else:
				raise ValueError("workspace cwd is required")
			# 跨会话共享记忆：把会话 → 工作区归属落盘（幂等），
			# 供 memory.search.search_session_notes 跨重启圈定同工作区对话。
			try:
				from session.ws_index import record_session_workspace

				record_session_workspace(session_id, use_cwd)
			except Exception:  # noqa: BLE001 — 索引失败绝不挡会话创建
				logging.getLogger(__name__).debug(
					"workspace index record failed", exc_info=True
				)

			existing = self._engines.get(session_id)
			if existing is not None and existing[0] == cfg:
				engine = existing[1]
				self._last_use[session_id] = time.monotonic()
				if initial_messages:
					engine.hydrate_if_empty(initial_messages)
				return engine

			preserved: list[Message] = []
			if existing is not None:
				# #6：模型/provider/base_url 变更时保留 transcript
				preserved = existing[1].mutable_messages
			if not preserved:
				preserved = list(self._history_stash.pop(session_id, []) or [])
			if not preserved:
				preserved = _load_disk_messages(session_id)
			if not preserved and initial_messages:
				# #2：冷启动且磁盘为空 — 信任客户端先前回合
				preserved = list(initial_messages)

			engine = self._build(
				cfg,
				session_id=session_id,
				initial_messages=preserved or None,
				cwd=use_cwd,
			)
			# T10：preset 首建 pin（first-write-wins）；engine 重建沿用原 pin。
			profile = self._profiles.setdefault(
				session_id, normalize_preset(permission_preset)
			)
			engine.set_permission_profile(profile)
			self._engines[session_id] = (cfg, engine)
			self._last_use[session_id] = time.monotonic()
			self._evict_locked()
			return engine

	def get_if_present(self, session_id: str) -> QueryEngine | None:
		"""若内存中已有 engine 则返回，否则 None（不创建、不 hydrate）。"""
		with self._lock:
			item = self._engines.get(session_id)
			if item is None:
				return None
			self._last_use[session_id] = time.monotonic()
			return item[1]

	def resync_after_rewind(self, session_id: str) -> bool:
		"""回溯提交后把内存态对齐到重写后的磁盘 transcript。

		v2 契约经 ``on_commit=_pool.drop`` 整引擎丢弃实现；v3 热路径此前漏接，
		常驻 engine 的 ``mutable_messages`` 仍含被回溯掉的回合——下一轮 LLM
		会收到 GUI 已不可见的消息。这里做精细对齐（不动工具运行时）：

		- 清 ``_history_stash``（engine 重建时 stash 优先于磁盘，回溯后必脏）；
		- engine 在内存：``QueryEngine.replace_history`` 用磁盘权威消息整表
		  替换，并复位压缩/投影态（compact 游标 / C2 摘要 / 锚点）；
		- engine 不在：仅复位 ``.working.json`` / ``session.md`` sidecar，
		  下次 hydrate 自然从截断后的磁盘装载；
		- 清非活跃 turn snapshot（防「继续」resume cue 富化出被回溯轮的
		  goal 文本）；
		- busy 时（提交与新 turn 并发的窗口）：置 pending 位，由 ``try_begin``
		  在下一 turn 开始前消费，绝不截断进行中的回合。
		"""
		sid = (session_id or "").strip()
		if not sid:
			return False
		with self._lock:
			self._history_stash.pop(sid, None)
			item = self._engines.get(sid)
			if sid in self._busy:
				self._pending_resync.add(sid)
				return False
		return self._resync_now(sid)

	def _resync_now(self, session_id: str) -> bool:
		"""执行内存/sidecar 对齐。调用方必须保证会话空闲（不持 _lock）。"""
		sid = (session_id or "").strip()
		if not sid:
			return False
		# LRU 逐出可能发生在置位与消费之间：stash 再清一次（幂等）。
		with self._lock:
			self._history_stash.pop(sid, None)
		working_reset = False
		try:
			from memory.working import reset_after_rollback

			reset_after_rollback(sid)
			working_reset = True
		except Exception:
			logging.getLogger(__name__).debug(
				"rewind working reset failed", exc_info=True
			)
		try:
			from memory.session_md import (
				clear_after_rollback,
				count_tool_results_rows,
			)
			from session.persistence import transcript_path
			from session.record_transcript import load_transcript, transcript_read_paths

			rows: list[dict[str, Any]] = []
			for p in transcript_read_paths(transcript_path(sid)):
				rows.extend(load_transcript(p))
			clear_after_rollback(sid, keep_tool_calls=count_tool_results_rows(rows))
		except Exception:
			logging.getLogger(__name__).debug(
				"rewind session.md reset failed", exc_info=True
			)
		try:
			from engine import turn_snapshot

			ts = turn_snapshot.hydrate(sid)
			# 回溯后被回溯轮的 goal/stop_reason 不得再经「继续」富化进提示
			# （recovery_required 也一并清：回溯已取代该轮的恢复语义）。
			if ts is None or not ts.is_active():
				turn_snapshot.clear(sid)
		except Exception:
			logging.getLogger(__name__).debug(
				"rewind turn snapshot clear failed", exc_info=True
			)
		with self._lock:
			item = self._engines.get(sid)
		if item is None:
			# 无常驻引擎：sidecar 已复位，下次 hydrate 即从截断后的磁盘装载。
			# LRU 逐出可能发生在置位与消费之间（旧全量历史已被回填进 stash），
			# 尾部再清一次才能保证下次 get_or_create 不复活被回溯消息。
			with self._lock:
				self._history_stash.pop(sid, None)
			return working_reset
		try:
			from session.persistence import is_session_persistence_disabled

			if is_session_persistence_disabled():
				# 持久化关闭时磁盘 transcript 不是权威（_load_disk_messages 恒空），
				# 严禁用它整表替换引擎历史（会把引擎记忆清空）。
				return False
			messages = _load_disk_messages(sid)
			item[1].replace_history(messages)
			return True
		except Exception:
			logging.getLogger(__name__).warning(
				"rewind engine history resync failed session=%s", sid, exc_info=True
			)
			return False

	def transcript_known_ids(self, session_id: str) -> set[str] | None:
		"""若内存中有该 session 的 engine，返回其 transcript 去重集合（供 ui_thought 同步复用）。"""
		with self._lock:
			item = self._engines.get(session_id)
			if item is None:
				return None
			return item[1]._session.transcript_known_ids

	def _build(
		self,
		cfg: ModelConfig,
		*,
		session_id: str,
		initial_messages: list[Message] | None = None,
		cwd: str,
	) -> QueryEngine:
		from tools.catalog import build_default_registry  # 惰性:会话创建时才建工具面

		reg = build_default_registry(cwd=cwd)
		# HTTP 全栈测试的确定性假模型：直接复用 FakeModelClient + 注入 EchoTool
		# （与 query_engine 的 fake 分支同款）；不走 OpenAI 兼容客户端。
		if cfg.provider == "fake":
			from model.fake import FakeModelClient
			from tools.echo import EchoTool

			model: Any = FakeModelClient()
			reg.register(EchoTool())
		else:
			model = OpenAICompatClient(
				api_key=cfg.api_key,
				base_url=cfg.base_url,
				model=cfg.model,
				provider=cfg.provider,
				thinking=cfg.thinking,
				reasoning_effort=cfg.reasoning_effort,
				max_tokens=cfg.max_tokens,
				session_id=session_id or "",
			)
			if cfg.context_limit is not None and cfg.context_limit > 0:
				model.context_limit = cfg.context_limit
			# Read vision：按模型能力在建表时开关（同会话 schema 稳定，不中途改 tools）
			from model.vision_capability import supports_vision_input
			from tools.catalog import apply_read_vision

			modes = getattr(cfg, "modes", None)
			apply_read_vision(
				reg,
				enabled=supports_vision_input(
					provider=cfg.provider,
					model=cfg.model,
					modes=modes if isinstance(modes, dict) else None,
				),
			)
		# F1：MCP 运行时接线（扩展层关 = 一次读盘 no-op；21 内置工具零变化）。
		try:
			from extension.mcp_manager import attach_mcp_tools

			attach_mcp_tools(reg, cwd)
		except Exception:  # noqa: BLE001 — 单点接线失败不挡会话创建
			import logging

			logging.getLogger(__name__).warning("mcp attach failed", exc_info=True)
		# 身份与安全围栏已在 PromptAssembler 左段；勿再 append 第二段 You-are。
		# 子 agent 不再附加任何文本附录（理念裁决 A2：约束由执行层强制）。
		assembler = PromptAssembler()
		config: QueryEngineConfig = {
			"cwd": cwd,
			"tools": reg,
			"model_client": model,
			"prompt_assembler": assembler,
			"append_system_prompt": "",
			"user_specified_model": cfg.model,
			# L1.2：用户选择的连接/模型，实时价按它算。
			"provider": cfg.provider,
			"model": cfg.model,
			# 每次用户 submit 的模型轮次（一次响应中多工具 = 1 轮）。
				"max_turns": max_turns_from_env(),
				"max_tool_calling": max_tool_calling_from_env(),
				"session_id": session_id,

		}
		if cfg.max_budget_usd is not None:
			config["max_budget_usd"] = cfg.max_budget_usd
		if initial_messages:
			config["initial_messages"] = list(initial_messages)

		# 多 Agent：给 AgentTool 注入 sub-agent 运行时（model/prompt/cwd/system/date）+ write_store。
		# 仅注入 AgentTool（其子 agent 写文件走单写者 store）；主 agent 的 Write/Edit 保持旁路（零回归）。
		# 侧链写入由 run_subagent 内完成；此处保证 HTTP 服务层的 AgentTool 能真正 spawn 子 agent。
		self._inject_subagent_runtime(reg, model, assembler, cwd)
		self._inject_subagent_write_store(reg, session_id, cwd)
		self._inject_todo_store(reg, session_id)
		self._inject_session_ids(reg, session_id)
		try:
			# 注册表背后的共享 ReadFileState 标记所属会话树根，供跨会话外部归因。
			from tools.catalog import shared_read_state

			shared_read_state(reg).set_conversation_id(session_id)
		except Exception:
			pass

		return QueryEngine(config)

	def _inject_subagent_runtime(
		self, reg: Any, model: Any, assembler: Any, cwd: str
	) -> None:
		from datetime import date

		from engine.subagent_runner import SubagentRuntime
		from tools.catalog import inject_subagent_runtime, shared_read_state

		inject_subagent_runtime(
			reg,
			lambda: SubagentRuntime(
				model_client=model,
				prompt_assembler=assembler,
				workspace_root=cwd,
				date_iso=date.today().isoformat(),
				read_state=shared_read_state(reg),
			),
		)

	def _inject_subagent_write_store(self, reg: Any, session_id: str, cwd: str) -> None:
		from tools.agent_tool import AgentTool

		store = self._write_store_locked(cwd)
		# 主 Agent Write/Edit/NotebookEdit 也走同一 WriteStore，避免与多 Agent / 跨会话静默互盖。
		for name in ("Write", "Edit", "NotebookEdit"):
			tool = reg.get(name)
			setter = getattr(tool, "set_write_store", None) if tool is not None else None
			if callable(setter):
				setter(store)
			id_setter = getattr(tool, "set_agent_id", None) if tool is not None else None
			if callable(id_setter):
				id_setter("main")
		at = reg.get("Agent")
		if isinstance(at, AgentTool):
			at.set_write_store(store)
			at.set_session_id(session_id)

	def _inject_todo_store(self, reg: Any, session_id: str) -> None:
		"""主会话 TodoWrite 共用 per-session TodoStore，并写入 session_id。

		调用方必须已持有 ``_lock``（仅由 ``_build`` / ``get_or_create`` 调用）。
		不可在此再 ``with self._lock``：``threading.Lock`` 不可重入，嵌套会死锁，
		整进程事件循环卡住（多 Agent 冷启动 / 重建 engine 时必现）。
		"""
		from tools.todo_write_tool.store import TodoStore

		store = self._todo_stores.get(session_id)
		if store is None:
			store = TodoStore()
			self._todo_stores[session_id] = store
		tool = reg.get("TodoWrite")
		if tool is None:
			return
		setter = getattr(tool, "set_todo_store", None)
		if callable(setter):
			setter(store)
		sid_setter = getattr(tool, "set_session_id", None)
		if callable(sid_setter):
			sid_setter(session_id)
		id_setter = getattr(tool, "set_agent_id", None)
		if callable(id_setter):
			id_setter("main")

	def _inject_session_ids(self, reg: Any, session_id: str) -> None:
		"""给所有实现 set_session_id 的工具注入当前会话 id（幂等）。"""
		tools = getattr(reg, "_tools", None)
		if not isinstance(tools, dict):
			return
		for tool in tools.values():
			sid_setter = getattr(tool, "set_session_id", None)
			if callable(sid_setter):
				sid_setter(session_id)

	def _reclaim_stale(self, now: float) -> None:
		"""调用方必须已持有 _lock。有活跃 multi-agent batch 的 session 绝不回收。"""
		stale = [
			sid
			for sid, lease in self._busy.items()
			if now - lease.started_at >= self._busy_stale_sec
			and sid not in self._batch_aborts
		]
		for sid in stale:
			del self._busy[sid]

	def try_begin(self, session_id: str) -> int | None:
		"""标记 session 为 busy。返回 lease id，若仍 busy 则返回 None。

		若 stream 的 finally 从未执行，过期的 lease 会自动回收。
		活跃 batch abort 期间禁止叠跑（即使 busy 被误清）。
		"""
		now = time.monotonic()
		cwd_for_presence: str | None = None
		with self._lock:
			self._reclaim_stale(now)
			if session_id in self._busy:
				return None
			if session_id in self._batch_aborts:
				return None
			self._lease_seq += 1
			lease_id = self._lease_seq
			self._busy[session_id] = _BusyLease(lease_id, now)
			cwd_for_presence = self._session_cwd.get(session_id) or self._ui_cwd
			resync_due = session_id in self._pending_resync
			if resync_due:
				self._pending_resync.discard(session_id)
		self._presence_busy(session_id, cwd_for_presence, busy=True)
		if resync_due:
			# 回溯提交曾撞上 busy：在新 turn 开始前把内存历史对齐磁盘。
			self._resync_now(session_id)
		return lease_id

	def touch_busy(self, session_id: str) -> None:
		"""长跑心跳：刷新 busy 租约起始时间，避免误回收。"""
		now = time.monotonic()
		with self._lock:
			cur = self._busy.get(session_id)
			if cur is not None:
				self._busy[session_id] = _BusyLease(cur.lease_id, now)

	def end(self, session_id: str, lease_id: int | None = None) -> None:
		"""释放 busy。若指定 lease_id，则忽略不匹配的（较新）持有者。"""
		cwd_for_presence: str | None = None
		ended = False
		with self._lock:
			cur = self._busy.get(session_id)
			if cur is None:
				return
			if lease_id is not None and cur.lease_id != lease_id:
				return
			del self._busy[session_id]
			self._pending_interrupt.discard(session_id)
			ended = True
			cwd_for_presence = self._session_cwd.get(session_id) or self._ui_cwd
		if ended:
			self._presence_busy(session_id, cwd_for_presence, busy=False)

	@staticmethod
	def _presence_busy(session_id: str, cwd: str | None, *, busy: bool) -> None:
		if not cwd or not (session_id or "").strip():
			return
		try:
			from engine.session_presence import default_session_presence

			default_session_presence().touch_busy(cwd, session_id, busy=busy)
		except Exception:
			logging.getLogger(__name__).debug(
				"session presence touch_busy failed", exc_info=True
			)

	def is_busy(self, session_id: str) -> bool:
		now = time.monotonic()
		with self._lock:
			self._reclaim_stale(now)
			return session_id in self._busy

	def force_idle(self, session_id: str) -> None:
		"""Interrupt engine and release a stale busy lease (rewind / stop recovery)."""
		with self._lock:
			self._reclaim_stale(time.monotonic())
			item = self._engines.get(session_id)
			if item is not None:
				try:
					item[1].interrupt()
				except Exception:
					logging.getLogger(__name__).debug(
						"force_idle interrupt failed", exc_info=True
					)
			self._busy.pop(session_id, None)
			self._pending_interrupt.discard(session_id)
			self._abort_batch_locked(session_id)

	def interrupt(self, session_id: str) -> bool:
		"""请求取消。

		- Busy（engine 可能尚未存在）：排队 pending + 若 engine 存在则 interrupt。
		- Idle（非 busy）：幂等 no-op — 不排队（避免污染下一轮）。
		请求被接受时始终返回 True（含 idle noop）。
		"""
		with self._lock:
			item = self._engines.get(session_id)
			busy = session_id in self._busy
			self._abort_batch_locked(session_id)
			if item is not None:
				item[1].interrupt()
				self._last_use[session_id] = time.monotonic()
				if busy:
					self._pending_interrupt.add(session_id)
				return True
			if busy:
				self._pending_interrupt.add(session_id)
				return True
			# Idle：清除过期的 pending 位；不入队。
			self._pending_interrupt.discard(session_id)
			return True

	def take_pending_interrupt(self, session_id: str) -> bool:
		"""消费排队的 interrupt（在 get_or_create 之后立即调用）。"""
		with self._lock:
			if session_id not in self._pending_interrupt:
				return False
			self._pending_interrupt.discard(session_id)
			return True

	def usage_snapshot(self) -> dict[str, Any]:
		"""L1.2：跨 engine 聚合的预算观测（供 GET /health）。"""
		last_usd = 0.0
		last_tokens = 0
		session_usd = 0.0
		session_tokens = 0
		last_hit = 0
		last_miss = 0
		with self._lock:
			for _cfg, eng in self._engines.values():
				snap = eng.budget_snapshot()
				session_usd += float(snap["used_usd"] or 0)
				session_tokens += int(snap["used_tokens"] or 0)
				if float(snap["last_usage_usd"] or 0) > last_usd:
					last_usd = float(snap["last_usage_usd"] or 0)
				if int(snap["last_usage_tokens"] or 0) > last_tokens:
					last_tokens = int(snap["last_usage_tokens"] or 0)
					last_hit = int(snap.get("last_cache_hit_tokens") or 0)
					last_miss = int(snap.get("last_cache_miss_tokens") or 0)
		cache_total = last_hit + last_miss
		# P3：前缀缓存命中率（最近一轮输入缓存命中占比；无数据 = None）。
		prefix_cache_hit_ratio = (
			round(last_hit / cache_total, 4) if cache_total > 0 else None
		)
		return {
			"last_turn_usd": round(last_usd, 8),
			"last_turn_tokens": last_tokens,
			"session_used_usd": round(session_usd, 8),
			"session_used_tokens": session_tokens,
			"last_cache_hit_tokens": last_hit,
			"last_cache_miss_tokens": last_miss,
			"prefix_cache_hit_ratio": prefix_cache_hit_ratio,
		}

	def busy_sessions(self) -> list[str]:
		"""T30 /health：当前持有 busy 租约的会话（真实引擎状态）。"""
		with self._lock:
			return sorted(self._busy)

	def loaded_sessions(self) -> int:
		"""T30 /health：已创建 engine 的会话数。"""
		with self._lock:
			return len(self._engines)

	def drop(self, session_id: str) -> bool:
		"""移除 FE 已删除 session 的 engine + busy + stash（#7）。"""
		with self._lock:
			item = self._engines.pop(session_id, None)
			self._busy.pop(session_id, None)
			self._history_stash.pop(session_id, None)
			self._pending_interrupt.discard(session_id)
			self._pending_resync.discard(session_id)
			self._last_use.pop(session_id, None)
			self._schedulers.pop(session_id, None)
			self._todo_stores.pop(session_id, None)
			self._session_cwd.pop(session_id, None)
			self._abort_batch_locked(session_id)
			had = item is not None
			if item is not None:
				try:
					item[1].interrupt()
				except Exception:
					pass
		try:
			from engine.session_presence import default_session_presence

			default_session_presence().drop(session_id)
		except Exception:
			logging.getLogger(__name__).debug(
				"session presence drop failed", exc_info=True
			)
		return had

	def drop_engine(self, session_id: str) -> bool:
		"""回滚/回溯提交后丢弃常驻引擎（下次 get_or_create 从磁盘重建）。

		与 :meth:`drop` 的差异：会话本身仍然存在——保留 cwd pin、权限 preset、
		TodoStore 与 workspace id 映射，避免 v2 ``on_commit=_pool.drop`` 曾有的
		「下一请求不带 workspace 时静默重钉到 _ui_cwd」换仓问题。
		"""
		with self._lock:
			item = self._engines.pop(session_id, None)
			self._busy.pop(session_id, None)
			self._history_stash.pop(session_id, None)
			self._pending_interrupt.discard(session_id)
			self._pending_resync.discard(session_id)
			self._last_use.pop(session_id, None)
			self._schedulers.pop(session_id, None)
			self._abort_batch_locked(session_id)
			had = item is not None
			if item is not None:
				try:
					item[1].interrupt()
				except Exception:
					pass
		return had

	def write_store(self, cwd: str | None = None) -> Any:
		"""同一工作区根共用一个 WriteStore（调度器与 AgentTool 同实例）。"""
		with self._lock:
			root = (cwd or self._ui_cwd or "").strip()
			if not root:
				raise ValueError("workspace cwd is required")
			return self._write_store_locked(root)

	def _write_store_locked(self, cwd: str) -> Any:
		from engine.write_store import WriteStore

		key = os.path.realpath(cwd)
		store = self._write_stores.get(key)
		if store is None:
			store = WriteStore(key)
			self._write_stores[key] = store
		return store

	def attach_batch_abort(self, session_id: str) -> Any:
		"""为本轮多 Agent 批创建 AbortController；若已有 pending interrupt 则立刻 abort。

		若该 session 已有未中止的 batch abort，复用它（禁止叠跑覆盖）。
		"""
		from engine.abort import AbortController

		with self._lock:
			existing = self._batch_aborts.get(session_id)
			if existing is not None and not getattr(existing, "aborted", False):
				return existing
			abort = AbortController()
			self._batch_aborts[session_id] = abort
			if session_id in self._pending_interrupt:
				abort.abort()
			return abort

	def detach_batch_abort(self, session_id: str, abort: Any | None = None) -> None:
		"""摘掉 batch abort。传入 abort 时仅当仍是同一实例才 pop（防旧流误摘新批）。"""
		with self._lock:
			cur = self._batch_aborts.get(session_id)
			if cur is None:
				return
			if abort is not None and cur is not abort:
				return
			self._batch_aborts.pop(session_id, None)

	def batch_is_active(self, session_id: str) -> bool:
		with self._lock:
			abort = self._batch_aborts.get(session_id)
			return abort is not None and not getattr(abort, "aborted", False)

	def _abort_batch_locked(self, session_id: str) -> None:
		abort = self._batch_aborts.get(session_id)
		if abort is not None:
			try:
				abort.abort()
			except Exception:  # noqa: BLE001
				pass

	def scheduler_for(self, session_id: str, *, write_store: Any | None = None) -> Any:
		"""按 session 延迟创建确定性调度器（HTTP 层做多任务分发的入口）。"""
		from engine.scheduler import Scheduler
		from tools.catalog import shared_read_state

		with self._lock:
			root = self._session_cwd.get(session_id) or self._ui_cwd
			if not root:
				raise ValueError("workspace cwd is required")
			store = write_store if write_store is not None else self._write_store_locked(root)
			sched = self._schedulers.get(session_id)
			if sched is None:
				sched = Scheduler(
					root,
					write_store=store,
					main_session_id=session_id,
					read_state=None,
				)
				self._schedulers[session_id] = sched
			# 每次调用都把 read_state 对齐到当前 engine：engine 因换配置 /
			# LRU 逐出重建后 registry 携带新 ReadFileState，钉住旧实例会让
			# 子 agent 写文件的时间戳进旧册，主会话 Edit 再次误报
			# modified-since-read（并阻止旧 engine 被 GC）。
			item = self._engines.get(session_id)
			if item is not None:
				try:
					sched._read_state = shared_read_state(item[1].config["tools"])
				except Exception:
					pass
			return sched

	def gc_sidechains(self, session_id: str, *, ttl_seconds: float = 7 * 24 * 3600) -> int:
		"""HTTP 层侧链垃圾回收：清理超 TTL 的子 agent 侧链（B6/C9）。"""
		from engine.subagent_runner import gc_sidechains

		return gc_sidechains(session_id, ttl_seconds=ttl_seconds)
