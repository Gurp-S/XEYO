"""并发额度单一来源：单轮工具批 / 子 agent DAG / spawn 槽。

三档上限原先各自散在三处、彼此不引用（``tools/orchestration.py``、
``engine/scheduler.py``、``tools/agent_tool/agent_tool.py``）⇒ 改一处推断不出
整体，也没有任何单点能回答"此刻还能起几个子 agent"。本模块把**来源**收口到
一处：各层保留自己的档位与语义，数值与解析规则只在这里定义。

统一的是来源，不是数值 —— 三档语义不同（工具批 / 单会话任务 DAG / 每会话
spawn 槽），合成一个数会改变行为：

- :func:`tool_batch_limit`：单轮工具批并发。env ``XEYO_MAX_TOOL_USE_CONCURRENCY``，默认 10。
- :func:`subagent_dag_limit`：单会话子 agent 任务 DAG 并发。默认 10（历史上无 env 入口，不新增）。
- :func:`agent_spawn_limit`：**每会话** spawn 槽上限。env ``XEYO_MAX_CONCURRENT_AGENTS``，默认 8。

非法 / 空 env 一律回退默认（历史行为是 ``int(env)`` 无保护，非法值会让工具模块
**导入即抛** ValueError，等于整块工具面起不来）。

spawn 槽的两条不变量（调用方拿不到裸计数器，只能经由本模块）：

1. **按会话分桶**：键 = session_id（空 id 归一个桶 = headless 单会话）。历史实现
   是模块级全局信号量，A 会话占满会让 B 会话拿到 "max concurrent agents reached"，
   而注释自称的是"同会话"上限。
2. **归还幂等**：:meth:`AgentSlotLease.release` 重复调用只生效一次。历史缺陷是
   拿到槽后的裸段一旦抛异常就永久烧掉一个槽（桌面 app 跑几天后多 agent 静默失效）。
"""

from __future__ import annotations

import os
import threading

DEFAULT_TOOL_BATCH_LIMIT = 10
DEFAULT_SUBAGENT_DAG_LIMIT = 10
DEFAULT_AGENT_SPAWN_LIMIT = 8

ENV_TOOL_BATCH_LIMIT = "XEYO_MAX_TOOL_USE_CONCURRENCY"
ENV_AGENT_SPAWN_LIMIT = "XEYO_MAX_CONCURRENT_AGENTS"


def _env_limit(name: str, default: int) -> int:
    """env → 正整数上限；空 / 非数字 / < 1 一律回退 default，绝不抛。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


def tool_batch_limit() -> int:
    """单轮工具批并发上限（来源：唯一）。"""
    return _env_limit(ENV_TOOL_BATCH_LIMIT, DEFAULT_TOOL_BATCH_LIMIT)


def subagent_dag_limit() -> int:
    """单会话子 agent 任务 DAG 并发上限（来源：唯一）。"""
    return DEFAULT_SUBAGENT_DAG_LIMIT


def agent_spawn_limit() -> int:
    """每会话 spawn 槽上限（来源：唯一）。"""
    return _env_limit(ENV_AGENT_SPAWN_LIMIT, DEFAULT_AGENT_SPAWN_LIMIT)


class SpawnSlots:
    """一个会话的 spawn 槽：计数 + 锁。limit 在桶创建时定，之后不随 env 变。"""

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._used = 0
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def available(self) -> int:
        with self._lock:
            return self._limit - self._used

    def try_acquire(self) -> "AgentSlotLease | None":
        """非阻塞：满则 None（调用方据此回中性事实，不排队、不阻塞）。"""
        with self._lock:
            if self._used >= self._limit:
                return None
            self._used += 1
        return AgentSlotLease(self)

    def _release(self) -> None:
        with self._lock:
            if self._used > 0:
                self._used -= 1


class AgentSlotLease:
    """借出的槽。``release()`` 幂等：同一对象只归还一次。"""

    def __init__(self, slots: SpawnSlots) -> None:
        self._slots = slots
        self._returned = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._returned:
                return
            self._returned = True
        self._slots._release()


_slots_lock = threading.Lock()
_slots: dict[str, SpawnSlots] = {}


def spawn_slots(session_id: str = "") -> SpawnSlots:
    """该会话的槽桶（惰性创建；同一 session_id 恒返回同一实例）。"""
    key = str(session_id or "")
    with _slots_lock:
        slots = _slots.get(key)
        if slots is None:
            slots = SpawnSlots(agent_spawn_limit())
            _slots[key] = slots
        return slots


def acquire_agent_slot(session_id: str = "") -> AgentSlotLease | None:
    """取该会话一个槽；满返回 None。"""
    return spawn_slots(session_id).try_acquire()


def agent_spawn_available(session_id: str = "") -> int:
    """该会话当前可用槽数（观测 / 测试用；会惰性建桶）。"""
    return spawn_slots(session_id).available()


def forget_session(session_id: str) -> None:
    """会话删除时回收它的桶。

    桶对象只有几十字节，不回收也不算泄漏；回收是为了让"会话已删、槽还在"不成立
    （同 id 复用时拿到的是计数归零的新桶）。在途租约不因此复活。
    """
    with _slots_lock:
        _slots.pop(str(session_id or ""), None)


__all__ = [
    "DEFAULT_AGENT_SPAWN_LIMIT",
    "DEFAULT_SUBAGENT_DAG_LIMIT",
    "DEFAULT_TOOL_BATCH_LIMIT",
    "ENV_AGENT_SPAWN_LIMIT",
    "ENV_TOOL_BATCH_LIMIT",
    "AgentSlotLease",
    "SpawnSlots",
    "acquire_agent_slot",
    "agent_spawn_available",
    "agent_spawn_limit",
    "forget_session",
    "spawn_slots",
    "subagent_dag_limit",
    "tool_batch_limit",
]
