"""AgentTool — spawn 一个受限的子 Agent（短命工人），作为主循环普通工具。

子 Agent 结论以
``tool_result`` 回到主对话，主模型带着热缓存继续写最终回答。

- **短上下文隔离**：独立 query_loop + 裁剪工具；不载入主会话全文。
- **递归控制（A8）**：``max_depth = 1``；子 agent 工具表剔除 Agent/Bash。
- **侧链**：历史写 ``{session}/agents/{agent_id}.jsonl``，不 append 主 JSONL。
- **并发**：``is_concurrency_safe=True``；同轮多 Agent 并行，写冲突靠 WriteStore。
- **UI**：经 progress_sink 发 multi_agent_task/delta/progress，复用现有 FE 卡片。
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from engine.abort import AbortController
from memory.agent_scope import (
    enqueue_subagent_candidates,
    format_subagent_summary,
    handoff_from_run_result,
)
from msgtypes.events import ToolProgressEvent
from tools.agent_tool.prompt import DESCRIPTION, TOOL_NAME
from tools.base_tool import ToolResult
from tools.progress_sink import emit_progress

MAX_DEPTH = 1  # P0 硬限制（A8）：只允许一层子 agent，禁止孙 agent
# 同会话并发 spawn 上限（硬门禁；可用环境变量覆盖）
_MAX_CONCURRENT = max(1, int(os.environ.get("XEYO_MAX_CONCURRENT_AGENTS", "8") or "8"))
_agent_slots = threading.Semaphore(_MAX_CONCURRENT)


def _format_agent_tool_result(
	*,
	agent_id: str,
	task_id: str,
	desc: str,
	body: str,
	is_error: bool,
) -> str:
	"""主循环看到的 Agent tool_result 正文（续写原问题，勿拐到 Memory）。"""
	status = "ERROR" if is_error else "OK"
	return (
		f"[Agent tool_result status={status} subagent={agent_id} task_id={task_id}]\n"
		f"Assigned task: {desc}\n"
		f"---\n"
		f"{body}\n"
		f"---\n"
		"Parent request context remains in the calling turn. Memory indexes and "
		"memory tools are not included in this result."
	)


@dataclass
class AgentInput:
    task_id: str
    desc: str
    scope: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    context_hint: dict[str, Any] = field(default_factory=dict)
    parent_depth: int = 0
    # 重试：复用已有 agent_id（清侧链后重跑），不生成新 id
    reuse_agent_id: str = ""
    # T14：角色名（agents/*.toml 的 name）；注入 developer_instructions + 卡片名
    agent_type: str = ""


def _safe_agent_id(task_id: str, *, tail: str) -> str:
    """侧链文件名用的稳定 id：agent-{task_id}-{tail}。"""
    tid = "".join(
        ch if ch.isalnum() or ch in "._-" else "_"
        for ch in (task_id or "task")
    ).strip("._") or "task"
    return f"agent-{tid}-{tail}"


class AgentTool:
    name = TOOL_NAME

    def __init__(
        self,
        *,
        cwd: str = ".",
        session_id: str = "",
        write_store: Any | None = None,
        journal: Any | None = None,
    ) -> None:
        self._cwd = os.path.abspath(cwd or ".")
        self._session_id = session_id
        self._write_store = write_store
        self._journal = journal
        self._runtime_provider: Any | None = None

    @staticmethod
    def is_read_only() -> bool:
        return False

    @staticmethod
    def is_concurrency_safe() -> bool:
        # 同轮可并行多个 Agent；磁盘冲突由 WriteStore content-hash 收敛。
        return True

    def set_runtime_provider(self, provider: Any) -> None:
        self._runtime_provider = provider

    def set_write_store(self, store: Any) -> None:
        self._write_store = store

    def set_session_id(self, session_id: str) -> None:
        self._session_id = str(session_id or "")

    def _get_runtime(self) -> Any:
        provider = self._runtime_provider
        return provider() if callable(provider) else None

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": DESCRIPTION.strip(),
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Stable id for this sub-task (also names the sidechain).",
                    },
                    "desc": {
                        "type": "string",
                        "description": "Clear task for the sub-agent (what to do and constraints).",
                    },
					"scope": {
						"type": "array",
						"items": {"type": "string"},
						"description": (
							"Write paths this agent may touch "
							"(empty = read-only; Write/Edit removed)."
						),
					},
                    "required_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Extra tools beyond baseline (e.g. Read, Edit, Grep, Glob).",
                    },
                    "parent_depth": {
                        "type": "integer",
                        "description": "Caller depth; leave 0 from the main agent.",
                    },
                    "reuse_agent_id": {
                        "type": "string",
                        "description": (
                            "Reuse an existing sidechain agent_id (clear then rerun); "
                            "omit to spawn a new id."
                        ),
                    },
                    "agent_type": {
                        "type": "string",
                        "description": (
                            "Optional persona name from agents/*.toml "
                            "(name field). Appends the role's developer_"
                            "instructions to the subagent system prompt and "
                            "auto-labels the spawn card."
                        ),
                    },
                },
                "required": ["task_id", "desc"],
            },
        }

    def parse_input(self, raw: dict[str, Any]) -> AgentInput:
        return AgentInput(
            task_id=str(raw.get("task_id") or ""),
            desc=str(raw.get("desc") or ""),
            scope=[str(x) for x in raw.get("scope") or [] if isinstance(x, str)],
            required_tools=[
                str(x) for x in raw.get("required_tools") or [] if isinstance(x, str)
            ],
            parent_depth=max(0, int(raw.get("parent_depth") or 0)),
            reuse_agent_id=str(raw.get("reuse_agent_id") or "").strip(),
            agent_type=str(raw.get("agent_type") or "").strip(),
        )

    def _emit_xy(self, payload: dict[str, Any], *, tool_use_id: str = "") -> None:
        emit_progress(
            ToolProgressEvent(
                name=self.name,
                tool_use_id=tool_use_id,
                message=str(payload.get("type") or ""),
                xy=payload,
            )
        )

    async def execute(
        self, input: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        agent_input = self.parse_input(input)

        depth = agent_input.parent_depth + 1
        if depth > MAX_DEPTH:
            return ToolResult(
                content=f"max agent depth reached ({MAX_DEPTH})", is_error=True
            )

        # T14：角色解析（agents/*.toml）——先于并发槽获取，失败不占槽。
        # 未知 agent_type 直接报错，不静默降级。
        agent_type = (agent_input.agent_type or "").strip()
        role = None
        role_suffix = ""
        if agent_type:
            from engine.agent_roles import load_agent_roles, role_developer_suffix

            role = load_agent_roles(self._cwd or ".").get(agent_type)
            if role is None:
                return ToolResult(
                    content=(
                        f"unknown agent_type: {agent_type} "
                        f"(no agents/*.toml role with this name)"
                    ),
                    is_error=True,
                )
            role_suffix = role_developer_suffix(role)

        if not _agent_slots.acquire(blocking=False):
            return ToolResult(
                content=(
                    f"max concurrent agents reached ({_MAX_CONCURRENT}); "
                    "wait for running sub-agents to finish"
                ),
                is_error=True,
            )

        from engine.abort import LinkedAbortController
        from engine.live_agents import register_live_agent, unregister_live_agent
        from usage.multi_agent_metrics import (
            record_agent_tool_end,
            record_agent_tool_start,
        )
        import time as _time

        task_id = (agent_input.task_id or "task").strip() or "task"
        reuse = (agent_input.reuse_agent_id or "").strip()
        if reuse:
            agent_id = reuse
            tail = agent_id.rsplit("-", 1)[-1] if "-" in agent_id else "retry"
            try:
                from engine.subagent_runner import clear_sidechain

                clear_sidechain(self._session_id, agent_id)
            except Exception:  # noqa: BLE001
                pass
        else:
            tail = uuid.uuid4().hex[:6]
            agent_id = _safe_agent_id(task_id, tail=tail)
        uid = f"{task_id}:{tail}"
        # spawn 描述自动生成：desc 缺省时回退角色描述 / task_id；卡片名带角色。
        desc = (agent_input.desc or "").strip()
        if not desc and role is not None:
            desc = role.description or role.display
        desc = (desc or task_id)[:120]
        from permissions.write_scope import normalize_worker_scope

        cwd = self._cwd or "."
        scope_paths, read_only, scope_reason = normalize_worker_scope(
            agent_input.scope, cwd=cwd
        )
        # 同步回 input，供 whitelist / run_subagent 使用
        agent_input.scope = list(scope_paths)
        tool_whitelist = self._tools_for(agent_input)
        local_abort = LinkedAbortController(abort)
        register_live_agent(self._session_id, agent_id, local_abort)
        started = _time.monotonic()
        record_agent_tool_start(
            session_id=self._session_id,
            agent_id=agent_id,
            task_id=task_id,
            desc=desc,
            read_only=read_only,
        )

        self._emit_xy({
            "type": "multi_agent_task",
            "task_id": task_id,
            "uid": uid,
            "agent_id": agent_id,
            "desc": desc,
            "status": "running",
            "scope": scope_paths,
            "read_only": read_only,
            "agent_type": agent_type,
            **({"role_display": role.display} if role is not None else {}),
            **({"scope_reason": scope_reason} if scope_reason else {}),
        })

        def _on_delta(text: str) -> None:
            if not text:
                return
            self._emit_xy({
                "type": "multi_agent_delta",
                "task_id": task_id,
                "uid": uid,
                "agent_id": agent_id,
                "text": text,
            })

        end_status = "failed"
        turns_used = 0
        max_turns_used = 0
        try:
            try:
                out = await self._run_subagent(
                    agent_input,
                    agent_id=agent_id,
                    depth=depth,
                    tool_whitelist=tool_whitelist,
                    abort=local_abort,
                    on_text_delta=_on_delta,
                    role_suffix=role_suffix,
                )
            except Exception as e:  # noqa: BLE001
                if local_abort.aborted and not abort.aborted:
                    reason = "cancelled by user"
                else:
                    reason = str(e)[:160]
                self._emit_xy({
                    "type": "multi_agent_progress",
                    "task_id": task_id,
                    "uid": uid,
                    "agent_id": agent_id,
                    "status": "failed",
                    "reason": reason,
                    "result": "",
                })
                end_status = "cancelled" if local_abort.aborted and not abort.aborted else "failed"
                return ToolResult(
                    content=_format_agent_tool_result(
                        agent_id=agent_id,
                        task_id=task_id,
                        desc=desc or task_id,
                        body=f"subagent failed: {reason}",
                        is_error=True,
                    ),
                    is_error=True,
                )

            turns_used = int(getattr(out, "turns_used", 0) or 0)
            max_turns_used = int(getattr(out, "max_turns", 0) or 0)
            handoff = handoff_from_run_result(
                agent_id=agent_id,
                conclusion=out.conclusion,
                files_touched=out.files_touched,
                memories=out.memories,
                is_error=out.is_error,
            )
            try:
                enqueue_subagent_candidates(
                    self._cwd,
                    [handoff],
                    main_session_id=self._session_id,
                )
            except Exception:  # noqa: BLE001
                pass

            if local_abort.aborted and not abort.aborted:
                status = "failed"
                end_status = "cancelled"
                preview = "cancelled by user"
            else:
                status = "failed" if out.is_error else "done"
                end_status = status
                preview = format_subagent_summary(handoff)
            progress_reason = ""
            if status != "done":
                progress_reason = (preview or "")[:160]
                if getattr(out, "had_write_stale", False) and "conflict" not in progress_reason.lower():
                    progress_reason = (f"write conflict; {progress_reason}").strip("; ")[:160]
            self._emit_xy({
                "type": "multi_agent_progress",
                "task_id": task_id,
                "uid": uid,
                "agent_id": agent_id,
                "status": status,
                "reason": progress_reason,
                "result": preview[:800],
                # 累计 token / 成本（GUI 子代理卡片角标）。
                "tokens_used": int(getattr(out, "tokens_used", 0) or 0),
                "cost_cny": round(float(getattr(out, "cost_cny", 0.0) or 0.0), 4),
            })

            body = (preview or "").strip() or "(empty subagent result)"
            content = _format_agent_tool_result(
                agent_id=agent_id,
                task_id=task_id,
                desc=desc or task_id,
                body=body,
                is_error=status != "done",
            )
            return ToolResult(
                content=content,
                metadata={
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "uid": uid,
                    "files_touched": list(out.files_touched or []),
                },
                is_error=status != "done",
            )
        finally:
            # T14：异常正在逃逸 = 子代理结果没能作为 tool_result 带回主会话
            # （父回合 abort / 中途崩溃）——记结算，下轮 T_now 注入归因通知。
            try:
                import sys as _sys

                if _sys.exc_info()[0] is not None:
                    from engine.agent_settlement import record_agent_settlement

                    record_agent_settlement(
                        self._session_id,
                        agent_id=agent_id,
                        task_id=task_id,
                        status="interrupted",
                        summary="子代理结果未带回主会话（回合被中断或异常）",
                    )
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "record_agent_settlement failed", exc_info=True
                )
            unregister_live_agent(self._session_id, agent_id)
            try:
                record_agent_tool_end(
                    session_id=self._session_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    status=end_status,
                    duration_ms=int((_time.monotonic() - started) * 1000),
                    read_only=read_only,
                    turns_used=turns_used,
                    max_turns=max_turns_used,
                )
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "record_agent_tool_end failed", exc_info=True
                )
            _agent_slots.release()
    def _tools_for(self, agent_input: AgentInput) -> list[str]:
        from engine.scheduler import Task, build_tool_whitelist

        task = Task(
            id=agent_input.task_id,
            desc=agent_input.desc,
            scope=agent_input.scope,
            required_tools=agent_input.required_tools,
        )
        return build_tool_whitelist(task)

    async def _run_subagent(
        self,
        agent_input: AgentInput,
        *,
        agent_id: str,
        depth: int,
        tool_whitelist: list[str],
        abort: AbortController,
        on_text_delta: Any = None,
        role_suffix: str = "",
    ) -> "SubagentOutput":
        _ = depth
        runtime = self._get_runtime()
        if runtime is None:
            return SubagentOutput(
                conclusion="ERROR: subagent runtime not configured (set_runtime_provider)",
                is_error=True,
            )

        from engine.subagent_runner import run_subagent

        append_prompt = getattr(runtime, "append_system_prompt", "") or ""
        if role_suffix:
            append_prompt = (
                f"{append_prompt}\n\n{role_suffix}" if append_prompt else role_suffix
            )
        rr = await run_subagent(
            workspace_root=runtime.workspace_root,
            agent_id=agent_id,
            task_prompt=agent_input.desc,
            tool_whitelist=tool_whitelist,
            model_client=runtime.model_client,
            prompt_assembler=runtime.prompt_assembler,
            write_store=self._write_store,
            main_session_id=self._session_id,
            coordinator=None,
            abort=abort,
            append_system_prompt=append_prompt,
            date_iso=runtime.date_iso,
            on_text_delta=on_text_delta,
            session_id=self._session_id,
            task_id=agent_input.task_id,
            write_scope_paths=list(agent_input.scope or []),
            read_state=getattr(runtime, "read_state", None),
            allow_followups=True,
        )
        return SubagentOutput(
            conclusion=rr.conclusion,
            files_touched=rr.files_touched,
            memories=rr.memories,
            is_error=rr.is_error,
            turns_used=int(getattr(rr, "turns_used", 0) or 0),
            max_turns=int(getattr(rr, "max_turns", 0) or 0),
            had_write_stale=bool(getattr(rr, "had_write_stale", False)),
        )


@dataclass
class SubagentOutput:
    """子 agent 回传的（供主会话追加一条 tool_result）。"""

    conclusion: str
    files_touched: list[str] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    turns_used: int = 0
    max_turns: int = 0
    had_write_stale: bool = False

