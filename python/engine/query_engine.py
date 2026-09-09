"""
查询引擎模块

提供单会话的 Agentic 查询引擎（QueryEngine），负责：
- 管理对话历史与 Session 状态
- 与模型客户端、工具注册表、Prompt 组装器协作
- 通过 submit_message 驱动模型 ↔ 工具的闭环交互
- 支持中断、预算控制、持久化转录等能力
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date
from typing import (
    Any,
    AsyncIterator,
    Callable,
    NotRequired,
    Optional,
    TypedDict,
    Union,
)

# 内部依赖
from engine.abort import AbortController          # 中止控制器
from engine.budget import (
    DEFAULT_MAX_TOOL_CALLING,
    DEFAULT_MAX_TURNS,
    BudgetTracker,
)  # 预算追踪（轮次 / 工具调用 / 费用）

from engine.query_loop import query_loop           # 核心对话循环
from engine.permission_coordinator import PermissionCoordinator
from engine.task_state import SessionTaskState     # 会话级任务状态机
from engine.workspace_context import (
    WorkspaceContext,
    set_workspace_context,
)
from memory.working import apply_to_tools, collect_from_tools, flush, hydrate
from model.client import ModelClient              # 模型客户端抽象
from msgtypes.events import (
    AssistantDelta,
    ReasoningDelta,
    ToolProgressEvent,
    EngineEvent,
    ResultEvent,
    StoppedEvent,
    TaskStateEvent,
)  # 事件类型

from msgtypes.message import Message, user_message # 消息结构
from prompt.assembler import PromptAssembler      # System Prompt 组装器
from permissions.store import default_permission_store
from permissions.policy import (
	normalize_agent_mode,
	set_agent_mode,
)
from rewind import is_rewind_enabled
from rewind.context import RewindExecutionContext, bind_context
from rewind.journal import OperationJournal
from rewind.revision import RevisionStore
from rewind.snapshot import SnapshotStore
from session import flush_transcript, record_transcript  # 会话持久化
from session.workspace_path import resolve_physical_cwd
from session.persistence import is_session_persistence_disabled  # 持久化开关
from session.state import SessionState             # 会话状态
from tools.tool_registry import ToolRegistry      # 工具注册表


def _rewind_take_snapshot(cwd: str, session_id: str, phase: str) -> str | None:
    """在跨进程工作区锁内拍 shadow-git 快照（阻塞操作，供 to_thread 调用）。"""
    from engine.workspace_lock import WorkspaceLock
    from engine.shadow_git import ShadowGit

    shadow = ShadowGit(cwd)
    lock = WorkspaceLock(cwd, owner=session_id)
    with lock.hold(blocking=True, timeout=10.0):
        return shadow.snapshot(message=f"{phase} turn {session_id}")


class QueryEngineConfig(TypedDict):
    """QueryEngine 构造配置（每个会话一个实例）。

    调用方通过 ``async for ev in engine.submit_message(prompt): ...`` 驱动查询，
    通过 ``engine.interrupt()`` 取消当前进行中的查询。
    """

    #: 工作目录；submit_message 开始时会调用 set_cwd(cwd)，所有相对路径以此为准。
    cwd: str
    #: 本会话可用的工具注册表，包含所有已注册的工具实例。
    tools: ToolRegistry
    #: 恢复会话时注入的历史消息（通常来自持久化存储）。
    initial_messages: NotRequired[Optional[list[Message]]]
    #: 追加到默认 system（含 XEYO.md）之后；不得用来整段替换 default+instructions。
    custom_system_prompt: NotRequired[Optional[str]]
    #: 再追加到 system prompt 末尾的说明，可与 custom_system_prompt 同时使用。
    append_system_prompt: NotRequired[Optional[str]]
    #: 用户指定的模型名称（如 "deepseek"），会覆盖默认模型选择。
    user_specified_model: NotRequired[Optional[str]]
    #: 用户选择的连接（厂商），用于实时价（L1.2 预算）。
    provider: NotRequired[Optional[str]]
    #: 用户选择的模型（来自厂商 /v1/models），用于实时价（L1.2 预算）。
    model: NotRequired[Optional[str]]
    #: agentic 循环最大回合数（模型→工具→模型轮次），默认 256。
    max_turns: NotRequired[Optional[int]]
    #: 每个模型 Turn 中实际进入 Agent tool interface 的最大执行次数，默认 64（并发上限另由编排层信号量决定）。
    max_tool_calling: NotRequired[Optional[int]]

    #: 美元费用上限（L1.2），超限即 StoppedEvent(reason="budget_usd")。
    max_budget_usd: NotRequired[Optional[float]]
    #: 兼容旧名：max_budget_usd 的别名。
    max_budget: NotRequired[Optional[float]]
    #: API 侧 output task_budget，用于限制模型输出 token 等（具体由模型客户端解释）。
    task_budget: NotRequired[Optional[dict[str, int]]]
    #: 结构化输出 JSON Schema，若提供则强制模型输出符合 Schema 的结果。
    json_schema: NotRequired[Optional[dict[str, Any]]]
    #: 是否开启详细日志（调试用）。
    verbose: NotRequired[Optional[bool]]
    #: 是否在事件流中回放用户消息（便于前端展示）。
    replay_user_messages: NotRequired[Optional[bool]]
    #: MCP elicitation 处理回调（用于某些工具需要的用户交互确认）。
    handle_elicitation: NotRequired[Optional[Any]]
    #: 是否产出底层的流式事件（如 token delta）。
    include_partial_messages: NotRequired[Optional[bool]]
    #: 可选外部 AbortController，若传入则引擎使用它而非内部新建。
    abort_controller: NotRequired[Optional[Any]]
    #: snip 边界处理器，用于处理代码片段的特殊格式。
    snip_replay: NotRequired[
        Optional[Callable[[Message, list[Message]], Optional[dict[str, Any]]]]
    ]
    #: HTTP/CLI 桥接：模型客户端实例（必须提供）。
    model_client: NotRequired[ModelClient]
    #: HTTP/CLI 桥接：PromptAssembler 实例（若未提供则新建默认）。
    prompt_assembler: NotRequired[PromptAssembler]
    #: 与 SessionPool / 磁盘 JSONL 共用的会话键；缺省则 SessionState 自生成 uuid。
    session_id: NotRequired[str]
    #: 是否启用企业级 rewind 记录；默认开启，可用 XEYO_REWIND_ENABLED=0 关闭。
    rewind_enabled: NotRequired[Optional[bool]]


class QueryEngine:
    """单会话查询引擎。

    - 持有对话可变状态（历史消息、Abort 控制器、预算等）
    - 每次调用 ``submit_message(prompt)`` 代表一个用户回合，
      内部通过 ``query_loop`` 执行模型↔工具迭代，直到模型结束或达到限制。
    - 可随时调用 ``interrupt()`` 取消当前进行中的查询。
    """

    def __init__(self, config: QueryEngineConfig) -> None:
        """初始化引擎，复制配置并建立初始会话状态。"""
        self._config: QueryEngineConfig = config
        # Date 在会话启动时固化：跨天首请求不改左段字节，保住 KV 前缀
        self._date_iso: str = date.today().isoformat()
        # 可变消息历史，用于内存中的对话记录
        self._mutable_messages: list[Message] = list(
            config.get("initial_messages") or []
        )

        self._has_handled_orphaned_permission: bool = False
        self._discovered_skill_names: set[str] = set()   # 发现的内置技能名称
        self._loaded_nested_memory_paths: set[str] = set()  # 已加载的嵌套记忆路径

        # 检查必需的 model_client
        model = config.get("model_client")
        if model is None:
            raise TypeError(
                "QueryEngine(config) 需要 config['model_client']（ModelClient 实例）"
            )
        self._model: ModelClient = model
        self._tools: ToolRegistry = config["tools"]
        self._prompt: PromptAssembler = (
            config.get("prompt_assembler") or PromptAssembler()
        )

        # 构建 SessionState，包含预算、历史、工作目录等
        max_turns = int(config.get("max_turns") or DEFAULT_MAX_TURNS)
        max_tool_calling = int(
            config.get("max_tool_calling") or DEFAULT_MAX_TOOL_CALLING
        )
        sid = str(config.get("session_id") or "").strip()

        self._provider = str(config.get("provider") or "deepseek")
        self._model_name = str(config.get("model") or "deepseek-v4-flash")
        self._session = SessionState(
            cwd=config["cwd"],
            budget=BudgetTracker(
                max_turns=max_turns,
                max_tool_calling=max_tool_calling,
                provider=self._provider,
                model=self._model_name,
            ),
            session_id=sid,
        )
        self._task_state = SessionTaskState(session_id=self._session.session_id)
        # T10：会话权限 preset（readonly/workspace-write/full），SessionPool 创建时 pin。
        self._permission_profile: str = "workspace-write"

        # 将初始消息填入 session
        for msg in self._mutable_messages:
            self._session.messages.append(msg)
        self._session.transcript_known_ids.update(
            m.id for m in self._mutable_messages if m.id
        )
        self._session.transcript_persist_index = len(self._mutable_messages)

        # 决定使用外部传入的 AbortController 还是内部新建
        abort = config.get("abort_controller")
        self._abort_controller: AbortController = (
            abort if isinstance(abort, AbortController) else self._session.abort
        )
        # 若外部提供了且与 session 内部的不同，则同步替换
        if abort is not None and abort is not self._session.abort:
            self._session.abort = self._abort_controller  # type: ignore[assignment]

        self._session.working = hydrate(self._session.session_id)
        self._session.working.session_id = self._session.session_id
        # sidecar 空时从 transcript 回填最后一次 TodoWrite（冷启动 / 丢 sidecar）。
        if not self._session.working.todos:
            try:
                from tools.todo_write_tool.restore import restore_todos_from_transcript

                restored = restore_todos_from_transcript(self._session.session_id)
                if restored:
                    self._session.working.todos = [t.to_dict() for t in restored]
            except Exception:
                pass
        apply_to_tools(self._session.working, self._tools)

        configured_rewind = config.get("rewind_enabled")
        self._rewind_enabled = (
            is_rewind_enabled()
            if configured_rewind is None
            else bool(configured_rewind)
        )
        # 关闭时这些 store 是惰性的。仍在此构造它们，
        # 以便后续请求能查到稳定的 per-session 归属。
        self._rewind_journal = OperationJournal(
            self._session.session_id,
            enabled=self._rewind_enabled,
        )
        self._revision_store = RevisionStore(
            self._session.session_id,
            enabled=self._rewind_enabled,
        )
        self._snapshot_store = SnapshotStore(
            self._session.session_id,
            enabled=self._rewind_enabled,
        )
        self._active_rewind_context: RewindExecutionContext | None = None
        # T39：引擎内互斥标记。同一事件循环内由 submit_message 入口/finally
        # 维护；engine 并发属于编程错误（外层闸门失效的兜底）。
        self._turn_active: bool = False

    @property
    def config(self) -> QueryEngineConfig:
        """返回只读配置（副本）"""
        return self._config

    @property
    def session_id(self) -> str:
        """与 SessionPool 键、transcript 文件名同一来源。"""
        return self._session.session_id

    @property
    def mutable_messages(self) -> list[Message]:
        """返回当前内存中消息历史的浅拷贝，供外部只读访问。"""
        return self._mutable_messages.copy()

    def is_empty(self) -> bool:
        """检查是否没有任何历史消息（未开始任何回合）。"""
        return len(self._mutable_messages) == 0

    def set_permission_profile(self, profile: str) -> None:
        """T10：设置会话权限 preset（由 SessionPool 在创建时调用一次）。"""
        from permissions.presets import normalize_preset

        self._permission_profile = normalize_preset(profile)

    @property
    def permission_profile(self) -> str:
        """本会话 pin 的权限 preset（readonly/workspace-write/full）。"""
        return self._permission_profile

    def hydrate_if_empty(self, messages: list[Message]) -> bool:
        """仅当本引擎尚无消息时，注入从外部恢复的历史消息。

        用于进程重启后或通过 session_id 恢复上下文。若成功注入则返回 True。
        """
        if self._mutable_messages or not messages:
            return False
        copied = list(messages)
        self._mutable_messages = copied
        for msg in copied:
            self._session.messages.append(msg)
            if msg.id:
                self._session.transcript_known_ids.add(msg.id)
        self._session.transcript_persist_index = len(copied)
        return True

    def replace_history(self, messages: list[Message]) -> None:
        """回溯后整表替换内存历史，对齐重写后的磁盘 transcript 前缀。

        与 ``hydrate_if_empty``（仅空引擎生效）不同：本方法无条件覆盖。
        回溯只重写磁盘 transcript；常驻 engine 的 ``_mutable_messages``
        若不同步截断，下一轮 LLM 仍会看到已被回溯掉的回合（GUI 不可见）。
        同时按 ``memory.working.reset_after_rollback`` 同清单复位压缩/投影
        态，并把复位结果灌回工具侧（TodoStore / ReadFileState）。
        """
        copied = list(messages)
        self._mutable_messages = copied
        self._session.messages.replace(copied)
        self._session.transcript_known_ids = {m.id for m in copied if m.id}
        self._session.transcript_persist_index = len(copied)
        snap = self._session.working
        snap.compact_cursor = 0
        snap.c1_frozen_until = 0
        snap.c2_summary_text = ""
        snap.turns_since_c2 = 0
        snap.last_x_sim = ""
        snap.last_x_sent = ""
        snap.last_action = ""
        snap.speculation = []
        snap.todos = []
        snap.tasks = []
        snap.read_file_state = {}
        snap.session_md_tool_epoch = 0
        snap.proj_cache = None
        snap.compact_checkpoint = None
        snap._pending_c2_summary = None
        snap.last_projection = None
        snap.current_atoms = []
        apply_to_tools(snap, self._tools)
        flush(self._session.session_id, snap)

    @property
    def abort_controller(self) -> AbortController:
        """暴露当前的中止控制器，供外部检查或手动中止。"""
        return self._abort_controller

    def budget_snapshot(self) -> dict[str, Any]:
        """L1.2：本轮预算快照，供 /health 与外部观测。"""
        b = self._session.budget
        # L1.2：最近一轮的 cache 命中/未命中拆分裂（供 /health 透出前缀缓存命中率）。
        _hit = 0
        _miss = 0
        try:
            if isinstance(b.last_usage, dict):
                from model import pricing_mod

                _hit, _miss, _out = pricing_mod.split_usage(b.last_usage)
        except Exception:  # noqa: BLE001
            _hit, _miss = 0, 0
        return {
            "turn_count": b.turn_count,
            "max_turns": b.max_turns,
            "current_turn_tool_calls": b.current_turn_tool_calls,
            "max_tool_calling": b.max_tool_calling,
            "grace_turns_used": b.grace_turns_used,
            "grace_turns_remaining": b.grace_turns_remaining,
            "grace_reason": b.grace_reason,
            "used_tokens": b.used_tokens,

            "used_usd": round(b.used_usd, 8),
            "usd_limit": b.usd_limit,
            "last_usage_tokens": b.last_usage_tokens,
            "last_usage_usd": round(b.last_usage_usd, 8),
            "last_cache_hit_tokens": int(_hit or 0),
            "last_cache_miss_tokens": int(_miss or 0),
        }

    def task_state_snapshot(self) -> dict[str, object]:
        """会话级任务状态快照，供 /health 与外部查询。"""
        return self._task_state.snapshot()

    def _should_persist(self) -> bool:
        """判断当前会话是否应进行持久化（全局未禁用且会话自身未禁用）。"""
        return not is_session_persistence_disabled() and not (
            hasattr(self._session, "is_session_persistence_disabled")
            and self._session.is_session_persistence_disabled()
        )

    async def _persist_transcript_delta(self) -> None:
        """只提交自上次落盘以来新增的消息（避免每事件拷贝全历史）。"""
        items = self._session.messages.items
        idx = self._session.transcript_persist_index
        if idx >= len(items):
            return
        await record_transcript(
            items[idx:],
            session_id=self._session.session_id,
            session_persistence_disabled=self._session.is_session_persistence_disabled(),
            known_ids=self._session.transcript_known_ids,
        )
        self._session.transcript_persist_index = len(items)

    def interrupt(self) -> None:
        """中止当前正在执行的查询（若存在）。"""
        self._abort_controller.abort()
        # 若 session 内部控制器与外部不一致，也一并中止
        if self._session.abort is not self._abort_controller:
            self._session.abort.abort()
        # 等待审批 / 提问的协程挂在 store.wait 的 Event 上，abort 无法唤醒；
        # 把未决面板按取消处理，等待者即刻返回（按拒绝 / 未回答处理），
        # 否则回合（及其 busy 租约）要等面板 TTL 到期才结束。
        sid = self._session.session_id
        try:
            from permissions.store import default_permission_store

            default_permission_store().cancel_pending_for_session(sid)
        except Exception:
            logging.getLogger(__name__).debug(
                "cancel pending permissions failed", exc_info=True
            )
        try:
            from permissions.ask_store import default_ask_store

            default_ask_store().cancel_pending_for_session(sid)
        except Exception:
            logging.getLogger(__name__).debug(
                "cancel pending asks failed", exc_info=True
            )
        try:
            from engine.plan import default_plan_engine

            default_plan_engine().cancel_pending_for_session(sid)
        except Exception:
            logging.getLogger(__name__).debug(
                "cancel pending plans failed", exc_info=True
            )

    async def _maybe_advance_goal_round(
        self,
        *,
        session_id: str,
        turn_succeeded: bool,
    ) -> None:
        """T9/41 号：turn 结束钩子——flush→候选派生（只记账，不调度）。

        只在成功 turn 且会话绑定了 active goal 时做候选派生；全程 try/except
        降级，goal 层绝不杀 turn / 挡工具 / 阻塞续跑（38 号 §「刻意不做」）。
        - flush：收集本轮信号（turn_succeeded、当前 todo 清单是否全 done）。
        - 复检：``derive_candidate`` 判断是否应置候选。
        - 记账：``mark_candidate_async`` 只写 pending_complete（无变化不写、不
          bump revision）。**轮次不再在此推进**——41 号语义修正：round 数只由
          round driver 的 ``admit_round_async`` 推进，人类轮不消耗 cap。
        """
        try:
            if not turn_succeeded:
                return
            from engine.goal_state import (
                STATUS_ACTIVE,
                GoalStore,
                candidate_is_pending,
                derive_candidate,
            )

            root = str(self._session.cwd or "").strip()
            if not root or not session_id:
                return
            gstore = GoalStore(root)
            goal = gstore.current(session_id)
            if goal is None or goal.status != STATUS_ACTIVE:
                return
            todos_all_done = False
            todo_tool = self._tools.get("TodoWrite")
            if todo_tool is not None:
                todos = todo_tool.current_todos()
                todos_all_done = bool(todos) and all(
                    getattr(t, "status", "") == "completed" for t in todos
                )
            candidate = derive_candidate(
                turn_succeeded=True, todos_all_done=todos_all_done
            )
            await gstore.mark_candidate_async(
                goal.goal_id,
                revision=goal.revision,
                pending_complete=candidate_is_pending(candidate),
            )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).debug(
                "goal round advance skipped session=%s", session_id, exc_info=True
            )

    async def submit_message(
        self,
        prompt: Union[str, list[Any]],
        options: Optional[Any] = None,
    ) -> AsyncIterator[EngineEvent]:
        """引擎内互斥入口（T39 防御纵深）。

        正常路径外层已有 SessionPool busy 表 + TurnRunner 双闸；这里挡住
        进程内 CLI REPL、旁路脚本等漏检入口，保证单引擎实例同时只跑一轮。
        消息文案含 ``busy``，经 friendly_error 会翻译为「会话正忙」。
        """
        if self._turn_active:
            raise RuntimeError(
                f"engine is busy: session {self._session.session_id} "
                "already running a turn"
            )
        self._turn_active = True
        try:
            async for event in self._submit_message_inner(prompt, options):
                yield event
        finally:
            self._turn_active = False
            # 修订2（设计32）：续跑指令轮结束即清，防 contextvar 泄漏到后续轮。
            from engine.resume_directive import clear_resume_directive

            clear_resume_directive()

    async def _submit_message_inner(
        self,
        prompt: Union[str, list[Any]],
        options: Optional[Any] = None,
    ) -> AsyncIterator[EngineEvent]:
        """提交一条用户输入，驱动一整轮查询。

        工作流程：
        1. 复位环境（工作目录、清空技能发现、重置本轮预算）
        2. 将用户消息追加到历史
        3. 构建 system prompt（调用 PromptAssembler）
        4. 调用 query_loop 进行模型↔工具迭代，产生事件流
        5. 在循环中，若需持久化则每次关键事件后记录转录
        6. 循环结束后，根据终止原因（中止、预算、成功、超时等）产出最终 ResultEvent

        参数：
            prompt: 用户输入，可为字符串或消息片段列表。
            options: 预留扩展选项。

        产出：
            一系列 EngineEvent，包括 AssistantDelta 等中间事件，最后一定是 ResultEvent。
        """
        _ = options or {}
        options_dict = options if isinstance(options, dict) else {}
        # 修订2（设计32）：续跑富化指令走 contextvar → T_now 投影-only 送达
        # （env_channel 下随伪对、legacy 下随尾插，均不落库）。先清旧值防
        # 同上下文上一轮残留；落库的 user 消息只存真实用户文本。
        from engine.resume_directive import clear_resume_directive
        from engine.resume_directive import set_resume_directive

        clear_resume_directive()
        _resume_directive = str(options_dict.get("resume_directive") or "").strip()
        if _resume_directive:
            set_resume_directive(_resume_directive)
        cfg = self._config
        cwd = cfg["cwd"]
        tools = cfg["tools"]
        max_budget_usd = cfg.get("max_budget_usd")
        if max_budget_usd is None:
            max_budget_usd = cfg.get("max_budget")
        if max_budget_usd is None:
            from engine.budget import max_budget_usd_from_env

            max_budget_usd = max_budget_usd_from_env()
        custom_system_prompt = cfg.get("custom_system_prompt")
        append_system_prompt = cfg.get("append_system_prompt")
        user_specified_model = cfg.get("user_specified_model")
        # Multi-Agent chip：query_loop 在 T_now 挂软提示；不裁剪工具。
        multi_agent = bool(options_dict.get("multi_agent"))

        # 1. 入口清理和环境复位
        self._discovered_skill_names.clear()
        persist_session = not is_session_persistence_disabled()
        cwd = resolve_physical_cwd(cwd)
        self._session.cwd = cwd
        # M2：会话级工作区上下文随 async 上下文隔离；任务状态进入 running。
        turn_id = uuid.uuid4().hex[:12]
        set_workspace_context(
            WorkspaceContext(
                session_id=self._session.session_id,
                cwd=cwd,
                permission_profile=self._permission_profile,
            )
        )
        agent_mode = normalize_agent_mode(options_dict.get("agent_mode"))
        set_agent_mode(agent_mode)
        self._task_state.set_status("running", turn_id=turn_id, agent_mode=agent_mode)
        # 左段不再枚举工具名；Ask/Plan 只过滤 API tools schemas（query_loop）。
        coordinator = PermissionCoordinator(
            store=default_permission_store(),
            task_state=self._task_state,
            session_id=self._session.session_id,
            turn_id=turn_id,
            on_event=None,
        )
        start_time = time.time()
        self._session.budget.reset_for_new_submit(
            max_turns=int(cfg.get("max_turns") or DEFAULT_MAX_TURNS),
            max_tool_calling=int(
                cfg.get("max_tool_calling") or DEFAULT_MAX_TOOL_CALLING
            ),
            usd_limit=max_budget_usd,
            provider=self._provider,
            model=self._model_name,
        )
        # 重置本回合 AbortController。
        # 注意：不要继承「上一控制器已 abort」——那是 interrupt-then-new-submit 的正常清场
        # （见 test_interrupt_then_submit）。Stop 打在 try_begin→submit 窗口时，由
        # options.stop_requested 显式传入，避免信号丢失。
        self._session.abort = AbortController()
        self._abort_controller = self._session.abort
        if options_dict.get("stop_requested"):
            self._abort_controller.abort()

        # 写入本轮用户消息到历史（query_loop 会依赖 session.messages 中的最新消息）
        # 必须在首个 yield 之前完成落盘：客户端若在 TaskStateEvent 后断开，
        # 否则会丢 transcript，编辑重发/rewind 失败。
        images = None
        if isinstance(options, dict):
            raw_imgs = options.get("images")
            if isinstance(raw_imgs, list):
                images = [str(u) for u in raw_imgs if u]
        if isinstance(prompt, str):
            text = prompt
        else:
            text = " ".join(str(x) for x in prompt)
        client_user_id = options_dict.get("user_message_id")
        if isinstance(client_user_id, str) and client_user_id.strip():
            user_msg = user_message(text, images=images, message_id=client_user_id.strip())
        else:
            user_msg = user_message(text, images=images)
        self._session.messages.append(user_msg)
        self._mutable_messages.append(user_msg)

        # 用户消息必须在调厂商之前落盘：403/网络失败时也要能编辑重发与 rewind。
        if self._should_persist():
            try:
                await self._persist_transcript_delta()
                flush_transcript()
            except Exception:
                logging.getLogger(__name__).warning(
                    "pre-provider transcript persist failed",
                    exc_info=True,
                )

        yield TaskStateEvent(
            session_id=self._session.session_id,
            turn_id=turn_id,
            task_status="running",
        )

        # 建立企业级 rewind 的 turn 边界。feature flag 关闭时完全不写盘。
        turn_record = None
        rewind_context: RewindExecutionContext | None = None
        turn_source_revision_id: str | None = None
        turn_terminal_error = False
        turn_stop_reason: str | None = None
        turn_error: str | None = None
        
        # 工作区快照上下文
        before_commit: str | None = None
        after_commit: str | None = None
        before_task: asyncio.Task[str | None] | None = None
        turn_baseline = None  # v3 热路径：turn 起始 lstat 基线
        turn_baseline_task: asyncio.Task[Any] | None = None

        if self._rewind_enabled:
            # Before 快照与 system 组装 / 首轮 stream 重叠：写工具执行前再 await。
            # 失败不得放行写工具（见 query_loop ensure_before）。
            source_revision = self._revision_store.head()
            turn_source_revision_id = (
                source_revision.revision_id if source_revision else None
            )
            turn_record = self._rewind_journal.start_turn(
                revision_id=turn_source_revision_id,
                user_message_id=user_msg.id,
            )
            if turn_record is not None:
                rewind_context = RewindExecutionContext(
                    session_id=self._session.session_id,
                    turn_id=turn_record.turn_id,
                    revision_id=turn_source_revision_id,
                    journal=self._rewind_journal,
                    snapshots=self._snapshot_store,
                )
                self._active_rewind_context = rewind_context
                # v3 热路径：turn 起始 lstat 基线（仅签名不读内容；失败不阻断）。
                # 挪线程：全工作区 lstat walk 在大工作区数百 ms，同步跑会卡
                # 事件循环（SSE 心跳/权限 TTL/touch_busy 全部延迟）。
                try:
                    from rewind.index import capture_turn_baseline

                    # 后台跑，首个 delta 前不等待：全工作区 lstat walk 大仓库数百
                    # ms，同步 await 会挡在首个字符之前。turn 结束 diff 前再收齐。
                    # 2026-09-09 rewind 热路径审计：首 token 延迟的一半来源在此。
                    turn_baseline_task = asyncio.create_task(
                        asyncio.to_thread(capture_turn_baseline, cwd),
                        name=f"rewind-baseline-{turn_id}",
                    )
                except Exception:
                    turn_baseline_task = None

            async def _before_snapshot() -> str | None:
                nonlocal before_commit
                commit = await asyncio.to_thread(
                    _rewind_take_snapshot,
                    cwd,
                    self._session.session_id,
                    "Before",
                )
                before_commit = commit
                if turn_record is not None and commit:
                    try:
                        from rewind.checkpoint import (
                            derive_checkpoint_id,
                            put_checkpoint_cache,
                        )
                        from rewind.index import freeze_checkpoint

                        cp_id = derive_checkpoint_id(
                            session_id=self._session.session_id,
                            user_message_id=str(user_msg.id or ""),
                            before_commit=commit,
                        )
                        self._rewind_journal.transition_turn(
                            turn_record.turn_id,
                            "running",
                            metadata={
                                "before_commit": commit,
                                "checkpoint_id": cp_id,
                            },
                        )
                        put_checkpoint_cache(
                            self._session.session_id,
                            checkpoint_id=cp_id,
                            user_message_id=str(user_msg.id or ""),
                            before_commit=commit,
                        )
                        # v3 热路径：发送时冻结 AgentFileIndex COW checkpoint（失败不阻断）
                        # 挪线程：COW 快照有磁盘 I/O，别卡事件循环。
                        # 注意：freeze_checkpoint 不收 workspace_root——多传会
                        # TypeError 并被上面 except 吞掉，导致 checkpoints.jsonl
                        # 永远为空、弹窗永远「没有文件检查点」（e2e 回归教训）。
                        await asyncio.to_thread(
                            freeze_checkpoint,
                            self._session.session_id,
                            str(user_msg.id or ""),
                            snapshots=self._snapshot_store,
                        )
                    except Exception:
                        logging.getLogger(__name__).debug(
                            "before_commit metadata update failed",
                            exc_info=True,
                        )
                return commit

            before_task = asyncio.create_task(_before_snapshot())

        def _ensure_before() -> Any:
            """写工具前确认 Before 已成功；失败则抛给 query_loop 拦写。"""
            if before_task is None:
                return None

            async def _wait() -> str | None:
                try:
                    return await before_task
                except BaseException as exc:
                    raise RuntimeError(
                        f"Failed to create before snapshot: {exc}"
                    ) from exc

            return _wait()

        # 2. 组装 system prompt（可能包含工具描述、自定义指令等）
        main_loop_model = user_specified_model or "deepseek"
        build_parts = getattr(self._prompt, "build_system_parts", None)
        if callable(build_parts):
            system_prompt, system_breakdown = await build_parts(
                cwd=cwd,
                model=main_loop_model,
                tools=tools,
                custom_system_prompt=custom_system_prompt,
                append_system_prompt=append_system_prompt,
                date_iso=self._date_iso,
            )
        else:
            system_prompt = await self._prompt.build_system(
                cwd=cwd,
                model=main_loop_model,
                tools=tools,
                custom_system_prompt=custom_system_prompt,
                append_system_prompt=append_system_prompt,
                date_iso=self._date_iso,
            )
            system_breakdown = None

        rewind_guard = bind_context(rewind_context)
        rewind_guard.__enter__()

        # 3–6. 进入 agent 循环（query_loop 负责模型推理、工具调用、迭代）
        # 注意：斜杠命令 / transcript 等功能暂未实现（TODO）
        try:
            async for event in query_loop(
                store=self._session.messages,
                model=self._model,
                tools=self._tools,
                prompt=self._prompt,
                system_prompt=system_prompt,
                abort=self._session.abort,
                budget=self._session.budget,
                working=self._session.working,
                coordinator=coordinator,
                system_breakdown=system_breakdown,
                agent_mode=agent_mode,
                multi_agent=multi_agent,
                ensure_before=_ensure_before if before_task is not None else None,
            ):
                if isinstance(event, StoppedEvent):
                    turn_terminal_error = True
                    turn_stop_reason = event.reason
                elif isinstance(event, ResultEvent):
                    turn_terminal_error = bool(event.is_error)
                    turn_stop_reason = event.stop_reason
                yield event

                # 若需持久化，且事件不是 AssistantDelta/ReasoningDelta（防止过于频繁），记录转录
                if self._should_persist() and not isinstance(
                    event, (AssistantDelta, ReasoningDelta, ToolProgressEvent)
                ):
                    await self._persist_transcript_delta()

            # 7. 查询结束后，最终持久化一次（确保完整历史落盘）
            should_persist = persist_session and self._should_persist()
            if should_persist:
                await self._persist_transcript_delta()
                flush_transcript()   # 强制刷新缓冲区

            # 8. 从历史中提取最终回答（取最后一条 assistant 消息的内容）
            text_result = ""
            for msg in reversed(list(self._session.messages.items)):
                if getattr(msg, "role", None) == "assistant":
                    text_result = msg.content or ""
                    break

            # 9. 统计耗时、轮次，并构造最终的 ResultEvent
            duration_ms = int((time.time() - start_time) * 1000)
            num_turns = self._session.budget.turn_count
            session_id = self._session.session_id

            # T9：turn 结束钩子——只在成功 turn 且绑定 active goal 时推进 goal 轮
            # （flush→复检→预约 + round cap 32；全部 try/except 降级，绝不杀/挡 turn）。
            turn_succeeded = (
                not self._session.abort.aborted
                and not self._session.budget.over_token_budget()
                and not self._session.budget.over_budget
                and turn_stop_reason not in ("max_tool_calling", "max_turns")
                and bool(text_result)
            )
            await self._maybe_advance_goal_round(
                session_id=session_id, turn_succeeded=turn_succeeded
            )

            # 根据终止原因决定事件类型
            if self._session.abort.aborted:
                yield ResultEvent(
                    subtype="aborted",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="aborted",
                )
            elif self._session.budget.over_token_budget():
                yield ResultEvent(
                    subtype="budget",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="budget",
                )
            elif self._session.budget.over_budget:
                yield ResultEvent(
                    subtype="budget_usd",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="budget_usd",
                    budget_used_usd=round(self._session.budget.used_usd, 8),
                    budget_limit_usd=self._session.budget.usd_limit,
                )
            elif turn_stop_reason == "max_tool_calling":
                yield ResultEvent(
                    subtype="error_max_tool_calling",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="max_tool_calling",
                )
            elif turn_stop_reason == "max_turns":
                yield ResultEvent(
                    subtype="error_max_turns",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="max_turns",
                )
            elif text_result:
                yield ResultEvent(
                    subtype="success",
                    result=text_result,
                    is_error=False,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="end_turn",
                )
            elif self._session.budget.turn_count >= self._session.budget.max_turns:

                yield ResultEvent(
                    subtype="error_max_turns",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason="max_turns",
                )
            else:
                yield ResultEvent(
                    subtype="error_during_execution",
                    result="",
                    is_error=True,
                    duration_ms=duration_ms,
                    num_turns=num_turns,
                    session_id=session_id,
                    stop_reason=None,
                )
        except Exception as exc:
            turn_terminal_error = True
            turn_stop_reason = "error"
            turn_error = f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            # 厂商错误（403 等）若在首个事件前抛出，上面的循环内 persist 不会跑到；
            # 这里再兜一次，避免 transcript 缺失导致无法编辑重发。
            if persist_session and self._should_persist():
                try:
                    await self._persist_transcript_delta()
                    flush_transcript()
                except Exception:
                    logging.getLogger(__name__).warning(
                        "finally transcript persist failed",
                        exc_info=True,
                    )
            # 纯文本回合也可能还在拍 Before；收尾前收齐，供 journal metadata。
            if before_task is not None and not before_task.done():
                try:
                    await before_task
                except Exception:
                    pass
            if before_commit is None and before_task is not None and before_task.done():
                try:
                    before_commit = before_task.result()
                except Exception:
                    pass
            collect_from_tools(self._session.working, self._tools)
            if persist_session and self._should_persist():
                # WorkingSnapshot sidecar 落盘失败（磁盘满/杀毒锁文件）不得
                # 中断收尾链：后面还有 After 快照、rewind journal 终态、
                # task_state 终态与 contextvar 复位。
                try:
                    flush(self._session.session_id, self._session.working)
                except Exception:
                    logging.getLogger(__name__).warning(
                        "working snapshot flush failed session=%s",
                        self._session.session_id,
                        exc_info=True,
                    )
            try:
                from memory.memdir import workspace_id
                from memory.nightshift import maybe_schedule
                from memory.subagent_memory import enqueue_main_session_candidates

                enqueue_main_session_candidates(
                    self._session.cwd,
                    self._session.messages.items,
                    self._session.working,
                    session_id=self._session.session_id,
                )
                maybe_schedule(
                    workspace_id=workspace_id(self._session.cwd),
                    after_stop=True,
                )
                # P2-2 任务级 rollout 归档：会话结束写一次（仅主会话，红线①单写者）
                try:
                    from memory.agent_scope import may_touch_session_md
                    from memory.session_md import archive_session_rollout

                    if may_touch_session_md(
                        getattr(self._session.working, "agent_id", "main")
                    ):
                        archive_session_rollout(
                            self._session.session_id,
                            wsid=workspace_id(self._session.cwd),
                        )
                except Exception:
                    pass
            except Exception:
                logging.getLogger(__name__).debug(
                    "nightshift/main-harvest schedule failed", exc_info=True
                )

            if turn_record is not None:
                final_status = (
                    "aborted"
                    if self._session.abort.aborted
                    else "failed"
                    if turn_terminal_error
                    else "committed"
                )
                
                # 2. 为 After 快照获取跨进程工作区锁
                eligibility = "safe"
                if self._rewind_enabled:
                    try:
                        after_commit = await asyncio.to_thread(
                            _rewind_take_snapshot,
                            cwd,
                            self._session.session_id,
                            "After",
                        )
                    except Exception as e:
                        # 按 v2.4 约定，After 快照创建失败会把该 turn 标记为失败/已污染
                        final_status = "failed"
                        turn_terminal_error = True
                        turn_error = f"Failed to create after snapshot: {e}"
                        eligibility = "contaminated"
                    # v3 热路径：turn 结束差量同步 AgentFileIndex（Bash 等兜底；失败不阻断）
                    if turn_baseline_task is not None:
                        try:
                            turn_baseline = await turn_baseline_task
                        except Exception:
                            turn_baseline = None
                    if turn_baseline is not None:
                        try:
                            from rewind.index import sync_index_from_turn_diff

                            # 挪线程保序执行：diff 二次全树 walk + 变化文件读盘入
                            # blob + 逐行 fsync，大仓库数百 ms；同步跑在事件循环会
                            # 卡住 SSE 心跳 / 其它会话（2026-09-09 rewind 热路径审计）。
                            await asyncio.to_thread(
                                sync_index_from_turn_diff,
                                self._session.session_id,
                                turn_baseline,
                                snapshots=self._snapshot_store,
                                workspace_root=cwd,
                            )
                        except Exception:
                            pass
                try:
                    message_ids = tuple(
                        message.id
                        for message in self._session.messages.items
                        if message.id
                    )
                    assistant_message_id = next(
                        (
                            message.id
                            for message in reversed(self._session.messages.items)
                            if message.role == "assistant" and message.id
                        ),
                        None,
                    )
                    operation_ids = tuple(rewind_context.operation_ids) if rewind_context else ()
                    updated = self._rewind_journal.transition_turn(
                        turn_record.turn_id,
                        final_status,
                        error=turn_error,
                        message_ids=message_ids,
                        operation_ids=operation_ids,
                        assistant_message_id=assistant_message_id,
                        stop_reason=turn_stop_reason,
                        metadata={
                            "before_commit": before_commit,
                            "after_commit": after_commit,
                            "eligibility": eligibility,
                        } if before_commit or after_commit else None,
                    )
                    if updated is not None and before_commit and final_status in {
                        "committed",
                        "failed",
                    }:
                        revision = self._revision_store.commit_turn(
                            turn_record.turn_id,
                            message_ids=message_ids,
                            parent_revision_id=turn_source_revision_id,
                            workspace_root=self._session.cwd,
                            metadata={
                                "operation_count": len(operation_ids),
                                "turn_status": final_status,
                            },
                        )
                        if revision is None:
                            raise RuntimeError("rewind revision commit returned no revision")
                        self._rewind_journal.transition_turn(
                            turn_record.turn_id,
                            final_status,
                            revision_id=revision.revision_id,
                        )
                        self._rewind_journal.audit(
                            "turn_committed",
                            revision_id=revision.revision_id,
                            turn_id=turn_record.turn_id,
                            payload={
                                "operation_count": len(operation_ids),
                                "turn_status": final_status,
                            },
                        )
                    else:
                        self._rewind_journal.audit(
                            "turn_finished",
                            revision_id=turn_source_revision_id,
                            turn_id=turn_record.turn_id,
                            payload={"status": final_status, "error": turn_error},
                        )
                except Exception as rewind_error:
                    # Rewind 记账必须可见，但不能把一次成功的
                    # 模型响应变成不透明的服务器错误。
                    try:
                        self._rewind_journal.audit(
                            "rewind_recording_failed",
                            revision_id=turn_source_revision_id,
                            turn_id=turn_record.turn_id,
                            payload={"error": f"{type(rewind_error).__name__}: {rewind_error}"[:2000]},
                        )
                    except Exception:
                        pass
            self._active_rewind_context = None
            # M2：写任务状态终态（供 /health / API 查询；不作为流事件，避免干扰 ResultEvent 序列）。
            terminal_status = (
                "stopped"
                if self._session.abort.aborted
                else "failed"
                if turn_terminal_error
                else "succeeded"
            )
            self._task_state.set_status(terminal_status, error=turn_error)
            set_agent_mode(None)
            # 释放会话级工作区上下文，避免同一 asyncio 任务内跨次提交泄漏 cwd。
            set_workspace_context(None)
            rewind_guard.__exit__(None, None, None)

    async def submit(
        self,
        prompt: Union[str, list[Any]],
        options: Optional[Any] = None,
        *,
        images: list[str] | None = None,
    ) -> AsyncIterator[EngineEvent]:
        """``submit_message`` 的短别名，供 app.py / SessionPool 等外部调用。"""
        from contextlib import aclosing

        opts = options
        if images:
            merged = dict(opts) if isinstance(opts, dict) else {}
            merged["images"] = images
            opts = merged
        # T39：aclosing 保证调用方 aclose/GC 时 GeneratorExit 传播到
        # submit_message 的护栏 finally，_turn_active 立即复位而非等 finalizer。
        async with aclosing(self.submit_message(prompt, opts)) as stream:
            async for event in stream:
                yield event


def _default_context_limit(provider: str, model: str) -> int | None:
	"""为缺失 context_limit 的客户端提供保守默认窗口（G67）。

	- ``XEYO_CONTEXT_LIMIT`` 显式覆盖（>0 生效）;
	- deepseek 路径固定 65536（不再让 C2 三触发点因 None 全哑）;
	- 已知大窗 OpenAI 型号给 128k;未知型号返回 None——宁可不压,也不拿错窗口压。
	"""
	import os

	raw = (os.environ.get("XEYO_CONTEXT_LIMIT") or "").strip()
	if raw:
		try:
			return max(4096, int(raw))
		except ValueError:
			return None
	provider_key = (provider or "").lower()
	model_key = (model or "").lower()
	if provider_key == "deepseek":
		return 65536
	if provider_key in ("openai", "local") and (
		model_key.startswith("gpt-4o")
		or model_key.startswith("gpt-4.1")
		or model_key.startswith("o1")
		or model_key.startswith("o3")
		or model_key.startswith("gpt-5")
	):
		return 128_000
	return None


def build_default_engine(
    *,
    max_turns: int = 50,
    max_tool_calling: int = DEFAULT_MAX_TOOL_CALLING,

    cwd: str | None = None,
    model_backend: str | None = None,
    session_id: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    initial_messages: list[Message] | None = None,
) -> QueryEngine:
    """为 CLI 或测试构建默认的查询引擎。

    参数：
                max_turns: 最大对话轮数。
        max_tool_calling: 每个模型 Turn 的最大工具执行次数。
        cwd: 工作目录，若未指定则使用当前工作目录。

        model_backend: 模型后端，支持 "deepseek"（默认）、"fake"（测试）、
                      "openai" / "local"（走 OpenAI 兼容客户端）。
                      也可通过环境变量 XEYO_MODEL 覆盖。
        session_id: 与磁盘 transcript 共用的会话键。
        api_key / provider / model / base_url: CLI/配置文件注入的连接信息。
        initial_messages: 冷启动 hydrate 的历史消息。

    返回：
        配置好的 QueryEngine 实例。
    """
    import os

    from tools.catalog import build_default_registry

    work_cwd = cwd or os.getcwd()
    # 构建默认工具注册表（包含文件操作、bash、编辑等基础工具）
    registry = build_default_registry(cwd=work_cwd)

    # 确定后端
    backend = (
        model_backend
        or provider
        or os.environ.get("XEYO_MODEL")
        or "deepseek"
    ).lower()
    if backend == "auto":
        backend = "deepseek"

    if backend == "fake":
        # FakeModelClient 契约使用 echo 工具；echo 刻意不在 ENABLED_TOOLS
        # （meta: 仅策略/测试用），fake 后端按需注入。
        from tools.echo import EchoTool

        registry.register(EchoTool())

    # 身份与 Tool policy 在 PromptAssembler 左段；此处不再 append 第二段 You-are。

    # 根据后端创建对应的模型客户端
    resolved_provider = backend
    resolved_model_name = model
    if backend == "fake":
        from model.fake import FakeModelClient
        model_client: ModelClient = FakeModelClient()
        resolved_provider = "fake"
        resolved_model_name = resolved_model_name or "fake"
    elif backend in ("openai", "local") or (
        api_key and backend in ("deepseek", "openai", "local")
    ):
        from model.openai_compat import OpenAICompatClient, PROVIDER_PRESETS

        preset = PROVIDER_PRESETS.get(backend) or PROVIDER_PRESETS["deepseek"]
        key = (api_key or "").strip()
        if not key:
            if backend == "deepseek":
                key = (
                    os.environ.get("DEEPSEEK_API_KEY")
                    or os.environ.get("XEYO_MODEL_API_KEY")
                    or ""
                ).strip()
            elif backend == "openai":
                key = (
                    os.environ.get("OPENAI_API_KEY")
                    or os.environ.get("XEYO_MODEL_API_KEY")
                    or ""
                ).strip()
            else:
                key = (os.environ.get("XEYO_MODEL_API_KEY") or "local").strip()
        if not key and backend != "local":
            raise ValueError(f"api key required for provider {backend}")
        if backend == "local" and not key:
            key = "local"
        url = (base_url or "").strip() or preset["base_url"]
        resolved_model_name = (
            resolved_model_name
            or os.environ.get("XEYO_MODEL_NAME")
            or ("deepseek-chat" if backend == "deepseek" else "gpt-4o-mini")
        )
        model_client = OpenAICompatClient(
            api_key=key,
            base_url=url,
            model=resolved_model_name,
            provider=backend if backend in PROVIDER_PRESETS else "openai",
            session_id=session_id or "",
        )
        resolved_provider = backend if backend in PROVIDER_PRESETS else "openai"
    elif backend == "deepseek":
        from model.deepseek import DeepSeekModelClient
        model_client = DeepSeekModelClient()
        resolved_provider = "deepseek"
        resolved_model_name = (
            resolved_model_name
            or getattr(model_client, "_model", None)
            or "deepseek-v4-flash"
        )
    else:
        raise ValueError(f"unknown model backend: {backend}")

    from model.vision_capability import supports_vision_input
    from tools.catalog import apply_read_vision

    model_name = str(
        resolved_model_name
        or getattr(model_client, "_model", None)
        or getattr(model_client, "model", "")
        or ""
    )
    provider_name = str(
        getattr(model_client, "provider", None)
        or getattr(model_client, "_provider", "")
        or resolved_provider
    )
    apply_read_vision(
        registry,
        enabled=supports_vision_input(provider=provider_name, model=model_name),
    )

    # G67: context_limit 断链修复——CLI/DeepSeek 路径原来不设 context_limit,
    # None 使 C2 压力/收益门恒不触发(长会话无界增长直到厂商 400)。仅当客户端
    # 没有已知窗口(usage 尾帧/显式配置)时注入保守默认。
    if not getattr(model_client, "context_limit", None) and resolved_provider != "fake":
        _ctx_default = _default_context_limit(provider_name, model_name)
        if _ctx_default:
            model_client.context_limit = _ctx_default

    # F1：MCP 运行时接线（扩展层关 = 一次读盘 no-op；21 内置工具零变化）。
    try:
        from extension.mcp_manager import attach_mcp_tools

        attach_mcp_tools(registry, work_cwd)
    except Exception:  # noqa: BLE001 — 单点接线失败不挡引擎构建
        logging.getLogger(__name__).warning("mcp attach failed", exc_info=True)

    # 46号：侧挂模块升格（默认开，可由 XEYO_SIDEMOD_PROMOTE=0 一键回退）。
    # 与 MCP attach 同款 fail-open：单模块失败不挡引擎构建；升格关时 apply() 返回 False（空操作）。
    try:
        from sidecar.upgrade import apply as _apply_sidecar_promote

        _apply_sidecar_promote()
    except Exception:  # noqa: BLE001 — 单点升格失败不挡引擎构建
        logging.getLogger(__name__).warning("sidecar promote apply failed", exc_info=True)

    # 共享 PromptAssembler（主会话与子 agent 一致，便于复用缓存/前缀）
    shared_assembler: PromptAssembler = PromptAssembler()

    # 子 agent：A3 稳定前缀（工人角色；append 段已随理念裁决 A2 删除）
    from engine.subagent_runner import SubagentRuntime
    from tools.catalog import inject_subagent_runtime, shared_read_state

    def _subagent_runtime_provider() -> SubagentRuntime:
        return SubagentRuntime(
            model_client=model_client,
            prompt_assembler=shared_assembler,
            workspace_root=work_cwd,
            date_iso=date.today().isoformat(),
            read_state=shared_read_state(registry),
        )

    inject_subagent_runtime(registry, _subagent_runtime_provider)

    # 组装配置
    config: QueryEngineConfig = {
        "cwd": work_cwd,
        "tools": registry,
        "model_client": model_client,
        "prompt_assembler": shared_assembler,
        "append_system_prompt": "",
        "user_specified_model": model_name or None,
        "provider": resolved_provider if resolved_provider in ("deepseek", "openai", "local", "fake") else "deepseek",
        "model": model_name or "deepseek-v4-flash",
        "max_turns": max_turns,
        "max_tool_calling": max_tool_calling,
    }
    sid = (session_id or "").strip()
    if sid:
        config["session_id"] = sid
        # 跨会话共享记忆：登记会话 → 工作区归属（幂等），供
        # memory.search.search_session_notes 跨重启圈定同工作区对话。
        try:
            from session.ws_index import record_session_workspace

            record_session_workspace(sid, work_cwd)
        except Exception:  # noqa: BLE001 — 索引失败绝不挡引擎构建
            logging.getLogger(__name__).debug(
                "workspace index record failed", exc_info=True
            )
    if initial_messages:
        config["initial_messages"] = list(initial_messages)

    return QueryEngine(config)
