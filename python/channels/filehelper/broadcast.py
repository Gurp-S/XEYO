"""File Helper SSE 广播：入站 / delta / status / outbound / state。"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

_subs: set[asyncio.Queue[tuple[str, dict[str, Any]] | None]] = set()
# 集合操作是同步的，用 threading.Lock 而非 asyncio.Lock：
# 模块级 asyncio.Lock 会绑定首个使用它的 loop，TestClient 每次请求
# 都用新 portal loop，跨 loop 复用导致 SSE 订阅永久挂起。
_lock = threading.Lock()


async def subscribe() -> asyncio.Queue[tuple[str, dict[str, Any]] | None]:
	q: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue(maxsize=512)
	with _lock:
		_subs.add(q)
	return q


async def unsubscribe(q: asyncio.Queue[tuple[str, dict[str, Any]] | None]) -> None:
	with _lock:
		_subs.discard(q)


def publish(event: str, data: dict[str, Any]) -> None:
	payload = (event, data)
	dead: list[asyncio.Queue] = []
	with _lock:
		subs = list(_subs)
	for q in subs:
		try:
			q.put_nowait(payload)
		except asyncio.QueueFull:
			dead.append(q)
	if dead:
		with _lock:
			for q in dead:
				_subs.discard(q)


def format_sse(event: str, data: dict[str, Any]) -> str:
	body = json.dumps(data, ensure_ascii=False)
	return f"event: {event}\ndata: {body}\n\n"
