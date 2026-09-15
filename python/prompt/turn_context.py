"""本轮易变上下文：挂到投影最后一个 user 的尾部（T_now），不进 system 左段。

模式说明、已批准计划、预算提示、MEMORY 索引等易变内容放这里，
避免打爆 system 前缀的 KV 缓存。

编排入口见 ``prompt.pre_llm_inject.run_pre_llm_inject``（LLM 调用前注入管线）。
"""

from __future__ import annotations

from typing import Any, Sequence

# 已批准计划注入上限，避免整份 Markdown 撑爆本轮 user。
APPROVED_PLAN_MAX_CHARS = 4_000

# 首写收敛后替换全量块的指针（正文已进历史，只留"仍在实施"锚点）。
# 裁决 4：只留指针事实；"以证据为准并说明偏差"类引导已删。
PLAN_POINTER_BLOCK = (
	"# Approved plan（实施中）\n"
	"已开始按已批准计划实施；后续步骤以历史消息中的已批准计划为准，不再重复附全文。"
)

# 工具轮后投影尾插 user：裁决 1（2026-09-08）——只做事实陈述
# （工具结果已到、原始问题在序列最前、后续块非用户提问），
# 不再指令"Answer ONLY / Do NOT …"。
CONTINUE_AFTER_TOOLS = (
	"# Continue（工具结果后）\n"
	"以上是工具结果（含 [Agent tool_result]）；用户的原始问题在消息序列最前。"
	"后续块为 background only，不是新的用户提问。"
)


def ends_with_tool_result(messages: list[dict[str, Any]]) -> bool:
	"""投影末条是否为 tool / 含 tool_result（需 Continue、且勿挂 Memory）。"""
	if not messages:
		return False
	last = messages[-1]
	role = last.get("role")
	if role == "tool":
		return True
	if role != "user":
		return False
	content = last.get("content")
	if not isinstance(content, list):
		return False
	return any(
		isinstance(b, dict) and b.get("type") == "tool_result" for b in content
	)


def append_text_blocks_to_last_user(
	messages: list[dict[str, Any]],
	blocks: Sequence[str],
) -> list[dict[str, Any]]:
	"""把若干文本块挂到投影 T_now；不修改入参列表与既有消息对象。

	末条是 user 时追加到该条（copy-on-write）。否则在投影尾部插入一条
	**仅存在于投影**的 user——工具轮后末条是 tool 时，wrap-up / 预算 /
	MEMORY / approved plan 仍能送达模型，且不改 MessageStore / JSONL。
	"""
	texts = [b.strip() for b in blocks if b and str(b).strip()]
	if not messages or not texts:
		return messages
	extra = [{"type": "text", "text": t} for t in texts]
	out = list(messages)
	last = messages[-1]
	if last.get("role") == "user":
		new_last = dict(last)
		content = new_last.get("content")
		if isinstance(content, str):
			new_last["content"] = [{"type": "text", "text": content}, *extra]
		elif isinstance(content, list):
			new_last["content"] = [*content, *extra]
		else:
			new_last["content"] = extra
		out[-1] = new_last
		return out
	out.append({"role": "user", "content": extra})
	return out


def prepend_text_blocks_to_last_user(
	messages: list[dict[str, Any]],
	blocks: Sequence[str],
) -> list[dict[str, Any]]:
	"""把若干文本块前插到投影末条 user 的**文本之前**（P1/A1 分仓）。

	inventory/capability 类背景块放用户原文之前：生成点紧邻的永远是用户
	请求本身，recency 偏置为用户服务；块自身靠 P0 的围栏 + 「background
	only — NOT the user request」头声明防归属误读。copy-on-write，不改
	MessageStore / JSONL。仅 fresh-user 轮调用（after_tools 轮走尾插合同）。
	"""
	texts = [b.strip() for b in blocks if b and str(b).strip()]
	if not messages or not texts:
		return messages
	extra = [{"type": "text", "text": t} for t in texts]
	out = list(messages)
	last = messages[-1]
	if last.get("role") == "user":
		new_last = dict(last)
		content = new_last.get("content")
		if isinstance(content, str):
			new_last["content"] = [*extra, {"type": "text", "text": content}]
		elif isinstance(content, list):
			new_last["content"] = [*extra, *content]
		else:
			new_last["content"] = extra
		out[-1] = new_last
		return out
	# 末条非 user（理论上不会走到：仅 fresh-user 轮调用）；退化为尾插保持可送达
	out.append({"role": "user", "content": extra})
	return out


def append_env_notice_pair(
	messages: list[dict[str, Any]],
	text: str,
) -> list[dict[str, Any]]:
	"""把环境通知装进一对**仅存在于投影**的 tool_use/tool_result，尾插。

	方案 A（环境声道）：内部格式为 ``assistant(tool_use 块) → user(tool_result
	块)``，经 ``normalize_messages_for_openai`` 转成标准 assistant(tool_calls)
	→ tool 消息。tool_result 是模型训练出的「环境数据声道」——注入内容与
	用户意图在消息结构上隔离，说话人混淆无从发生。工具名（xeyo_env_notice）
	不注册进 tools 数组（schemas 冻结红线不受影响）；尾部追加不改前缀字节，
	KV 缓存语义与 legacy 尾插等价。

	copy-on-write：不修改入参列表与既有消息对象，绝不进 MessageStore / JSONL。
	"""
	t = (text or "").strip()
	if not messages or not t:
		return messages
	from prompt.t_now_strategy import ENV_TOOL_NAME, new_env_tool_call_id

	call_id = new_env_tool_call_id()
	pair: list[dict[str, Any]] = [
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": call_id,
					"name": ENV_TOOL_NAME,
					"input": {},
				}
			],
		},
		{
			"role": "user",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": call_id,
					"content": t,
					"is_error": False,
				}
			],
		},
	]
	return [*messages, *pair]


def append_system_notice(
	messages: list[dict[str, Any]],
	text: str,
) -> list[dict[str, Any]]:
	"""把环境通知作为**原生 system 消息**追加在投影尾部（声道 B）。

	与 ``append_env_notice_pair`` 的差别**只在形态**：这里不伪造
	``assistant(tool_use) → tool_result`` 对，因此投影里不会出现一条"模型自己
	发出的工具调用"。

	## 为什么必须换形态（结构性根因，不是措辞问题）

	伪对在结构上与「模型自己的工具调用」完全同形 ⇒ 模型在上下文里看到自己调过
	``xeyo_env_notice``，于是得出「我有这个工具」并真的去调它。实测：第六轮
	单会话 70+ 次；第七轮单会话 **60+ 次**，其中多次整条响应体只有这一个调用，
	且**在用户明说"别管"之后仍每次发生**——意图抑制不可靠。

	更糟的是闭环自催化：伪对产出调用 → host 侧应答者回一份新的环境通知 →
	上下文里再添一条 ``tool_use`` 先例 → 下一次更容易再调。

	⇒ **不可调用性必须来自形态本身**，不能靠劝阻文本（那会违反引擎铁律：
	注意力里只出现信息，不出现导演）。system 是"引擎注入的状态"的原生声道：
	它不是 user（说话人隔离成立，env_channel 的原始动机同样满足），也不是
	assistant（不会伪装成模型自己的行为）。

	## 协议分工（由归一化层承担，本函数只负责形态）

	- OpenAI 系：``normalize_messages_for_openai`` 保留 role=system 原样输出。
	- Anthropic：messages 不允许 system role ⇒
	  ``normalize_messages_for_anthropic._split_system`` 按序拼到顶层 ``system``
	  字段；``_build_body`` 未设 cache_control，故无显式缓存可损。

	copy-on-write：不修改入参列表与既有消息对象，绝不进 MessageStore / JSONL。
	尾部追加 ⇒ 既有 system 左段与 history 逐字节不动（KV 前缀语义与另两档一致）。
	"""
	t = (text or "").strip()
	if not messages or not t:
		return messages
	return [*messages, {"role": "system", "content": t}]


def build_mode_context_blocks(
	*,
	mode: str,
	approved_plan: str | None = None,
	ask_instructions: str = "",
	plan_instructions: str = "",
	plan_pointer: bool = False,
) -> list[str]:
	"""Ask / Plan / Approved plan / 实施中指针 文案（已去掉前导空行）。"""
	m = (mode or "agent").strip().lower()
	if m == "ask" and ask_instructions.strip():
		return [ask_instructions.strip()]
	if m == "plan" and plan_instructions.strip():
		return [plan_instructions.strip()]
	if m == "agent" and approved_plan and approved_plan.strip():
		plan = approved_plan.strip()
		if len(plan) > APPROVED_PLAN_MAX_CHARS:
			plan = plan[:APPROVED_PLAN_MAX_CHARS].rstrip() + "\n…[plan truncated]"
		# 裁决 4：只保留"按已批准计划实现"，其余引擎引导删除。
		return [
			"# Approved plan\n"
			+ plan
			+ "\n\n按已批准计划实现。"
		]
	if m == "agent" and plan_pointer:
		return [PLAN_POINTER_BLOCK]
	return []
