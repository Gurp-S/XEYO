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
	"已批准计划的全文位于消息历史；当前状态为实施中。"
)

# 工具轮后投影尾插 user：裁决 1（2026-09-08）——只做事实陈述
# （工具结果已到、原始问题在序列最前、后续块非用户提问），
# 不再指令"Answer ONLY / Do NOT …"。
CONTINUE_AFTER_TOOLS = (
	"# Continue（工具结果后）\n"
	"以上是工具结果（含 [Agent tool_result]）；用户的原始问题在消息序列最前。"
	"后续块来源=引擎背景状态。"
)


def ends_with_tool_result(messages: list[dict[str, Any]]) -> bool:
	"""投影末条是否为 tool / 含 tool_result（需 Continue、且勿挂 Memory）。

	尾部的**引擎留痕**（system 形态、或通报片段形态的 role=user 条目）不算轮边界：
	上一边界落库的状态片段就贴在工具结果后面，把它当"末条"会误判成 fresh-user 轮
	⇒ Continue 合同与 MEMORY 挂载双双走错档。
	"""
	if not messages:
		return False
	from prompt.notice_channel import is_notice_message

	last: dict[str, Any] | None = None
	for m in reversed(messages):
		if not isinstance(m, dict) or is_notice_message(m):
			continue
		last = m
		break
	if last is None:
		return False
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


def _strip_stale_env_pairs(
	messages: list[dict[str, Any]], prefix: str
) -> list[dict[str, Any]]:
	"""剥掉历史里残留的环境伪对块（投影-only 状态不得跨轮存活）。

	伪对（assistant tool_use + user tool_result，id 前缀即 ``prefix``）只应存在
	于**当轮**投影。若上一轮把它落进了历史或投影缓存，本轮再追加新对，请求里
	就会带着旧对的半边（另一半被压缩/改写掉）——那是一条**无主的 tool 结果**，
	厂商直接 400（`role 'tool' must be a response to a preceding message with
	'tool_calls'`）。此处只剥离、不新增任何文本。
	"""
	out: list[dict[str, Any]] = []
	for message in messages:
		content = message.get("content")
		if not isinstance(content, list):
			out.append(message)
			continue
		kept: list[Any] = []
		for block in content:
			if isinstance(block, dict) and block.get("type") in {"tool_use", "tool_result"}:
				uid = str(block.get("id") or block.get("tool_use_id") or "")
				if uid.startswith(prefix):
					continue
			kept.append(block)
		if not kept:
			continue  # 整行都是伪对残片 → 整行丢弃
		out.append({**message, "content": kept} if len(kept) != len(content) else message)
	return out


def _strip_env_notice_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""剥掉历史里残留的环境伪对块（``xeyo_env_`` 前缀）——投影状态不跨轮存活。

	伪对只应存在于**本轮**投影尾部。一旦哪一轮把它带进了历史或投影缓存，再追加
	新对就会出现两组 tool_use/tool_result；旧的若只剩半边，就是"无主 tool 结果"
	⇒ 厂商 400（2026-09-20 事故的怀疑来源）。追加前统一清掉带该前缀的块，整行被
	清空即丢该行；无残留时返回原列表。
	"""
	from prompt.t_now_strategy import ENV_ID_PREFIX

	out: list[dict[str, Any]] = []
	changed = False
	for m in messages:
		content = m.get("content") if isinstance(m, dict) else None
		if not isinstance(content, list):
			out.append(m)
			continue
		kept: list[Any] = []
		for b in content:
			if isinstance(b, dict) and str(b.get("type") or "") in {
				"tool_use",
				"tool_result",
			}:
				uid = str(b.get("id") or b.get("tool_use_id") or "")
				if uid.startswith(ENV_ID_PREFIX):
					changed = True
					continue
			kept.append(b)
		if not kept:
			changed = True
			continue
		out.append({**m, "content": kept})
	return out if changed else messages


def strip_stale_env_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""剥掉投影里遗留的环境伪对行（投影-only 状态不跨轮存活）。

	伪对由引擎自己生成、**只应存在于本轮投影**；一旦哪一轮把它写进了历史或
	投影缓存，下一轮就会带着一条无主的 ``tool_result``（``xeyo_env_*``）继续走
	——厂商 400 ``role 'tool' must be a response to a preceding message with
	'tool_calls'``，且每轮重算同一个坏形状 ⇒ 会话结构性卡死（2026-09-20 实测）。
	本函数只做剥离，不新增/改写任何文本。
	"""
	from prompt.t_now_strategy import ENV_ID_PREFIX

	out: list[dict[str, Any]] = []
	for m in messages:
		if not isinstance(m, dict):
			out.append(m)
			continue
		content = m.get("content")
		if isinstance(content, list) and any(
			isinstance(b, dict)
			and str(b.get("type") or "") in {"tool_use", "tool_result"}
			and str(b.get("id") or b.get("tool_use_id") or "").startswith(ENV_ID_PREFIX)
			for b in content
		):
			continue
		out.append(m)
	return out if len(out) != len(messages) else messages


def _is_env_pair_row(message: object) -> bool:
	"""该行是否是环境声道伪对的载体（含 ``xeyo_env_`` 的 tool_use/tool_result）。

	伪对是**仅存在于投影**的状态，本不该跨轮存活；一旦上一轮只留下半对，
	本轮再追加新对就会在历史里多出一条无主 tool 结果 ⇒ 厂商 400
	（2026-09-20 事故）。剥掉旧对是纯删除，不新增任何文本。
	"""
	from prompt.t_now_strategy import ENV_ID_PREFIX, ENV_TOOL_NAME

	if not isinstance(message, dict):
		return False
	content = message.get("content")
	if not isinstance(content, list):
		return False
	for block in content:
		if not isinstance(block, dict):
			continue
		if block.get("type") not in {"tool_use", "tool_result"}:
			continue
		uid = str(block.get("id") or block.get("tool_use_id") or "")
		if uid.startswith(ENV_ID_PREFIX) or str(block.get("name") or "") == ENV_TOOL_NAME:
			return True
	return False


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
	追加前先剥掉历史残留的同前缀伪对（见 ``_strip_env_notice_pairs``）：保证
	任一投影里只存在**一对**环境通知，不会出现无主的 tool_result 块。
	"""
	t = (text or "").strip()
	if not messages or not t:
		return messages
	from prompt.t_now_strategy import ENV_TOOL_NAME, new_env_tool_call_id

	base = _strip_env_notice_pairs(messages)
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
		return ["# Approved plan\n" + plan]
	if m == "agent" and plan_pointer:
		return [PLAN_POINTER_BLOCK]
	return []
