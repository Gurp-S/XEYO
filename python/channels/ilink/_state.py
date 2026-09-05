"""iLink 通道共享状态：模块级单例的集中承载（拆包后各子模块共享同一实例）。

不在此创建 asyncio 原语（Event/Lock 惰性创建并绑定当前 loop，见 bridge）；mirror
放在 stream.py（其 delta_extra 依赖 _mirror_sid，避免 _state ↔ stream 循环）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from channels.ilink import SESSION_ID
from channels.ilink.bridge import ILinkBridge
from channels.ilink.channel import ILinkChannel
from channels.filehelper.inbound_queue import InboundQueue
from channels.runner import FinalOnlyRunner

# 通道唯一桥与频道实例
_bridge = ILinkBridge()
_channel: ILinkChannel | None = None
_runner_ref: FinalOnlyRunner | None = None
_prev_complete: Any = None

# 入站队列与会话游标
_inbound_q = InboundQueue()
_last_session_id = SESSION_ID
_stream_session_id = ""

# 凭据持久化去抖句柄 / 入站分发锁
_persist_handle: asyncio.TimerHandle | None = None
_msg_lock: asyncio.Lock | None = None