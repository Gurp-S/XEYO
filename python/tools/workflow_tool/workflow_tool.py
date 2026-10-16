"""Workflow — 模型自写编排脚本，引擎只做执行器。

与 dsh 的 ``packages/workflow/`` 同位（那边是 JS 脚本 + worker_threads；这边是
Python 脚本 + 线程），差别只在语言与运行时。共同点是把「编排」从**引擎规划**改成
**模型书写**：

- 引擎不规划路线（XEYO 铁律 2），所以这里**没有**任何"引擎替你决定怎么拆任务"
  的逻辑；脚本是模型写的，引擎只提供原语并执行。
- 每个 ``agent()`` 调用都走 ``AgentTool`` 的同一条产线路径（spawn 槽 / 侧链 /
  live-agent 注册 / 成本归因 / 写域门禁），因此**不存在第二套子代理实现**——
  这是与 ``common/concurrency_budget`` 把额度收口同一类的一致性考虑。
- 结果正文 = **脚本的返回值**（JSON 事实）。``phase`` / ``log`` 只进 metadata，
  不进模型可见正文——避免脚本自述变成"导演文本"（铁律 1）。

安全边界：见 ``script_guard`` 的模块声明——AST 白名单是表达能力约束，不是安全
边界；本工具默认关（``XEYO_WORKFLOW``），沙箱落地前不作为默认能力。
"""

from __future__ import annotations

import asyncio
import builtins
import json
import logging
import os
import uuid
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from common.concurrency_budget import agent_spawn_limit
from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.workflow_tool.prompt import DESCRIPTION, WORKFLOW_TOOL_NAME
from tools.workflow_tool.script_guard import (
    ORCHESTRATION_NAMES,
    SAFE_BUILTIN_NAMES,
    SAFE_HELPER_NAMES,
    PreparedScript,
    ScriptFacts,
    ScriptRejected,
    prepare_script,
)

_log = logging.getLogger(__name__)

DEFAULT_MAX_AGENTS = 12
MAX_MAX_AGENTS = 64
#: 单次 agent() 的等待上限（秒）；超时按子代理失败处理（返回 None）。
DEFAULT_AGENT_TIMEOUT_S = 900.0
#: 脚本总执行上限（秒）。0 = 不限（由外层工具 deadline 兜底）。
DEFAULT_SCRIPT_TIMEOUT_S = 3600.0

#: 传给 agent() 的合法可选参数（未知键一律报错，不静默忽略——照 dsh 的
#: 「a typo'd option must kill the script loudly」）。
_AGENT_OPTION_KEYS = frozenset(
    {"label", "schema", "scope", "tools", "agent_type", "reuse_agent_id"}
)


class WorkflowFatal(RuntimeError):
    """脚本用法错误 / 触顶：整段脚本失败（不是单个子代理失败）。"""


class WorkflowAborted(RuntimeError):
    """外部 abort 触发的脚本终止。"""


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _extract_json(text: str) -> Any:
    """从子代理文本里取 JSON 对象；失败抛 ValueError（由调用方转成 None）。"""
    body = (text or "").strip()
    if body.startswith("```"):
        first_newline = body.find("\n")
        if first_newline != -1:
            body = body[first_newline + 1 :]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    body = body.strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    start = body.find("{")
    end = body.rfind("}")
    if start != -1 and end > start:
        return json.loads(body[start : end + 1])
    raise ValueError("no JSON object in sub-agent output")


def _validate_meta(raw: Any) -> dict[str, Any]:
    """meta 必须是**纯 JSON 数据**且含 name/description（对齐 dsh 的同名契约）。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkflowFatal("meta must be a JSON object")
    try:
        json.dumps(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowFatal(f"meta must be plain JSON data: {exc}") from exc
    name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()
    if not name:
        raise WorkflowFatal("meta.name is required")
    if not description:
        raise WorkflowFatal("meta.description is required")
    phases = raw.get("phases")
    if phases is not None and not isinstance(phases, list):
        raise WorkflowFatal("meta.phases must be a list")
    return dict(raw)


class _ScriptRuntime:
    """一次 workflow run 的执行环境：编排原语 + 计数 + 结果收集。"""

    def __init__(
        self,
        *,
        agent_tool: Any,
        abort: AbortController,
        loop: asyncio.AbstractEventLoop,
        run_short: str,
        max_agents: int,
        agent_timeout_s: float,
        meta: dict[str, Any],
        args: Any,
    ) -> None:
        self._agent_tool = agent_tool
        self._abort = abort
        self._loop = loop
        self._run_short = run_short
        self._max_agents = max(1, int(max_agents))
        self._agent_timeout_s = float(agent_timeout_s)
        self._meta = meta
        self._args = args
        self.agents_started = 0
        self._agent_lock = threading.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.phases: list[str] = []
        self.logs: list[str] = []

    # -- 事实收集 -----------------------------------------------------------

    def _phase(self, title: Any) -> None:
        self.phases.append(str(title or "")[:200])

    def _log(self, message: Any) -> None:
        # print 也绑到这里：脚本的 stdout 不进引擎 stdout，只进 metadata。
        self.logs.append(str(message or "")[:500])

    # -- 编排原语 -----------------------------------------------------------

    def _agent(self, prompt: Any, **options: Any) -> Any:
        self._check_abort()
        unknown = sorted(set(options) - _AGENT_OPTION_KEYS)
        if unknown:
            raise WorkflowFatal(f"agent() unknown option(s): {', '.join(unknown)}")
        with self._agent_lock:
            if self.agents_started >= self._max_agents:
                raise WorkflowFatal(f"workflow agent budget exhausted ({self._max_agents})")
            self.agents_started += 1
            index = self.agents_started
        task_id = f"wf-{self._run_short}-{index}"
        desc = str(prompt or "")
        schema = options.get("schema")
        if schema is not None:
            try:
                schema_text = json.dumps(schema, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                raise WorkflowFatal(f"agent() schema must be JSON data: {exc}") from exc
            desc = (
                f"{desc}\n\nReturn ONLY a JSON object matching this schema "
                f"(no prose, no code fence): {schema_text}"
            )
        tool_input: dict[str, Any] = {"task_id": task_id, "desc": desc, "background": False}
        scope = options.get("scope")
        if scope:
            if not isinstance(scope, (list, tuple)):
                raise WorkflowFatal("agent() scope must be a list of paths")
            tool_input["scope"] = [str(p) for p in scope]
        tools = options.get("tools")
        if tools:
            if not isinstance(tools, (list, tuple)):
                raise WorkflowFatal("agent() tools must be a list of names")
            tool_input["required_tools"] = [str(t) for t in tools]
        for key in ("agent_type", "reuse_agent_id"):
            value = options.get(key)
            if value:
                tool_input[key] = str(value)

        async def owned_agent():
            task = asyncio.current_task()
            self._tasks.add(task)
            try:
                return await self._agent_tool.execute(tool_input, self._abort)
            finally:
                self._tasks.discard(task)
        future = asyncio.run_coroutine_threadsafe(owned_agent(), self._loop)
        try:
            import time
            deadline = time.monotonic() + self._agent_timeout_s
            while True:
                if self._abort.aborted:
                    future.cancel()
                    raise WorkflowAborted("workflow aborted")
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError
                try:
                    result = future.result(timeout=min(.1, left))
                    break
                except TimeoutError:
                    continue
        except TimeoutError:
            future.cancel()
            self._log(f"agent {task_id} timed out after {self._agent_timeout_s:g}s")
            return None
        except Exception as exc:  # noqa: BLE001 — 子代理异常不炸整段脚本
            self._log(f"agent {task_id} raised {type(exc).__name__}: {exc}")
            return None
        is_error, body = _parse_agent_result(str(getattr(result, "content", "") or ""))
        if is_error or getattr(result, "is_error", False):
            self._log(f"agent {task_id} failed: {body[:200]}")
            return None
        if schema is None:
            return body
        try:
            return _extract_json(body)
        except ValueError as exc:
            self._log(f"agent {task_id} output is not schema-valid JSON: {exc}")
            return None

    def _parallel(self, thunks: Any) -> list[Any]:
        self._check_abort()
        if not isinstance(thunks, (list, tuple)):
            raise WorkflowFatal("parallel() expects a list of zero-argument callables")
        items = list(thunks)
        if not items:
            return []
        for item in items:
            if not callable(item):
                raise WorkflowFatal("parallel() items must be callables")
        workers = max(1, min(len(items), agent_spawn_limit()))
        results: list[Any] = [None] * len(items)

        def _run(index: int, thunk: Any) -> None:
            try:
                results[index] = thunk()
            except (WorkflowAborted, WorkflowFatal):
                raise
            except Exception as exc:  # noqa: BLE001 — 单项失败不影响兄弟项
                self._log(f"parallel item {index} raised {type(exc).__name__}: {exc}")
                results[index] = None

        with ThreadPoolExecutor(max_workers=workers) as pool:
            from tools.workflow_tool.lifetime import checked_call
            futures = [pool.submit(contextvars.copy_context().run, checked_call, _run, self, i, t)
                       for i, t in enumerate(items)]
            for future in futures:
                future.result()  # WorkflowFatal / WorkflowAborted 原样上抛
        return results

    def _pipeline(self, items: Any, *stages: Any) -> list[Any]:
        self._check_abort()
        if not isinstance(items, (list, tuple)):
            raise WorkflowFatal("pipeline() expects a list of items")
        for stage in stages:
            if not callable(stage):
                raise WorkflowFatal("pipeline() stages must be callables")
        originals = list(items)
        current: list[Any] = list(originals)
        for stage in stages:
            nxt: list[Any] = []
            for index, item in enumerate(originals):
                prev = None if not stages else current[index]
                try:
                    nxt.append(stage(prev, item))
                except (WorkflowAborted, WorkflowFatal):
                    raise
                except Exception as exc:  # noqa: BLE001
                    self._log(
                        f"pipeline stage raised {type(exc).__name__}: {exc}"
                    )
                    nxt.append(None)
            current = nxt
        return current

    def _check_abort(self) -> None:
        if getattr(self._abort, "aborted", False):
            raise WorkflowAborted("workflow aborted")

    # -- 命名空间 -----------------------------------------------------------

    def build_globals(self) -> dict[str, Any]:
        """脚本可见命名空间：只有编排原语 + 白名单内置 + args/meta。"""
        safe_builtins: dict[str, Any] = {}
        for name in SAFE_BUILTIN_NAMES:
            if name == "print":
                safe_builtins[name] = self._log
                continue
            resolved = getattr(builtins, name, None)
            if resolved is not None:
                safe_builtins[name] = resolved
        for name in SAFE_HELPER_NAMES:
            safe_builtins[name] = _to_json if name == "to_json" else _from_json
        namespace: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "agent": self._agent,
            "parallel": self._parallel,
            "pipeline": self._pipeline,
            "phase": self._phase,
            "log": self._log,
            "args": self._args,
            "meta": self._meta,
        }
        return namespace


def _to_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return json.dumps(repr(value))


def _from_json(text: Any) -> Any:
    try:
        return json.loads(str(text))
    except (TypeError, ValueError):
        return None


def _parse_agent_result(content: str) -> tuple[bool, str]:
    """取回 Agent tool_result 的正文（逆 ``_format_agent_tool_result``）。

    与 formatter 同源实现（``tools/agent_tool/agent_tool.py``），避免两处格式漂移。
    """
    from tools.agent_tool.agent_tool import parse_agent_tool_result

    return parse_agent_tool_result(content)


class WorkflowTool:
    name = WORKFLOW_TOOL_NAME

    def __init__(
        self,
        *,
        cwd: str = ".",
        session_id: str = "",
        write_store: Any | None = None,
    ) -> None:
        self._cwd = os.path.abspath(cwd or ".")
        self._session_id = str(session_id or "")
        self._write_store = write_store
        self._runtime_provider: Any | None = None
        self._agent_id: str | None = None

    # -- 契约 ---------------------------------------------------------------

    @staticmethod
    def is_read_only() -> bool:
        return False

    @staticmethod
    def is_concurrency_safe() -> bool:
        # 同轮两个 Workflow 会各自持子代理槽，彼此争抢没有收益；串行更可预测。
        return False

    def set_write_store(self, store: Any) -> None:
        self._write_store = store

    def set_runtime_provider(self, provider: Any) -> None:
        self._runtime_provider = provider

    def set_session_id(self, session_id: str) -> None:
        self._session_id = str(session_id or "")

    def set_agent_id(self, agent_id: str | None) -> None:
        self._agent_id = agent_id

    def _runtime(self) -> Any:
        provider = self._runtime_provider
        return provider() if callable(provider) else None

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": DESCRIPTION,
            "input_schema": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": (
                            "Orchestration script body. Top-level statements; "
                            "its return value is the tool result."
                        ),
                    },
                    "meta": {
                        "type": "object",
                        "description": (
                            "Plain JSON identity block; requires name and description."
                        ),
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "when_to_use": {"type": "string"},
                            "phases": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"title": {"type": "string"}},
                                },
                            },
                        },
                        "required": ["name", "description"],
                    },
                    "args": {
                        "description": "Optional JSON value exposed to the script as args.",
                    },
                    "max_agents": {
                        "type": "integer",
                        "description": (
                            f"Total agent() calls allowed for this run "
                            f"(1–{MAX_MAX_AGENTS}; default {DEFAULT_MAX_AGENTS})."
                        ),
                    },
                },
                "required": ["script", "meta"],
            },
        }

    # -- 执行 ---------------------------------------------------------------

    async def execute(
        self, input: dict[str, Any], abort: AbortController
    ) -> ToolResult:
        abort.raise_if_aborted()
        raw = input if isinstance(input, dict) else {}
        try:
            meta = _validate_meta(raw.get("meta"))
        except WorkflowFatal as exc:
            return ToolResult(content=f"invalid meta: {exc}", is_error=True)
        script = raw.get("script")
        if not isinstance(script, str) or not script.strip():
            return ToolResult(content="script is required", is_error=True)
        try:
            prepared: PreparedScript = prepare_script(script)
        except ScriptRejected as exc:
            return ToolResult(content=f"script rejected: {exc}", is_error=True)
        facts: ScriptFacts = prepared.facts

        agent_tool = self._build_agent_tool()
        if agent_tool is None:
            return ToolResult(
                content="subagent runtime not configured (set_runtime_provider)",
                is_error=True,
            )

        max_agents = self._max_agents(raw.get("max_agents"))
        from engine.abort import LinkedAbortController
        runtime = _ScriptRuntime(
            agent_tool=agent_tool,
            abort=LinkedAbortController(abort),
            loop=asyncio.get_running_loop(),
            run_short=uuid.uuid4().hex[:8],
            max_agents=max_agents,
            agent_timeout_s=_env_float(
                "XEYO_WORKFLOW_AGENT_TIMEOUT_S", DEFAULT_AGENT_TIMEOUT_S
            ),
            meta=meta,
            args=raw.get("args"),
        )
        timeout = _env_float("XEYO_WORKFLOW_SCRIPT_TIMEOUT_S", DEFAULT_SCRIPT_TIMEOUT_S)

        try:
            from tools.workflow_tool.lifetime import run_owned
            value = await run_owned(self._run_script, prepared, runtime, timeout)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return self._failure(runtime, f"script exceeded {timeout:g}s", facts)
        except WorkflowAborted:
            return self._failure(runtime, "workflow aborted", facts)
        except WorkflowFatal as exc:
            return self._failure(runtime, str(exc), facts)
        except BaseException as exc:  # noqa: BLE001 — 脚本异常不逃出工具
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            _log.debug("workflow script failed", exc_info=True)
            return self._failure(runtime, f"{type(exc).__name__}: {exc}", facts)

        payload = {
            "ok": True,
            "value": _jsonable(value),
            "agents_started": runtime.agents_started,
            "phases": runtime.phases,
            "logs": runtime.logs,
        }
        return ToolResult(
            content=json.dumps(payload, ensure_ascii=False, default=repr),
            metadata={
                "workflow_ok": True,
                "agents_started": runtime.agents_started,
                "phases": list(runtime.phases),
                "logs": list(runtime.logs),
                "script_facts": {
                    "chars": facts.chars,
                    "nodes": facts.nodes,
                    "calls": facts.calls,
                    "agent_calls": facts.agent_calls,
                },
            },
        )

    # -- 内部 ---------------------------------------------------------------

    def _build_agent_tool(self) -> Any | None:
        """复用 AgentTool 的产线路径（spawn 槽 / 侧链 / live / 成本 / 写域）。"""
        if self._runtime() is None:
            return None
        from tools.agent_tool import AgentTool

        tool = AgentTool(
            cwd=self._cwd,
            session_id=self._session_id,
            write_store=self._write_store,
        )
        tool.set_runtime_provider(self._runtime_provider)
        return tool

    @staticmethod
    def _run_script(prepared: PreparedScript, runtime: _ScriptRuntime) -> Any:
        """在工作线程里 exec 脚本并调用生成的入口函数，取其返回值。"""
        namespace = runtime.build_globals()
        exec(prepared.code, namespace)  # noqa: S102 — 受 script_guard 白名单约束
        entry = namespace.get(prepared.entry)
        if not callable(entry):
            raise WorkflowFatal("script entry did not compile")
        return entry()

    @staticmethod
    def _max_agents(raw: Any) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_MAX_AGENTS
        if value < 1:
            return 1
        return min(value, MAX_MAX_AGENTS)

    @staticmethod
    def _failure(
        runtime: _ScriptRuntime, detail: str, facts: ScriptFacts
    ) -> ToolResult:
        payload = {
            "ok": False,
            "error": detail,
            "agents_started": runtime.agents_started,
            "phases": runtime.phases,
            "logs": runtime.logs,
        }
        return ToolResult(
            content=json.dumps(payload, ensure_ascii=False, default=repr),
            is_error=True,
            metadata={
                "workflow_ok": False,
                "agents_started": runtime.agents_started,
                "phases": list(runtime.phases),
                "logs": list(runtime.logs),
                "script_facts": {"chars": facts.chars, "nodes": facts.nodes},
            },
        )


def _jsonable(value: Any) -> Any:
    """把脚本返回值收敛成 JSON 事实；不可序列化的类型退化为 repr。"""
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError):
        if isinstance(value, (list, tuple)):
            return [_jsonable(v) for v in value]
        if isinstance(value, dict):
            return {str(k): _jsonable(v) for k, v in value.items()}
        return repr(value)


__all__ = [
    "DEFAULT_MAX_AGENTS",
    "MAX_MAX_AGENTS",
    "WorkflowAborted",
    "WorkflowFatal",
    "WorkflowTool",
    "ORCHESTRATION_NAMES",
]
