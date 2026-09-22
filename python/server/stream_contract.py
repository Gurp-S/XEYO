"""流式帧契约的**唯一声明面**（引擎 ↔ GUI ↔ TUI 的 wires 口径）。

为什么要有这个模块：本轮联调审计里有一整类缺陷是"两套口径各写各的"——
后端改了/新增了 `xy.type`，前端 `parseSseBlock()` 的 if-chain 缺分支，于是帧被
**静默丢弃**（不报错、不告警、测试全绿）；反向也成立（前端留着后端从不发的死分支）。
`provider` 的 `Literal[...]` 少一个取值同理（选 Anthropic 后每轮 422）。

三道门：
1. `_id()` 组帧时断言 type 已在此声明（新帧名必须先登记，运行即红）。
2. `python/tests/test_stream_contract.py`：静态扫描发帧文件里的字面量 type
   必须 ⊆ 声明集；并断言生成物未过期（`--check`）。
3. `gui/src/lib/streamContract.test.ts`：声明集 ↔ 前端解析分支双向对账，
   外加 GUI 的 provider 联合类型 ⊆ 后端 `Literal`，以及忙时 202 受理体的键集
   （`ACCEPT_EVENT_KEYS`）↔ 前端读取的键双向对账。

生成物：`py -3.11 -m server.export_stream_contract` → `gui/src/generated/streamContract.ts`
（提交进仓库，与 `slash.export_manifest` 同一套路：构建期直接 import，不做跨语言运行时耦合）。
"""

from __future__ import annotations

#: 旁路帧在 OpenAI chunk 里的信封键。前端只认这一个键。
XY_ENVELOPE_KEY = "xy"
#: 正文帧（无 xy）携带的事件号键——重连去重靠它，缺了它游标只能停在结构化帧上。
CHUNK_EVENT_ID_KEY = "xeyo_event_id"
#: 流终止标记。
DONE_TOKEN = "[DONE]"

#: 后端**可能**发出的全部 `xy.type`。新增帧必须在此登记后才能上线。
STREAM_EVENT_TYPES: frozenset[str] = frozenset(
	{
		"reasoning_delta",
		"tool_call",
		"tool_result",
		"tool_progress",
		"usage",
		"title",
		"goal",
		"jobs",
		"task_state_changed",
		"steer_delivered",
		"permission_pending",
		"permission_resolved",
		"ask_user_pending",
		"ask_user_resolved",
		"plan_pending",
		"plan_resolved",
		"llm_retry",
		"llm_retry_started",
		# 压缩帧按 phase 动态拼名（chat.py 用 f-string），两个取值都在这儿。
		"context_compression_start",
		"context_compression_complete",
		# 多 Agent 子任务（经 ToolProgressEvent.xy）。
		"multi_agent_task",
		"multi_agent_progress",
		"multi_agent_delta",
		# reattach 重放有洞（turn_runner 环形缓冲挤掉过帧）。
		"stream_gap",
	}
)


class UndeclaredStreamType(ValueError):
	"""发出了未登记的帧类型——必须先在 `STREAM_EVENT_TYPES` 登记。"""


#: 忙时 POST /chat 的 202 受理体口径（唯一真相）。
#: - queued  ：settle 后排（下一轮才送达），有 inbox queue_id 可撤销。
#: - steered ：本轮边界投递，不入 inbox，客户端消息 id 就是它唯一的身份。
#: GUI `chatStream.ts` 的 202 分支按 `steered` 分流这两者，键集漂移即幽灵卡。
ACCEPT_EVENT_KEYS: dict[str, frozenset[str]] = {
	"queued": frozenset({"queued", "delivery", "queue_id", "position"}),
	"steered": frozenset({"queued", "steered", "delivery", "message_id"}),
}


def accepted_payload_kind(body: dict) -> str | None:
	"""从 202 受理体判口径类型（对齐 Codex：queued_messages vs TurnSteer 两种回执）。"""
	if body.get("steered") is True:
		return "steered"
	if body.get("queued") is True:
		return "queued"
	return None


def accepted_payload(kind: str, **fields: object) -> dict:
	"""组 202 受理体：键集必须与 `ACCEPT_EVENT_KEYS[kind]` 完全一致。

	受理体不是流式帧，但同样是 wires 口径：后端改键名（或漏发 `message_id`）
	而 GUI 未跟随时，排队卡会静默变成删不掉的幽灵卡——所以在此当场抛，而不是
	等前端对不上号。
	"""
	declared = ACCEPT_EVENT_KEYS.get(kind)
	if declared is None:
		raise UndeclaredStreamType(
			f"未登记的受理体类型 {kind!r}；新增请先写入 ACCEPT_EVENT_KEYS"
		)
	got = frozenset(fields)
	if got != declared:
		raise UndeclaredStreamType(
			f"受理体 {kind!r} 键集漂移：期望 {sorted(declared)}，实得 {sorted(got)}"
		)
	return dict(fields)


def assert_stream_type(xy: dict) -> dict:
	"""组帧出口断言：xy.type 必须已登记。未登记即抛，绝不静默上线。"""
	kind = xy.get("type")
	if not isinstance(kind, str) or not kind:
		raise UndeclaredStreamType(f"xy 帧缺少 type：{xy!r}")
	if kind not in STREAM_EVENT_TYPES:
		raise UndeclaredStreamType(
			f"未登记的流式帧类型 {kind!r}；新增请先写入 STREAM_EVENT_TYPES"
		)
	return xy
