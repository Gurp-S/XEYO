"""子 Agent 运行器：用**独立 query_loop**驱动一个受限子 agent + 侧链。

设计（多 Agent 协同落地 #29 §3 / 附录 C）：
- **不重建 QueryEngine 上帝对象**：直接复用 `query_loop`，组件各自独立拆装：
  `MessageStore(任务 prompt)` / `BudgetTracker(小预算)` / `WorkingSnapshot(agent_id)` /
  `AbortController(独立)` / `build_subagent_registry`(注入 write_store+agent_id) /
  `build_subagent_context`(短上下文，A3 前缀稳定)。
- **短上下文**：`[base_prefix]`(稳定) 在最前，`task_prompt`+`recent_changes`(动态) 只在尾部（A3）。
- **侧链**：`record_transcript(path=.../agents/{agent_id}.jsonl)`，**不 append 主 JSONL**（§3.1）。
- **递归控制**：调用方负责 `_depth`/`max_depth`；`build_subagent_registry` 已剔除 `_agent`（A8）。
- 子 agent `_depth>=1` 不得等待跨 Agent DAG 任务（B1）——本模块只做纯工具驱动，不涉 DAG。

注意：骨架。`model_client`/`prompt_assembler`/`coordinator` 由调用方注入；真正执行依赖模型客户端。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Any

DEFAULT_SUB_MAX_TURNS = 32
DEFAULT_SUB_MAX_TOOL_CALLING = 64
DEFAULT_SUB_RO_MAX_TURNS = 16
DEFAULT_SUB_RO_MAX_TOOL_CALLING = 32


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def subagent_budgets_for_scope(scope_paths: list[str]) -> tuple[int, int]:
    """只读工人更低轮次上限（省钱）；可写保持默认。可用环境变量覆盖。"""
    if scope_paths:
        return (
            _env_int("XEYO_SUB_MAX_TURNS", DEFAULT_SUB_MAX_TURNS),
            _env_int("XEYO_SUB_MAX_TOOL_CALLING", DEFAULT_SUB_MAX_TOOL_CALLING),
        )
    return (
        _env_int("XEYO_SUB_RO_MAX_TURNS", DEFAULT_SUB_RO_MAX_TURNS),
        _env_int("XEYO_SUB_RO_MAX_TOOL_CALLING", DEFAULT_SUB_RO_MAX_TOOL_CALLING),
    )


def _followup_max_turns() -> int:
    """follow-up 续跑轮次上限（省钱：短预算，不复用首轮大预算）。"""
    return _env_int("XEYO_SUB_FOLLOWUP_MAX_TURNS", 12)


def _followup_max_tool_calling() -> int:
    return _env_int("XEYO_SUB_FOLLOWUP_MAX_TOOL_CALLING", 24)


def _followup_limit() -> int:
    """每 agent 的 follow-up 循环次数上限（防刷）。"""
    return _env_int("XEYO_SUB_FOLLOWUP_LIMIT", 3)


def _followup_user_text(text: str) -> str:
    """follow-up 在侧链里的触发消息：复用 [Resume] 契约 + 真实 follow-up 文本。"""
    return f"[Resume] Continue.\n\nUser follow-up:\n{(text or '').strip()}"


# 运行中侧链增量落盘的最小间隔（秒）：GUI 每 2s 轮询一次，
# 1s 的落盘节拍足够跟上轮询且几乎不增加 IO 压力。
_LIVE_FLUSH_INTERVAL_S = 1.0


class _StreamingTeeClient:
    """透传型模型客户端包装：把 ``text_delta`` 文本增量镜像给回调。

    用途：SSE 流式回放子 agent 输出（chat 层把回调转成 multi_agent_delta 帧）。
    除 stream() 外的属性与方法全部转发给底层客户端；增量 chunk 本身照常
    yield，query_loop 的行为与不包一层时完全一致。回调异常一律吞掉。
    """

    def __init__(self, inner: Any, on_text_delta: Any) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_cb", on_text_delta)

    def __getattr__(self, name: str) -> Any:
        # 仅在常规属性查找失败时触发；_inner/_cb 在 __init__ 已设置。
        return getattr(object.__getattribute__(self, "_inner"), name)

    async def stream(self, messages: Any, tools: Any, abort: Any):
        inner = object.__getattribute__(self, "_inner")
        cb = object.__getattribute__(self, "_cb")
        async for chunk in inner.stream(messages, tools, abort):
            try:
                if getattr(chunk, "kind", "") == "text_delta":
                    text = getattr(chunk, "text", "") or ""
                    if text:
                        cb(str(text))
            except Exception:  # noqa: BLE001
                pass
            yield chunk


@dataclass
class SubagentRuntime:
    """子 agent 运行时（由编排层注入）：提供驱动 loop 所需的模型客户端与系统提示参数。

    ``base_prefix`` 不在这里硬编码——它由 run_subagent 按**子 agent 工具集**经
    ``prompt_assembler.build_system`` 生成的稳定前缀（A3）；这里只给生成所需的最小参数。
    """
    model_client: Any
    prompt_assembler: Any
    workspace_root: str | Path
    append_system_prompt: str = ""     # 基础系统提示（如 identity + tools hint）
    date_iso: str = ""                 # 固化日期，保证左段字节稳定
    # 与主会话同册的 ReadFileState；缺省时子 agent 自建（会破坏主会话
    # 的 Edit 新鲜度校验，见 catalog.shared_read_state）。
    read_state: Any | None = None


@dataclass
class SubagentRunResult:
    """子 agent 运行结果（回传给主会话一条 tool_result）。"""
    conclusion: str = ""
    files_touched: list[str] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)  # MemoryCandidate[]
    is_error: bool = False
    stop_reason: str = ""
    had_write_stale: bool = False
    turns_used: int = 0
    max_turns: int = 0
    read_only: bool = False


async def run_subagent(
    *,
    workspace_root: str | Path,
    agent_id: str,
    task_prompt: str,
    tool_whitelist: list[str],
    model_client: Any,
    prompt_assembler: Any,
    write_store: Any,
    main_session_id: str,
    recent_changes: str = "",
    coordinator: Any = None,
    abort: Any = None,
    max_turns: int = DEFAULT_SUB_MAX_TURNS,
    max_tool_calling: int = DEFAULT_SUB_MAX_TOOL_CALLING,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    append_system_prompt: str = "",
    date_iso: str = "",
    on_text_delta: Any = None,
    task_batch_id: str = "",
    session_id: str = "",
    task_id: str = "",
    write_scope_paths: list[str] | None = None,
    read_state: Any | None = None,
    allow_followups: bool = True,
) -> SubagentRunResult:
    """spawn 一个子 agent 并驱动 query_loop；写侧链；返回可回传的结果。

    A3 稳定前缀：由 ``prompt_assembler.build_system`` 按**子 agent 工具集**（reg）
    生成，再经 ``build_subagent_context`` 把 task_prompt + recent_changes 追加到尾部。

    ``write_scope_paths``：写路径硬门禁；``None`` 表示调用方未声明（按空 scope=只读），
    显式列表限制可写前缀。

    ``allow_followups``：P2 follow-up inbox 开关——首轮 settle 后消费 ``drain_agent_inbox``
    里排队给该 agent 的消息，同实例续跑（短预算），侧链自然延续，GUI 卡片无感知。
    """
    from engine.abort import AbortController
    from permissions.write_scope import write_scope as write_scope_cm

    abort = abort if abort is not None else AbortController()
    if getattr(abort, "aborted", False):
        return SubagentRunResult(
            conclusion="interrupted", is_error=True, stop_reason="aborted"
        )

    # 空列表 = 只读工人；None 也按空处理（子 Agent 必须显式声明 scope 才能写）。
    scope_paths = list(write_scope_paths) if write_scope_paths is not None else []
    ro_turns, ro_tools = subagent_budgets_for_scope(scope_paths)
    # 仅当调用方传的是"默认值"标记时按只读/可写套预算；调用方显式给出更大的
    # 上限(如调度器按 timeout 推导的轮次)必须尊重，不得被强行改小(grace 修复)。
    if max_turns == DEFAULT_SUB_MAX_TURNS:
        max_turns = ro_turns
    if max_tool_calling == DEFAULT_SUB_MAX_TOOL_CALLING:
        max_tool_calling = ro_tools

    # T14：标记子代理上下文——pre_llm_inject 的净化清单据此跳过易变块
    # （peer presence / 文件冲突 / 浏览器预览 / repeat guard 等）。
    from permissions.policy import set_in_subagent

    set_in_subagent(True)
    try:
        with write_scope_cm(scope_paths):
            out = await _run_subagent_body(
                workspace_root=workspace_root,
                agent_id=agent_id,
                task_prompt=task_prompt,
                tool_whitelist=tool_whitelist,
                model_client=model_client,
                prompt_assembler=prompt_assembler,
                write_store=write_store,
                main_session_id=main_session_id,
                recent_changes=recent_changes,
                coordinator=coordinator,
                abort=abort,
                max_turns=max_turns,
                max_tool_calling=max_tool_calling,
                provider=provider,
                model=model,
                append_system_prompt=append_system_prompt,
                date_iso=date_iso,
                on_text_delta=on_text_delta,
                task_batch_id=task_batch_id,
                session_id=session_id,
                task_id=task_id,
                write_scope_paths=scope_paths,
                read_state=read_state,
                allow_followups=allow_followups,
            )
            out.read_only = len(scope_paths) == 0
            out.max_turns = max_turns
            return out
    finally:
        set_in_subagent(False)


async def _run_subagent_body(
    *,
    workspace_root: str | Path,
    agent_id: str,
    task_prompt: str,
    tool_whitelist: list[str],
    model_client: Any,
    prompt_assembler: Any,
    write_store: Any,
    main_session_id: str,
    recent_changes: str = "",
    coordinator: Any = None,
    abort: Any = None,
    max_turns: int = DEFAULT_SUB_MAX_TURNS,
    max_tool_calling: int = DEFAULT_SUB_MAX_TOOL_CALLING,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    append_system_prompt: str = "",
    date_iso: str = "",
    on_text_delta: Any = None,
    task_batch_id: str = "",
    session_id: str = "",
    task_id: str = "",
    write_scope_paths: list[str] | None = None,
    read_state: Any | None = None,
    allow_followups: bool = True,
) -> SubagentRunResult:
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from engine.subagent_context import build_subagent_context
    from memory.subagent_memory import (
        SUBAGENT_MEMORY_INSTRUCTION,
        collect_files_touched,
        harvest_subagent_memories,
    )
    from memory.working import WorkingSnapshot
    from msgtypes.events import FinalEvent, ResultEvent, StoppedEvent
    from msgtypes.message import user_message
    from session.message_store import MessageStore
    from tools.catalog import build_subagent_registry
    from tools.fileio.read_state import ReadFileState

    # 1) 注入式受限工具注册表（多 Agent 写路径：写工具拿到 write_store）
    reg = build_subagent_registry(
        cwd=str(workspace_root),
        tool_names=tool_whitelist,
        read_state=read_state or ReadFileState(),
        write_store=write_store,
        agent_id=agent_id,
    )
    sub_tool_names = sorted(getattr(reg, "_tools", {}).keys())

    # 2) A3 稳定前缀：瘦工人提示——不含 XEYO.md / Memory 索引；再 + 动态尾部
    build_parts = getattr(prompt_assembler, "build_system_parts", None)
    if callable(build_parts):
        base_prefix, _breakdown = await build_parts(
            cwd=str(workspace_root), model=model, tools=reg,
            custom_system_prompt=None, append_system_prompt=append_system_prompt,
            date_iso=date_iso, tool_names=sub_tool_names,
            include_context_blocks=False,
        )
    else:
        base_prefix = await prompt_assembler.build_system(
            cwd=str(workspace_root), model=model, tools=reg,
            custom_system_prompt=None, append_system_prompt=append_system_prompt,
            date_iso=date_iso, tool_names=sub_tool_names,
            include_context_blocks=False,
        )
    ctx = build_subagent_context(
        base_prefix=base_prefix,
        task_prompt=f"{task_prompt.rstrip()}\n\n{SUBAGENT_MEMORY_INSTRUCTION}",
        recent_changes=recent_changes,
        tool_whitelist=tool_whitelist,
    )

    # 2) 独立会话组件
    import time

    started_ts = time.time()
    # 续跑：若同 agent_id 侧链已有对话，接着跑，避免把 Glob/Read 再做一遍。
    sidechain = _sidechain_path(main_session_id, agent_id)
    prior_msgs: list[Any] = []
    try:
        from session.hydrate import messages_from_transcript

        prior_msgs = messages_from_transcript(sidechain)
    except Exception:  # noqa: BLE001
        prior_msgs = []
    if prior_msgs:
        # 侧链已有对话：追加一轮极短续跑触发，由历史本身承接上下文。
        sub_store = MessageStore(
            initial=[*prior_msgs, user_message("[Resume] Continue.")]
        )
    else:
        sub_store = MessageStore(initial=[user_message(task_prompt)])
    budget = BudgetTracker(
        max_turns=max(1, max_turns), max_tool_calling=max(1, max_tool_calling)
    )
    budget.provider = provider
    budget.model = model
    from memory.agent_scope import scoped_session_id

    snap = WorkingSnapshot(
        session_id=scoped_session_id(main_session_id, agent_id),
        agent_id=agent_id,
    )
    abort = abort if abort is not None else AbortController()

    # 2.5) 元数据先行落盘（best-effort）：卡片即刻存在且状态为「运行中」，
    #      GUI 据此进入子视图轮询增量侧链，实现运行中实时回放输出。
    try:
        upsert_subagent_meta(
            main_session_id,
            agent_id=agent_id,
            task_desc=task_prompt,
            status="running",
            started_at=started_ts,
            task_id=task_id,
            write_scope=list(write_scope_paths or []),
        )
    except Exception:  # noqa: BLE001
        pass

    # 3) 驱动 loop，收集 final result；循环内周期性把 store 增量追加到侧链
    #    （按消息 id 去重，见 record_transcript），运行中即可被轮询读取。
    result = SubagentRunResult()
    live_known: set[str] = set()
    live_persist_index = 0
    if prior_msgs:
        # 历史已在侧链；只追加本轮新消息，避免重复写入旧行。
        live_persist_index = len(prior_msgs)
        for msg in prior_msgs:
            mid = getattr(msg, "id", None)
            if isinstance(mid, str) and mid.strip():
                live_known.add(mid.strip())

    async def _flush_live_transcript() -> None:
        """把当前 store 增量追加到侧链 JSONL（失败静默，不阻断子 agent）。"""
        nonlocal live_persist_index
        try:
            from session.record_transcript import record_transcript

            items = sub_store.items
            if live_persist_index >= len(items):
                return
            await record_transcript(
                items[live_persist_index:],
                session_id=agent_id,
                path=sidechain,
                session_persistence_disabled=False,
                known_ids=live_known,
            )
            live_persist_index = len(items)
        except Exception:  # noqa: BLE001
            pass

    # 厂商调用前先把本轮用户/续跑触发落盘，避免 403 后侧链缺首条。
    await _flush_live_transcript()
    try:
        from session.record_transcript import flush_transcript

        flush_transcript(sidechain)
    except Exception:  # noqa: BLE001
        pass

    last_flush_mono = 0.0
    # 流式回放：包装 model_client，把 text_delta 镜像给 on_text_delta 回调
    # （chat 层转成 multi_agent_delta SSE 帧）。回调异常不影响子任务本身。
    effective_client: Any = model_client
    if callable(on_text_delta):
        effective_client = _StreamingTeeClient(model_client, on_text_delta)

    async def _do_cycle(budget_obj: Any) -> None:
        """跑一轮 query_loop；把终态写进 ``result``（最后轮覆盖，符合 follow-up 语义）。"""
        nonlocal result, last_flush_mono
        try:
            async for event in query_loop(
                store=sub_store,
                model=effective_client,
                tools=reg,
                prompt=prompt_assembler,
                system_prompt=ctx.system_prompt,
                abort=abort,
                budget=budget_obj,
                working=snap,
                coordinator=coordinator,
                agent_mode="agent",
                include_memory_index=False,
            ):
                if isinstance(event, FinalEvent):
                    result.conclusion = event.text      # text-only 正常结束
                    result.stop_reason = "finished"
                elif isinstance(event, ResultEvent):
                    result.conclusion = event.result
                    result.is_error = bool(event.is_error)
                    result.stop_reason = str(event.stop_reason or "")
                elif isinstance(event, StoppedEvent):
                    result.stop_reason = str(event.reason or "")
                now_mono = time.monotonic()
                if now_mono - last_flush_mono >= _LIVE_FLUSH_INTERVAL_S:
                    last_flush_mono = now_mono
                    await _flush_live_transcript()
        except Exception as exc:  # noqa: BLE001
            from common.errors import friendly_error

            result.conclusion = friendly_error(exc)
            result.is_error = True
            result.stop_reason = "error"
        finally:
            # 收尾：补齐尾部增量并排空后台写队列，保证磁盘与内存一致；
            # 这样步骤 4 的全量 record_transcript 扫盘去重后不会重复追加。
            await _flush_live_transcript()
            try:
                from session.record_transcript import flush_transcript

                flush_transcript(sidechain)
            except Exception:  # noqa: BLE001
                pass

    followup_budget: Any = None
    cycle_no = 0
    while True:
        # 首轮用调用方预算；follow-up 轮用小预算（省钱 + 防刷）。
        b = budget if cycle_no == 0 else followup_budget
        await _do_cycle(b)

        # P2 follow-up inbox：首轮 settle 后消费排队给该 agent 的消息，同实例续跑。
        # 「park 而非注入、回合边界投递」——当前工具调用窗口即本 agent 的回合边界。
        if not allow_followups or abort.aborted:
            break
        if cycle_no >= _followup_limit():
            break
        from engine.live_agents import drain_agent_inbox, post_to_agent

        followups = drain_agent_inbox(main_session_id, agent_id)
        if not followups:
            break
        # 只消费第一条；其余放回（保持 FIFO 顺序，下轮再取）。
        first = followups[0]
        for fut in followups[1:]:
            post_to_agent(
                main_session_id,
                agent_id,
                str(fut.get("text") or ""),
                message_id=str(fut.get("message_id") or ""),
            )
        sub_store.append(user_message(_followup_user_text(first["text"])))
        if followup_budget is None:
            followup_budget = BudgetTracker(
                max_turns=_followup_max_turns(),
                max_tool_calling=_followup_max_tool_calling(),
            )
            followup_budget.provider = provider
            followup_budget.model = model
        cycle_no += 1

    # 4) 侧链兜底全量写（增量收尾已落绝大部分；此处扫盘去重补齐）+ snapshot 持久化
    try:
        from session.record_transcript import record_transcript

        await record_transcript(
            sub_store.items[live_persist_index:],
            session_id=agent_id,
            path=sidechain,
            session_persistence_disabled=False,
            known_ids=live_known,
        )
    except Exception:  # noqa: BLE001
        # 侧链失败不阻断子 agent 结果；仅供调试/审计。
        pass
    try:
        _flush_subagent_snapshot(main_session_id, agent_id, snap)
    except Exception:  # noqa: BLE001
        # snapshot 持久化失败不阻断结果
        pass

    # 5) 元数据落盘（UI 卡片 / 历史回放数据源；best-effort）
    try:
        stop = result.stop_reason or ""
        status = (
            "error" if result.is_error else ("stopped" if stop and stop != "finished" else "done")
        )
        upsert_subagent_meta(
            main_session_id,
            agent_id=agent_id,
            task_desc=task_prompt,
            status=status,
            started_at=started_ts,
            finished_at=time.time(),
            result_preview=result.conclusion,
            has_transcript=sidechain.is_file(),
        )
    except Exception:  # noqa: BLE001
        pass

    memories, clean_conclusion = harvest_subagent_memories(
        sub_store.items,
        snap,
        main_session_id=main_session_id,
        agent_id=agent_id,
        conclusion=result.conclusion,
    )
    if clean_conclusion:
        result.conclusion = clean_conclusion
    result.conclusion = _usable_conclusion(sub_store.items, result.conclusion)
    result.memories = memories
    result.files_touched = collect_files_touched(sub_store.items)
    result.had_write_stale = _detect_write_stale(sub_store.items)
    result.turns_used = int(getattr(budget, "turn_count", 0) or 0) + int(
        getattr(followup_budget, "turn_count", 0) or 0
    )
    result.max_turns = max(
        int(getattr(budget, "max_turns", 0) or 0),
        int(getattr(followup_budget, "max_turns", 0) or 0),
    )

    if budget.last_usage and task_batch_id:
        try:
            from usage.multi_agent_metrics import record_subagent_usage

            record_subagent_usage(
                task_batch_id=task_batch_id,
                session_id=session_id or main_session_id,
                agent_id=agent_id,
                task_id=task_id or agent_id,
                usage=budget.last_usage,
            )
        except Exception:  # noqa: BLE001
            pass

    return result


def _usable_conclusion(messages: list[Any], conclusion: str) -> str:
    """若结论是未执行的 XML tool_call，回退到侧链里最近一段可读 assistant 正文。"""
    from engine.xml_tool_call import looks_like_raw_tool_markup

    text = (conclusion or "").strip()
    if text and not looks_like_raw_tool_markup(text):
        return text
    fallback = ""
    for msg in reversed(list(messages or [])):
        if getattr(msg, "role", "") != "assistant":
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            candidate = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ):
                    t = block["text"].strip()
                    if t:
                        parts.append(t)
            candidate = "\n".join(parts).strip()
        else:
            continue
        if candidate and not looks_like_raw_tool_markup(candidate):
            fallback = candidate
            break
    if fallback:
        return fallback
    return text


_STALE_WRITE_NEEDLES = (
    "unexpectedly modified",
    "write conflict",
    "missing_read",
)


def _detect_write_stale(messages: list[Any]) -> bool:
    """侧链 tool 行是否出现过 write-store stale / conflict。"""
    for msg in messages:
        role = getattr(msg, "role", "")
        if role != "tool":
            continue
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            text = " ".join(
                str(p.get("text", "") if isinstance(p, dict) else p) for p in content
            )
        else:
            text = str(content or "")
        low = text.lower()
        if any(n in low for n in _STALE_WRITE_NEEDLES):
            return True
    return False


def _sidechain_dir(main_session_id: str) -> Path:
    """子 agent 侧链目录：~/.xeyo/sessions/{main_session}/agents。"""
    safe_main = _safe(main_session_id)
    return Path.home() / ".xeyo" / "sessions" / safe_main / "agents"


def _flush_subagent_snapshot(
    main_session_id: str, agent_id: str, snap: Any
) -> None:
    """把子 agent 的 WorkingSnapshot（含 agent_id）持久化到侧链目录（agent_id snapshot）。"""
    import os

    d = _sidechain_dir(main_session_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_safe(agent_id)}.working.json"
    payload = {
        "agent_id": agent_id,
        "main_session_id": main_session_id,
        "to_dict": getattr(snap, "__dict__", {}),
    }
    tmp = path.with_name(path.name + ".tmp")
    import json

    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _meta_path(main_session_id: str, agent_id: str) -> Path:
    """子 agent 元数据：`~/.xeyo/sessions/{main}/agents/{agent_id}.meta.json`。"""
    return _sidechain_dir(main_session_id) / f"{_safe(agent_id)}.meta.json"


def clear_sidechain(main_session_id: str, agent_id: str) -> None:
    """删除子 agent 侧链 transcript / working，保留 meta 供卡片身份；重试用。"""
    d = _sidechain_dir(main_session_id)
    stem = _safe(agent_id)
    for name in (f"{stem}.jsonl", f"{stem}.working.json"):
        path = d / name
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def upsert_subagent_meta(
    main_session_id: str,
    *,
    agent_id: str,
    task_desc: str,
    status: str,
    task_id: str = "",
    started_at: float = 0.0,
    finished_at: float = 0.0,
    result_preview: str = "",
    has_transcript: bool | None = None,
    write_scope: list[str] | None = None,
    pending_followups: list[str] | None = None,
) -> None:
    """写/更新子 agent 元数据（best-effort）：UI 卡片列表与历史回放的数据源。

    ``status`` ∈ done / error / stopped / failed。写失败静默（不阻断主流程）。
    ``write_scope`` 空列表 = 只读工人（无 Write/Edit）。
    ``pending_followups``：P2 已结束 agent 的迟到 follow-up（merge-keep，不覆盖旧值）；由
    retry 连带执行。``inbox_count`` 为派生值（不在 meta 存储，读取时合成）。
    """
    import json
    import os
    import time

    path = _meta_path(main_session_id, agent_id)
    existing: dict[str, Any] = {}
    try:
        if path.is_file():
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                existing = obj
    except Exception:  # noqa: BLE001
        existing = {}
    if has_transcript is None:
        sidechain = path.parent / f"{path.stem.removesuffix('.meta')}.jsonl"
        try:
            has_transcript = sidechain.is_file()
        except OSError:
            has_transcript = bool(existing.get("has_transcript"))
    # chat 层兜底 upsert 常不带时间戳；合并旧值，避免把 started_at 冲成 finished_at。
    keep_started = float(existing.get("started_at") or 0.0)
    keep_finished = float(existing.get("finished_at") or 0.0)
    keep_preview = str(existing.get("result_preview") or "")
    keep_task_id = str(existing.get("task_id") or "")
    keep_scope = existing.get("write_scope")
    if not isinstance(keep_scope, list):
        keep_scope = []
    scope_out = (
        [str(x) for x in write_scope if str(x).strip()]
        if write_scope is not None
        else [str(x) for x in keep_scope if str(x).strip()]
    )
    new_preview = (result_preview or "").strip()
    from engine.xml_tool_call import looks_like_raw_tool_markup

    if new_preview and looks_like_raw_tool_markup(new_preview) and keep_preview:
        new_preview = keep_preview
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "main_session_id": main_session_id,
        "task_id": (task_id or keep_task_id),
        "task_desc": (task_desc or str(existing.get("task_desc") or ""))[:200],
        "status": status or str(existing.get("status") or "done"),
        "result_preview": (new_preview or keep_preview)[:400],
        "has_transcript": bool(has_transcript),
        "write_scope": scope_out[:32],
        "read_only": len(scope_out) == 0,
        "started_at": float(started_at or keep_started or time.time()),
        "finished_at": float(
            finished_at
            or (0.0 if status == "running" else (keep_finished or time.time()))
        ),
        "pending_followups": [
            str(x)
            for x in (
                pending_followups
                if pending_followups is not None
                else list(existing.get("pending_followups") or [])
            )
            if str(x).strip()
        ][:16],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def list_subagent_metas(main_session_id: str) -> list[dict[str, Any]]:
    """读取该主会话全部子 agent 元数据，按 started_at 升序；损坏行跳过。"""
    import json

    d = _sidechain_dir(main_session_id)
    out: list[dict[str, Any]] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.meta.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:  # noqa: BLE001
            continue
    out.sort(key=lambda x: float(x.get("started_at") or 0))
    return out


def load_sidechain_messages(main_session_id: str, agent_id: str) -> list[dict[str, Any]]:
    """读取子 agent 侧链 transcript 行（已还原 blob 引用）；文件缺失返回 []。"""
    from session.record_transcript import load_transcript
    from session.transcript_blobs import resolve_transcript_rows

    anchor = _sidechain_path(main_session_id, agent_id)
    return resolve_transcript_rows(load_transcript(anchor), anchor)


def gc_sidechains(
    main_session_id: str,
    *,
    ttl_seconds: float = 7 * 24 * 3600,
    now: float | None = None,
) -> int:
    """清理超 TTL 的子 agent 侧链（.jsonl / .working.json）；返回删除条数（B6/C9）。"""
    import time

    now = now if now is not None else time.time()
    d = _sidechain_dir(main_session_id)
    if not d.is_dir():
        return 0
    removed = 0
    for f in d.iterdir():
        if not f.is_file():
            continue
        if not (
            f.suffix == ".jsonl"
            or f.name.endswith(".working.json")
            or f.name.endswith(".meta.json")
        ):
            continue
        try:
            if (now - f.stat().st_mtime) > ttl_seconds:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _sidechain_path(main_session_id: str, agent_id: str) -> Path:
    """侧链 JSONL：`~/.xeyo/sessions/{main_session}/agents/{agent_id}.jsonl`。"""
    safe_main = _safe(main_session_id)
    safe_agent = _safe(agent_id)
    return (
        Path.home() / ".xeyo" / "sessions" / safe_main / "agents"
        / f"{safe_agent}.jsonl"
    )


def _safe(raw: str) -> str:
    """稳定文件名（对齐 working._safe_name 的简化版）。"""
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (raw or "")).strip("._") or "x"


# ---- 一键分解：Multi-Agent 无显式 tasks 时，让主模型把用户消息拆成任务清单 ----

_DECOMPOSE_INSTRUCTION = (
    "你是多 Agent 任务编排器：只拆任务，不写代码、不调工具。"
    "最多 {max_tasks} 个；能独立改不同文件的必须并行（depends_on=[]）。"
    "用户明确说「两个/三个」「分别」「并行」或多个文件时，必须拆成对应数量，禁止合成单任务。"
    "先用中文写两三句「分配说明」，再另起一行输出 JSON 数组："
    '[{{"id":"t1","desc":"…","depends_on":[],"scope":["路径"],'
    '"required_tools":["Read","Edit"],"timeout_s":300}}]。'
    "不要 markdown 围栏；无必要拆则只输出一个任务。"
    "（工具白名单、环依赖、数量上限由调度器修复，无需在文案里重复。）"
)

_DECOMPOSE_PROMPT = (
    "用户请求：\n\n{text}\n\n"
    "工作区文件样例（可能不完整）：\n{files}\n\n"
    "请先写分配说明，再输出任务 JSON 数组。"
)

_SKIP_WALK_DIRS = frozenset({
    ".git", "node_modules", ".xeyo", "__pycache__", "dist", "build",
    ".venv", "venv", ".xy-shadow-git",
})


@dataclass
class DecomposeResult:
    """分解结果：给人看的分配说明 + 给调度器用的任务列表。"""
    tasks: list["Task"]
    plan_text: str = ""
    raw_text: str = ""
    used_heuristic: bool = False


def sample_workspace_files(workspace_root: str | Path, *, limit: int = 60) -> str:
    """给分解模型看的短文件清单。"""
    root = Path(workspace_root)
    if not root.is_dir():
        return "(empty)"
    paths: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_WALK_DIRS and not d.startswith(".")
        ]
        rel_dir = os.path.relpath(dirpath, root)
        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = fn if rel_dir in (".", "") else f"{rel_dir}/{fn}"
            paths.append(rel.replace("\\", "/"))
            if len(paths) >= limit:
                return "\n".join(f"- {p}" for p in paths)
    return "\n".join(f"- {p}" for p in paths) if paths else "(empty)"


def split_decompose_output(text: str) -> tuple[str, str]:
    """把模型输出拆成（分配说明, JSON 数组原文）。找不到 JSON 则 plan=全文、json=\"\"。"""
    import re

    raw = (text or "").strip()
    if not raw:
        return "", ""
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        return raw, ""
    plan = raw[: m.start()].strip()
    # 去掉常见标题前缀噪音
    for prefix in ("分配说明：", "分配说明:", "【分配说明】", "计划：", "计划:"):
        if plan.startswith(prefix):
            plan = plan[len(prefix):].strip()
    return plan, m.group(0)


def parse_tasks_json(text: str) -> list["Task"]:
    """从模型输出里提取任务 JSON 数组（容忍代码块/前后缀）。解析失败返回 []。

    纯函数，可单测。
    """
    import json
    import re

    from engine.scheduler import Task

    text = (text or "").strip()
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[Task] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        if not str(item.get("desc") or "").strip():
            continue
        out.append(
            Task.from_dict(
                {**item, "id": str(item.get("id") or f"t{i}")}
            )
        )
    return out


def format_heuristic_plan(tasks: list["Task"]) -> str:
    """启发式拆分时的可读分配说明。"""
    if not tasks:
        return ""
    lines = [
        f"主模型未拆出可用的多任务清单，已按文件/话术启发式拆成 {len(tasks)} 个子任务：",
    ]
    for t in tasks:
        scope = "、".join(t.scope) if t.scope else "（未限定文件）"
        lines.append(f"- **{t.id}**：{t.desc[:80]} · scope: {scope}")
    note = schedule_overlap_note(tasks)
    if note:
        lines.append(note)
    elif all(not t.depends_on for t in tasks):
        lines.append("无依赖且文件不重叠 → 调度将尽量并行。")
    return "\n".join(lines)


def schedule_overlap_note(
    tasks: list["Task"],
    *,
    workspace_root: str | Path | None = None,
) -> str:
    """若存在同文件 scope 重叠，返回串行提示（空串表示可并行）。"""
    if len(tasks) < 2:
        return ""
    from engine.scheduler import scope_conflicts

    overlapped: list[str] = []
    for i, a in enumerate(tasks):
        for b in tasks[i + 1 :]:
            if scope_conflicts(a, b, root=workspace_root):
                sa = "、".join(a.scope) if a.scope else "（未声明 scope）"
                sb = "、".join(b.scope) if b.scope else "（未声明 scope）"
                overlapped.append(f"{a.id}↔{b.id}（{sa} / {sb}）")
    if not overlapped:
        return ""
    return (
        "注意：以下任务文件 scope 重叠，调度器会串行执行（防同文件写冲突），"
        "不会真正并行：" + "；".join(overlapped[:4])
        + ("…" if len(overlapped) > 4 else "")
        + "。测真并行请改不同文件。"
    )


def with_schedule_note(
    plan_text: str,
    tasks: list["Task"],
    *,
    workspace_root: str | Path | None = None,
) -> str:
    """把串行/并行事实补进分配说明，纠正模型误写「并行」。"""
    note = schedule_overlap_note(tasks, workspace_root=workspace_root)
    base = (plan_text or "").strip()
    if not note:
        return base
    if "串行" in base and "并行" not in base:
        return base
    # 模型常把同文件也写成并行——用调度事实覆盖观感
    cleaned = base
    for bad in ("可以并行执行", "可以并行", "并行执行", "两个并行", "并行子任务"):
        if bad in cleaned:
            cleaned = cleaned.replace(bad, "将串行调度（同文件）")
    if note in cleaned:
        return cleaned
    if cleaned:
        return f"{cleaned}\n\n{note}"
    return note


def validate_decomposed_tasks(
    tasks: list["Task"],
    *,
    workspace_root: str | Path,
) -> list["Task"]:
    """C8：修图后返回可调度任务；修完仍空则 []（调用方回退单任务）。"""
    if not tasks:
        return []
    from engine.scheduler import MAX_DECOMPOSE_TASKS, repair_task_graph

    return repair_task_graph(tasks, max_tasks=MAX_DECOMPOSE_TASKS)


_FILE_TOKEN_RE = (
    r"(?:[\w./\\-]+\.(?:md|ts|tsx|js|jsx|py|css|json|html)|README\.md)"
)


def extract_target_files(user_text: str) -> list[str]:
    """从用户话里抽出目标文件路径（去重、保序）。"""
    import re

    text = (user_text or "").strip()
    if not text:
        return []
    out: list[str] = []
    for m in re.finditer(_FILE_TOKEN_RE, text, re.I):
        p = m.group(0).replace("\\", "/")
        # 用户说「在 docs/ 下」且文件无目录前缀 → 补 docs/
        if (
            "/" not in p
            and re.search(r"(?:^|[\s「『])docs\s*/", text, re.I)
            and not p.lower().startswith("docs/")
        ):
            p = f"docs/{p}"
        if p not in out:
            out.append(p)
    return out


def user_requests_multi_tasks(user_text: str) -> bool:
    """用户话术明显要求多子任务时，禁止回退成单任务。"""
    import re

    t = (user_text or "").strip()
    if not t:
        return False
    if len(extract_target_files(t)) >= 2:
        return True
    cues = (
        "两个子任务",
        "两个任务",
        "三个子任务",
        "三个任务",
        "分别",
        "各写",
        "各自",
        "互不",
        "并行",
        "一个加",
        "一个…",
        "另一个",
        "故意同文件",
        "同文件",
    )
    if any(c in t for c in cues):
        return True
    if t.count("一个") >= 2:
        return True
    if re.search(
        r"[两二三四五六七八九十\d]+\s*个?\s*(?:短\s*)?(?:md|文件|任务|子任务)",
        t,
        re.I,
    ):
        return True
    return False


def heuristic_split_tasks(user_text: str) -> list["Task"]:
    """分解失败时的兜底：按文件列表 / 「一个…一个…」拆成多个独立任务。"""
    import re

    from engine.scheduler import MAX_DECOMPOSE_TASKS, Task

    text = (user_text or "").strip()
    if not text:
        return []
    files = extract_target_files(text)
    if len(files) >= 2:
        tasks: list[Task] = []
        for i, path in enumerate(files[:MAX_DECOMPOSE_TASKS]):
            tasks.append(
                Task(
                    id=f"t{i + 1}",
                    desc=f"在 {path} 完成用户要求（只改该文件，勿动其它文件）",
                    depends_on=[],
                    scope=[path],
                    required_tools=["Read", "Edit", "Write"],
                )
            )
        return tasks
    # 「一个X，一个Y」
    parts = re.split(r"[，,；;。]\s*(?=一个|另一)", text)
    parts = [p.strip() for p in parts if p.strip()]
    dual = [p for p in parts if ("一个" in p or "另一" in p)]
    if len(dual) >= 2:
        scope = files[:1]
        return [
            Task(
                id="t1",
                desc=dual[0][:200],
                depends_on=[],
                scope=list(scope),
                required_tools=["Read", "Edit", "Write"],
            ),
            Task(
                id="t2",
                desc=dual[1][:200],
                depends_on=[],
                scope=list(scope),
                required_tools=["Read", "Edit", "Write"],
            ),
        ]
    if user_requests_multi_tasks(text):
        n = 2
        m = re.search(
            r"([两二三四五六七八九十\d]+)\s*个?\s*(?:短\s*)?(?:md|文件|任务|子任务)",
            text,
            re.I,
        )
        cmap = {
            "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        }
        if m:
            raw = m.group(1)
            if raw.isdigit():
                n = max(2, min(MAX_DECOMPOSE_TASKS, int(raw)))
            else:
                n = max(2, min(MAX_DECOMPOSE_TASKS, cmap.get(raw, 2)))
        return [
            Task(
                id=f"t{i}",
                desc=f"{text[:100]}（子任务 {i}/{n}）",
                depends_on=[],
                scope=[],
                required_tools=["Read", "Edit", "Write"],
            )
            for i in range(1, n + 1)
        ]
    return []


# 兼容旧名
heuristic_split_dual_tasks = heuristic_split_tasks


def _plan_prefix_before_json(text: str) -> tuple[str, bool]:
    """返回（当前可展示的分配说明前缀, 是否已碰到任务 JSON 数组起点）。

    单独一个行末 ``[`` 也算起点，避免把 ``[`` 漏进主气泡后再干等模型吐 JSON。
    """
    import re

    raw = text or ""
    m = re.search(r"\[", raw)
    if not m:
        return raw, False
    after = raw[m.start() + 1 :]
    # 起点：后面还没字 / 只有空白 / 已是 { " 或 ]
    if not (
        re.match(r"\s*$", after)
        or re.match(r"\s*[{\"]", after)
        or re.match(r"\s*\]", after)
    ):
        return raw, False
    plan = raw[: m.start()]
    stripped = plan.lstrip()
    for prefix in ("分配说明：", "分配说明:", "【分配说明】", "计划：", "计划:"):
        if stripped.startswith(prefix):
            plan = plan[: len(plan) - len(stripped)] + stripped[len(prefix) :]
            break
    return plan, True


async def decompose_tasks_stream(
    user_text: str,
    *,
    model_client: Any,
    prompt_assembler: Any = None,
    workspace_root: str | Path,
    append_system_prompt: str = "",
    date_iso: str = "",
    abort: Any = None,
    max_chars: int = 20_000,
):
    """流式分解：yield ``(\"delta\", str)``，最后 ``(\"done\", DecomposeResult)``。

    启发式只在主模型拆出 <2 个任务、且用户明显要多任务时介入——不再用
    ``want_n`` 强行覆盖「模型已给出 ≥2 个任务」的决策。
    """
    from engine.abort import AbortController
    from msgtypes.message import Message, user_message
    from session.message_store import MessageStore

    abort = abort if abort is not None else AbortController()
    if getattr(abort, "aborted", False):
        yield ("done", DecomposeResult(tasks=[], plan_text="", raw_text=""))
        return

    from engine.scheduler import MAX_DECOMPOSE_TASKS

    _ = append_system_prompt, date_iso, prompt_assembler
    files = sample_workspace_files(workspace_root)
    system = _DECOMPOSE_INSTRUCTION.format(max_tasks=MAX_DECOMPOSE_TASKS)
    store = MessageStore(
        initial=[
            Message(role="system", content=system),
            user_message(_DECOMPOSE_PROMPT.format(text=user_text, files=files)),
        ]
    )

    text = ""
    emitted = 0
    json_hit = False
    async for chunk in model_client.stream(store.as_api_messages(), [], abort):
        if getattr(chunk, "kind", "") == "text_delta":
            piece = str(getattr(chunk, "text", "") or "")
            if not piece:
                continue
            text += piece
            if not json_hit:
                plan_prefix, hit = _plan_prefix_before_json(text)
                if len(plan_prefix) > emitted:
                    yield ("delta", plan_prefix[emitted:])
                    emitted = len(plan_prefix)
                if hit:
                    json_hit = True
                    # 说明已写完，正等 JSON——避免主界面干等像卡住。
                    yield ("phase", "parsing_tasks")
        if len(text) > max_chars:
            break

    plan_text, _json_blob = split_decompose_output(text)
    parsed = parse_tasks_json(text)
    tasks = validate_decomposed_tasks(parsed, workspace_root=workspace_root)
    used_heuristic = False
    file_n = len(extract_target_files(user_text))
    want_multi = user_requests_multi_tasks(user_text) or file_n >= 2
    if want_multi and len(tasks) < 2:
        fallback = heuristic_split_tasks(user_text)
        if len(fallback) >= 2:
            tasks = (
                validate_decomposed_tasks(fallback, workspace_root=workspace_root)
                or fallback
            )
            used_heuristic = True
            note = format_heuristic_plan(tasks)
            if plan_text.strip():
                plan_text = f"{plan_text.strip()}\n\n---\n\n{note}"
            else:
                plan_text = note
            # 补发启发式说明（模型原稿已流过则只追加 note）
            if emitted > 0:
                yield ("delta", f"\n\n---\n\n{note}")
            elif note:
                yield ("delta", note)
            emitted = len(plan_text)

    if tasks and not (plan_text or "").strip():
        plan_text = "\n".join(
            f"- **{t.id}**：{(t.desc or '')[:100]}"
            + (f" · scope: {'、'.join(t.scope)}" if t.scope else "")
            for t in tasks
        )
        if len(plan_text) > emitted:
            yield ("delta", plan_text[emitted:])

    note = schedule_overlap_note(tasks, workspace_root=workspace_root)
    if note and note not in (plan_text or ""):
        yield ("delta", f"\n\n{note}")
    plan_text = with_schedule_note(
        plan_text, tasks, workspace_root=workspace_root
    )

    yield (
        "done",
        DecomposeResult(
            tasks=tasks,
            plan_text=(plan_text or "").strip(),
            raw_text=text,
            used_heuristic=used_heuristic,
        ),
    )


async def decompose_tasks(
    user_text: str,
    *,
    model_client: Any,
    prompt_assembler: Any = None,
    workspace_root: str | Path,
    append_system_prompt: str = "",
    date_iso: str = "",
    abort: Any = None,
    max_chars: int = 20_000,
) -> DecomposeResult:
    """让主模型拆任务；返回分配说明 + 任务列表（非流式封装，测用/兼容）。"""
    result = DecomposeResult(tasks=[], plan_text="", raw_text="")
    async for kind, payload in decompose_tasks_stream(
        user_text,
        model_client=model_client,
        prompt_assembler=prompt_assembler,
        workspace_root=workspace_root,
        append_system_prompt=append_system_prompt,
        date_iso=date_iso,
        abort=abort,
        max_chars=max_chars,
    ):
        if kind == "done":
            result = payload
    return result


_SYNTH_INSTRUCTION = (
    "你是主 Agent。子 Agent 已完成勘察或执行，下面是它们的结论摘录。\n"
    "请直接回答用户的原始问题，要求：\n"
    "1. 紧扣用户原话意图与约束（例如「不要修改代码」则只给实现方案/步骤，"
    "不要写成已改代码的报告，也不要要求用户立刻改代码）。\n"
    "2. 综合子结论写成连贯回答；不要输出「### 多 Agent 运行结果」标题，"
    "不要把每段子结论整段粘贴或机械罗列。\n"
    "3. 子结论没有的信息不要编造；缺口可写「尚需确认…」。\n"
    "4. 方案类问题：按目标 → 建议交互/组件落点 → 关键注意点组织，控制篇幅。"
)

_SYNTH_FINDINGS_LIMIT = 700


def format_findings_for_synthesis(task_rows: list[dict[str, Any]]) -> str:
    """把子任务结论压成合成提示用的摘录（纯函数，可单测）。"""
    blocks: list[str] = []
    for i, row in enumerate(task_rows or [], start=1):
        desc = str(row.get("desc") or row.get("id") or f"task-{i}").strip()
        status = str(row.get("status") or "")
        body = str(row.get("result") or row.get("reason") or "").strip()
        if len(body) > _SYNTH_FINDINGS_LIMIT:
            body = body[:_SYNTH_FINDINGS_LIMIT].rstrip() + "…"
        mark = "done" if status == "done" else "failed"
        blocks.append(f"### [{mark}] {desc}\n{body or '(无正文)'}")
    return "\n\n".join(blocks) if blocks else "(无子任务结论)"


async def synthesize_multi_agent_answer(
    *,
    user_text: str,
    task_rows: list[dict[str, Any]],
    model_client: Any,
    abort: Any = None,
    max_chars: int = 12_000,
):
    """流式产出主会话最终回答（token 字符串）；失败由调用方回退拼接摘要。"""
    from engine.abort import AbortController
    from msgtypes.message import Message, user_message
    from session.message_store import MessageStore

    if model_client is None:
        return

    abort = abort if abort is not None else AbortController()
    findings = format_findings_for_synthesis(task_rows)
    prompt = (
        f"用户原始问题：\n{user_text.strip()}\n\n"
        f"子 Agent 结论摘录：\n{findings}\n\n"
        "请给出给用户的最终回答："
    )
    store = MessageStore(
        initial=[
            Message(role="system", content=_SYNTH_INSTRUCTION),
            user_message(prompt),
        ]
    )
    total = 0
    async for chunk in model_client.stream(store.as_api_messages(), [], abort):
        if getattr(chunk, "kind", "") != "text_delta":
            continue
        text = str(getattr(chunk, "text", "") or "")
        if not text:
            continue
        total += len(text)
        yield text
        if total >= max_chars:
            break
