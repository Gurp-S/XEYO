"""流式契约的门（一）：后端侧。

堵的是这一类事故：新增/改名一个 `xy.type`，前端 if-chain 没有分支 ⇒ 帧被静默
丢弃、界面少一块且**没有任何测试变红**；或请求体 `Literal` 少一个取值 ⇒ 客户端
一发消息就 422。前端侧的对账在 `gui/src/lib/api/streamContract.test.ts`。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.export_stream_contract import check_output
from server.stream_contract import (
	ACCEPT_EVENT_KEYS,
	STREAM_EVENT_TYPES,
	UndeclaredStreamType,
	accepted_payload,
	assert_stream_type,
)

_PY_ROOT = Path(__file__).resolve().parents[1]

#: 会把 xy 帧发出去的文件（新增发帧模块就加一行）。
_EMITTER_FILES = (
	_PY_ROOT / "server" / "routers" / "chat.py",
	_PY_ROOT / "engine" / "turn_runner.py",
	_PY_ROOT / "tools" / "agent_tool" / "agent_tool.py",
)

_TYPE_LITERAL = re.compile(r'"type"\s*:\s*"([a-z_]+)"')

#: 与流式帧无关的 `"type": ...`（内容块类型、JSON Schema 标量等）。
_NON_FRAME_TYPES = frozenset(
	{
		"array",
		"boolean",
		"function",
		"image_url",
		"integer",
		"number",
		"object",
		"string",
		"text",
		"tool_use",
	}
)


def _emitted_literals() -> set[str]:
	found: set[str] = set()
	for path in _EMITTER_FILES:
		if not path.exists():
			continue
		found.update(_TYPE_LITERAL.findall(path.read_text(encoding="utf-8")))
	return found


def test_emitter_scan_actually_finds_frame_types() -> None:
	"""扫描器烂掉（文件挪走/正则失配）会让下面那道门假绿，先自证。"""
	found = _emitted_literals()
	assert len(found) >= 18, f"发帧点扫到 {len(found)} 个类型，明显不对：{sorted(found)}"
	assert {"permission_pending", "tool_call", "usage"} <= found


def test_every_emitted_frame_type_is_declared() -> None:
	undeclared = _emitted_literals() - _NON_FRAME_TYPES - STREAM_EVENT_TYPES
	assert not undeclared, (
		f"发帧处出现未登记类型 {sorted(undeclared)}；"
		"先在 server/stream_contract.py 的 STREAM_EVENT_TYPES 登记"
	)


def test_assert_stream_type_rejects_undeclared() -> None:
	with pytest.raises(UndeclaredStreamType):
		assert_stream_type({"type": "brand_new_frame"})
	with pytest.raises(UndeclaredStreamType):
		assert_stream_type({})
	assert assert_stream_type({"type": "usage"})["type"] == "usage"


def test_generated_contract_is_fresh() -> None:
	"""后端改了枚举/帧名却没重导出 ⇒ 红（CI 亦以 --check 把同一道门）。"""
	assert check_output() == 0, "gui/src/generated/streamContract.ts 已过期"


_ACCEPT_CALL = re.compile(r'accepted_payload\(\s*"([a-z_]+)"')


def test_accepted_payload_rejects_key_drift() -> None:
	"""受理体少一个键就红：漏发 `message_id` 会让引导回执无法对号。"""
	accepted_payload(
		"queued", queued=True, delivery="after_turn", queue_id="q1", position=1
	)
	with pytest.raises(UndeclaredStreamType):
		accepted_payload("queued", queued=True, delivery="after_turn", position=1)
	with pytest.raises(UndeclaredStreamType):
		accepted_payload("brand_new_accept", anything=1)


def test_declared_accept_kinds_are_all_emitted() -> None:
	"""声明了却没人发 = 死口径；发了却未登记 = 前端无从对齐。两者都红。"""
	src = (_PY_ROOT / "server" / "routers" / "chat.py").read_text(encoding="utf-8")
	emitted = set(_ACCEPT_CALL.findall(src))
	assert emitted == set(ACCEPT_EVENT_KEYS), (
		f"chat.py 发出的受理体 {sorted(emitted)} 与声明集 "
		f"{sorted(ACCEPT_EVENT_KEYS)} 不一致"
	)
