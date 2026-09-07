"""统一事件外壳（envelope）——为每条事件附加可关联、可排序、可去重的身份。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from msgtypes.events import EngineEvent


@dataclass(frozen=True)
class Envelope:
    """事件传输外壳。旧客户端可忽略 payload 之外的字段，不影响解码。

    schema_version: 事件协议版本，便于未来演进。
    session_id:     会话身份，用于隔离不同会话的事件。
    turn_id:        回合身份，同一会话的每轮交互有一个稳定值。
    event_id:       同 turn 内单调递增，供前端去重、排序、断线 reset/replay。
    created_at:     事件产生时间（unix 秒）。
    type:           事件类型，与 payload.type 保持一致，便于快速路由。
    payload:        具体事件对象，保留现有 dataclass 结构。
    """

    schema_version: str
    session_id: str
    turn_id: str
    correlation_id: str
    event_id: int
    created_at: float
    type: str
    payload: Any


def wrap(
    event: EngineEvent,
    *,
    session_id: str,
    turn_id: str,
    event_id: int,
    correlation_id: str | None = None,
    schema_version: str = "1.0",
) -> Envelope:
    """把一条 EngineEvent 包装成带身份的 Envelope。

    correlation_id 为 request 级关联键（断线重连后同一次请求的事件仍可归组）；
    缺省与 turn_id 一致（旧客户端不感知差异）。
    """
    etype = getattr(event, "type", type(event).__name__)
    return Envelope(
        schema_version=schema_version,
        session_id=session_id,
        turn_id=turn_id,
        correlation_id=correlation_id or turn_id,
        event_id=event_id,
        created_at=time.time(),
        type=etype,
        payload=event,
    )


@dataclass
class EventIdGenerator:
    """同 turn 内的单调递增事件号生成器。"""

    _sequence: int = 0

    def next(self) -> int:
        self._sequence += 1
        return self._sequence

    def reset(self) -> None:
        self._sequence = 0

