"""runtime.py — 送模型投影。公式在 simulator，本文件只 Apply。

flowchart TD
  In[messages + working] --> Sw{XEYO_L5}
  Sw -->|project / 关| P[engine.compact.project]
  Sw -->|v61 实验通道| S0[state_from_messages]
  Sw -->|project + XEYO_C2_GATE| S0
  S0 --> D[decide forecast=p0]
  D --> K{a_star}
  K -->|keep| P[frozen_until 保持，字节稳定]
  K -->|C1| C1[note_c1 推进 frozen_until]
  K -->|C2| A[apply_c2]
  P --> T[记忆索引尾插 T_now]
  C1 --> T
  A --> T
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any

from engine.compact import (
	build_tool_use_names,
	keep_tail_cut,
	split_at_cursor,
)
from engine.compact import project as project_c0c1
from engine.aging import AGING_VERSION, aging_enabled
from memory.citation import message_citation
from memory.l5_flag import c2_gate, l5_mode, use_v61
from memory.summarize import extract_tool_summary, is_error_like
from memory.token import token_len
from memory.working import (
	WorkingSnapshot,
	append_compact_window,
	note_c1,
	note_c2,
	note_compact_checkpoint,
)


#: 老化边界推进的最小滞后（消息数）：两次推进之间至少积累这么多新消息，
#: 保证推进是稀发事件、推进后投影字节稳定（设计 N≈8 的落地映射）。
AGING_MIN_ADVANCE_DEFAULT = 8

# C2 确定性摘要：全局字符预算 + 类型配额（优先错误/取值，再 grep/assistant 结论，再普通）
C2_SUMMARY_BUDGET = 12_000
C2_QUOTA_ERROR = 400
C2_QUOTA_VALUE = 320
C2_QUOTA_ASSISTANT = 260  # 叙述性结论（git 提交号/文件结论/计数等）——事实常在此层，勿被低配额挤掉（B2）
C2_QUOTA_GREP = 220
C2_QUOTA_USER = 200
C2_QUOTA_DEFAULT = 120
C2_QUOTA_TOOL_USE = 80

# T8：C2 LLM 摘要旁路（默认关）。开关由环境变量 XEYO_C2_LLM_SUMMARY=1 显式开启；
# 关闭时 project_for_model/apply_c2_messages/force_compact 走纯确定性摘要（行为不劣化）。
C2_LLM_SUMMARY_ENV = "XEYO_C2_LLM_SUMMARY"

# 旁路请求末尾追加的压缩指令（重放前缀后原样追加，只收纯文本摘要）。
C2_SUMMARY_INSTRUCTION = (
	"\n\n# 压缩指令（请只输出摘要正文）\n"
	"请把以上对话压缩成一段纯文本摘要：保留用户目标、已确认的决定、关键工具结论、"
	"错误/取值事实、以及后续仍需要的上下文；省略普通寒暄与已无关的中间过程。"
	"只输出摘要正文本身，不要任何前言、解释、markdown 代码块或工具调用。"
)


def c2_llm_summary_enabled() -> bool:
	"""C2 LLM 摘要旁路（默认关）：**settings.memory 权威（GUI「记忆系统开关」面板可切换）**。

	eval / 脚本可写 ``memory_switches.save({"XEYO_C2_LLM_SUMMARY": "1"})``。
	与其它注册键一致（test_memory_switch_authority 契约）：运行时只读 get_value，
	env 不参与。多一次模型调用，成本权衡；实测吸收潜力高（96% 单次）但输出不稳定
	（同配置三次 62/92/83%），故默认关=确定性摘要。
	"""
	from memory.memory_switches import get_value

	return str(get_value("XEYO_C2_LLM_SUMMARY")).strip().lower() in ("1", "true", "on", "yes")


def _append_c2_instruction(messages: list[dict]) -> list[dict]:
	"""在重放前缀（system + 投影消息）末尾追加一条压缩指令。"""
	out = list(messages)
	try:
		from prompt.turn_context import append_text_blocks_to_last_user

		return append_text_blocks_to_last_user(out, [C2_SUMMARY_INSTRUCTION])
	except Exception:
		out.append({"role": "user", "content": C2_SUMMARY_INSTRUCTION})
		return out


async def c2_llm_bypass(
	*,
	system_prompt: str,
	messages: list[dict],
	model,
	abort,
	region_text: int,
	instruction: str | None = None,
) -> str | None:
	"""C2 摘要旁路请求：重放前缀打 warm cache，末尾追加压缩指令，只收纯文本。

	- 重放：``[system, *projected_messages, user(压缩指令)]`` —— 与模型已看到的
	  前缀完全一致，命中 KV 缓存（前缀重放）。
	- 只收 ``text_delta``；出现 ``tool_use`` 即视为非纯文本，返回 None 回退。
	- 拒绝不缩小：摘要 >= ``region_text``（被替换的左段字符数）→ None。
	- 任何异常/无 client/无 abort → None（fail-closed，回退确定性摘要）。

	返回有效摘要文本，失败返回 None。
	"""
	if model is None or abort is None:
		return None
	replay: list[dict] = [{"role": "system", "content": system_prompt}, *list(messages)]
	replay = _append_c2_instruction(replay) if not instruction else [
		*replay,
		{"role": "user", "content": instruction},
	]
	parts: list[str] = []
	try:
		async for chunk in model.stream(replay, [], abort):
			if chunk.kind == "tool_use":
				# 旁路只收纯文本；出现工具调用即失败回退
				return None
			if chunk.kind == "text_delta" and chunk.text:
				parts.append(chunk.text)
	except Exception:
		return None
	summary = "".join(parts).strip()
	if not summary:
		return None
	if len(summary) >= int(region_text or 0):
		# 拒绝不缩小的摘要（省 token 的收益不成立）
		return None
	return summary


async def prefetch_c2_summary(
	working: WorkingSnapshot,
	api_messages: list[dict],
	system_prompt: str | None,
	model,
	abort,
) -> str | None:
	"""引擎侧异步预取：在首压前把旁路摘要算好存进 ``working._pending_c2_summary``。

	只作用于「已进入 C2 压缩」且「旁路开启」的路径；失败置空，让
	``apply_c2_messages`` 回退确定性摘要。返回值仅供调用方观测，落地靠 pending 字段。
	"""
	try:
		working._pending_c2_summary = None
		if not c2_llm_summary_enabled() or model is None or abort is None:
			return None
		if not system_prompt:
			return None
		prefix = project_c0c1(api_messages)
		region_text = _region_chars(api_messages)
		summary = await c2_llm_bypass(
			system_prompt=system_prompt,
			messages=prefix,
			model=model,
			abort=abort,
			region_text=region_text,
		)
		if summary:
			working._pending_c2_summary = summary
		return summary
	except Exception:
		working._pending_c2_summary = None
		return None


def _resolve_c2_summary(
	working: WorkingSnapshot,
	left: list[dict],
	messages: list[dict],
	summary_provider,
) -> str:
	"""生成 C2 摘要：优先（a）已预取的旁路摘要；（b）注入的同步 provider；
	否则回退确定性摘要。任何失败都收敛到确定性，行为不劣化。

	summary_provider：同步 callable ``(left, region_chars) -> str | None``；
	返回的摘要需非空且小于 ``region_chars`` 才被采用，否则回退。
	"""
	pending = getattr(working, "_pending_c2_summary", None)
	if pending:
		# 预取结果只在当前轮一次性消费
		working._pending_c2_summary = None
		if len(pending) < _region_chars(left):
			return pending
	if c2_llm_summary_enabled() and summary_provider is not None:
		try:
			region_chars = _region_chars(left)
			got = summary_provider(left, region_chars)
			if isinstance(got, str) and got.strip() and len(got) < region_chars:
				return got
		except Exception:
			pass
	return deterministic_c2_summary(left, id_to_name=build_tool_use_names(messages))


def _aging_min_advance() -> int:
	try:
		return max(1, int(os.environ.get("XEYO_TOOL_AGING_MIN_ADVANCE", "") or AGING_MIN_ADVANCE_DEFAULT))
	except (TypeError, ValueError):
		return AGING_MIN_ADVANCE_DEFAULT


def maybe_advance_aging_boundary(messages: list[dict], working: WorkingSnapshot) -> bool:
	"""非 v61 路径的老化边界推进：把 frozen_until 前移到尾部保护区之前。

	仅在开启 XEYO_TOOL_AGING 时生效；带滞后门（≥MIN_ADVANCE）与 pair-safe
	切点。**已压缩态（compact_cursor>0）跳过**：避免与 C2 同轮抢推边界、
	制造双 miss。v61 模式不介入（其 C1 由公式决策）。
	"""
	if not aging_enabled() or use_v61():
		return False
	if int(working.compact_cursor or 0) > 0:
		return False
	candidate = pair_safe_cut(messages, keep_tail_cut(messages))
	if candidate - int(working.c1_frozen_until) < _aging_min_advance():
		return False
	note_c1(working, candidate)
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"memory.aging.advance",
			session_id=working.session_id,
			aging_version=AGING_VERSION,
			frozen_until=candidate,
			messages=len(messages),
		)
	except Exception:
		pass
	return True


def idle_seconds(working: WorkingSnapshot) -> float:
	"""根据 last_model_call_at 估算空闲秒数，供 ρ̂ / TTL 先验；无记录则 0"""
	at = working.last_model_call_at
	if at is None:
		return 0.0
	now = datetime.now(at.tzinfo) if at.tzinfo else datetime.now()
	return max(0.0, (now - at).total_seconds())


def _assistant_tool_ids(msg: dict[str, Any]) -> list[str]:
	"""取出 assistant 消息上的 tool_use / tool_calls id。"""
	ids: list[str] = []
	content = msg.get("content")
	if isinstance(content, list):
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_use":
				continue
			uid = str(block.get("id") or "")
			if uid:
				ids.append(uid)
	calls = msg.get("tool_calls")
	if isinstance(calls, list):
		for call in calls:
			if not isinstance(call, dict):
				continue
			uid = str(call.get("id") or "")
			if uid:
				ids.append(uid)
	return ids


def _tool_result_ids(msg: dict[str, Any]) -> list[str]:
	"""取出 role=tool 或 content 里 tool_result 的 id。"""
	ids: list[str] = []
	role = msg.get("role")
	if role == "tool":
		tid = str(msg.get("tool_call_id") or "")
		if tid:
			ids.append(tid)
	content = msg.get("content")
	if isinstance(content, list):
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_result":
				continue
			uid = str(block.get("tool_use_id") or "")
			if uid:
				ids.append(uid)
	return ids


def _pair_ranges(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
	"""assistant(tool_calls) 到其连续 tool 结果的半开区间。"""
	ranges: list[tuple[int, int]] = []
	i = 0
	n = len(messages)
	while i < n:
		ids = _assistant_tool_ids(messages[i])
		if not ids:
			i += 1
			continue
		j = i + 1
		while j < n and _tool_result_ids(messages[j]):
			j += 1
		ranges.append((i, j))
		i = j
	return ranges


def pair_safe_cut(messages: list[dict[str, Any]], cut: int) -> int:
	"""把切点移到成对边界：不得落在 assistant.tool_calls 与 role=tool 之间。"""
	cut = max(0, min(int(cut), len(messages)))
	for start, end in _pair_ranges(messages):
		if start < cut < end:
			cut = start
	return cut


def c2_cut_index(messages: list[dict], s0) -> int:
	"""计算 C2 应前进到的消息下标（不含尾部 Tk/Tnow），且不得小于当前 cursor"""
	_ = s0
	raw = keep_tail_cut(messages)
	return pair_safe_cut(messages, raw)


def _msg_kind(msg: dict[str, Any]) -> str:
	"""确定性摘要用的消息种类。"""
	if _assistant_tool_ids(msg):
		return "tool_use"
	if _tool_result_ids(msg):
		return "tool_result"
	role = str(msg.get("role") or "unknown")
	return role


def _msg_tokens(msg: dict[str, Any]) -> int:
	"""粗估一条消息的 token 数（utf-8/4）。"""
	content = msg.get("content")
	if isinstance(content, str):
		return token_len(content)
	if isinstance(content, list):
		parts: list[str] = []
		for block in content:
			if not isinstance(block, dict):
				continue
			if "text" in block:
				parts.append(str(block.get("text") or ""))
			elif "content" in block:
				parts.append(str(block.get("content") or ""))
		return token_len("\n".join(parts))
	return 0


def _msg_text(msg: dict[str, Any], limit: int = 160, *, id_to_name: dict[str, str] | None = None) -> str:
	"""取消息纯文本片段，供确定性摘要保留语义。

	tool_result 块按内容类型动态抽摘要（memory.summarize），不再无脑取前 160 字符：
	错误/栈回溯保留首尾、grep 只留 文件:行号 统计、read 保留开头、其它长文本 head+tail。
	text / assistant / tool_use 块仍取前 limit 字符，行为不变。
	"""
	content = msg.get("content")
	if isinstance(content, str):
		return content.strip()[:limit]
	if isinstance(content, list):
		parts: list[str] = []
		for block in content:
			if not isinstance(block, dict):
				continue
			bt = block.get("type")
			if bt == "text":
				txt = block.get("text") or ""
			elif bt == "tool_result":
				txt = block.get("content") or ""
				if not isinstance(txt, str):
					txt = str(txt)
				uid = str(block.get("tool_use_id") or "")
				name = (id_to_name or {}).get(uid, "")
				parts.append(extract_tool_summary(txt, name, max_text=limit))
				continue
			elif bt == "tool_use":
				name = str(block.get("name") or "")
				inp = block.get("input")
				txt = f"{name} {inp if isinstance(inp, str) else str(inp)}"
			else:
				txt = block.get("text") or ""
			if isinstance(txt, str) and txt.strip():
				parts.append(txt.strip())
		return "\n".join(parts).strip()[:limit]
	return ""


def _msg_quota(msg: dict[str, Any], *, id_to_name: dict[str, str] | None = None) -> int:
	"""按消息类型分配 C2 摘要字符配额（错误/取值优先）。"""
	kind = _msg_kind(msg)
	if kind == "user":
		return C2_QUOTA_USER
	if kind == "assistant":
		return C2_QUOTA_ASSISTANT
	if kind == "tool_use":
		return C2_QUOTA_TOOL_USE
	if kind == "tool_result":
		content = msg.get("content")
		raw = ""
		name = ""
		if isinstance(content, str):
			raw = content
		elif isinstance(content, list):
			for block in content:
				if not isinstance(block, dict) or block.get("type") != "tool_result":
					continue
				raw = str(block.get("content") or "")
				uid = str(block.get("tool_use_id") or "")
				name = (id_to_name or {}).get(uid, "")
				break
		if is_error_like(raw):
			return C2_QUOTA_ERROR
		from memory.summarize import extract_value_facts

		if len(extract_value_facts(raw, limit=8)) >= 3:
			return C2_QUOTA_VALUE
		lname = (name or "").lower()
		if lname in {"grep", "rg", "ripgrep", "search"}:
			return C2_QUOTA_GREP
		return C2_QUOTA_DEFAULT
	return C2_QUOTA_DEFAULT


def _summary_msg_line(
	msg: dict,
	i: int,
	*,
	max_text: int = 160,
	style: str = "new",
	id_to_name: dict[str, str] | None = None,
	cite=None,
) -> str:
	"""确定性摘要的单条消息行。style=old 只保留 id/kind/tokens（A/B 基线用）。

	cite：可选 ``citation.CitationEntry``，解释后作为引用锚点追加在行尾
	（仅 new 风格；legacy 基线不加，保持其 A/B 对照语义）。不改变 id/kind/tokens 前缀。
	"""
	uid = ""
	ids = _assistant_tool_ids(msg) or _tool_result_ids(msg)
	if ids:
		uid = ids[0]
	base = f"{i}:{uid or i}:{_msg_kind(msg)}:{_msg_tokens(msg)}"
	if style == "old":
		return base
	snippet = _msg_text(msg, max_text, id_to_name=id_to_name)
	suffix = f" :: {snippet}" if snippet else ""
	line = base + suffix
	if cite is not None:
		from memory.citation import entry_line

		line += f" ⟦{entry_line(cite)}⟧"
	return line


def _norm_sig(text: str) -> str:
	"""把正文归一化为「近似重复签名」：数字、空白全部规整。

	用于 P2 折叠：如 ``conclusion 0``/``conclusion 1`` → ``conclusion #``，
	``Read {'q': 'r0_1'}``/``Read {'q': 'r0_4'}`` → ``Read {'q': 'r#_#'}``——二者归为一桶，
	摘要只保留一条代表行 + 计数，去掉「同一模板重复 N 次」的字墙。
	"""
	t = re.sub(r"\d+", "#", text or "")
	t = re.sub(r"\s+", " ", t).strip()
	return t


def _c2_citation_enabled() -> bool:
	"""C2 摘要行引用锚点：**已固化开启**（原 XEYO_C2_CITATION 键已删，回退只能改源码）。"""
	return True


def _c2_fold_enabled() -> bool:
	"""P2 摘要折叠开关：默认开；可用 ``XEYO_C2_SUMMARY_FOLD=0`` 关（回退逐条基线）。"""
	raw = os.environ.get("XEYO_C2_SUMMARY_FOLD", "").strip().lower()
	if raw:
		return raw not in ("0", "false", "off", "no")
	return True


def _c2_role_group_enabled() -> bool:
	"""P3 摘要「按角色分组」开关：默认开。

	把摘要按角色分节（叙事结论/工具结果/工具调用），模仿 session.md 的
	Goal/Completed 结构化叙事——诊断显示失败事实「已吸收但定位难」，按角色分组
	让模型先看到「会话要点/结论」再看到工具数据（session.md 叙事吸收=100%）。
	可用 ``XEYO_C2_SUMMARY_ROLE_GROUP=0`` 关。仅影响 new 风格文本呈现，不改 Q/J。
	"""
	raw = os.environ.get("XEYO_C2_SUMMARY_ROLE_GROUP", "").strip().lower()
	if raw:
		return raw not in ("0", "false", "off", "no")
	return True


def _role_group(kind: str) -> int:
	"""角色分组优先级：0=叙事结论(assistant/user)，1=工具结果，2=工具调用/其它。"""
	if kind in ("assistant", "user"):
		return 0
	if kind == "tool_result":
		return 1
	return 2


def _c2_role_share() -> float:
	"""P4 角色组预算保底份额（new 风格）：给角色组0（assistant/user 结论）预留的预算比例。

	默认 0.35：确保叙事结论不被 quota 更高的 tool_result（错误/取值，400/320）吃光，
	避免结论消息整条落成 metadata、丢失叙述事实（表A 根因）。``XEYO_C2_ROLE_SHARE=0`` 关，
	=\":1.0\" 封顶；超界强制钳到 [0,1]。仅 new 风格参与预算分配。
	"""
	raw = os.environ.get("XEYO_C2_ROLE_SHARE", "").strip()
	if not raw:
		return 0.78
	try:
		v = float(raw)
	except (TypeError, ValueError):
		return 0.78
	return max(0.0, min(1.0, v))


def _c2_user_share() -> float:
	"""P4 角色组0 内 user 子池份额（new 风格）：保证用户请求在原叙述池里占一份预算。

	用户消息承载目标/意图/请求（会话锚，不可再生），故在角色组0 池内再拆出 user 子池，
	避免被 quota 更高的 assistant（260>200）挤掉（如 128k 这条用户写明的事实）。
	默认 0.3（XEYO_C2_USER_SHARE 可调/关=0 不分池，即 role_share 直接给组0）。
	"""
	raw = os.environ.get("XEYO_C2_USER_SHARE", "").strip()
	if not raw:
		return 0.25
	try:
		v = float(raw)
	except (TypeError, ValueError):
		return 0.25
	return max(0.0, min(1.0, v))


_ROLE_HEADERS = {0: "[C2] 会话要点/结论:", 1: "[C2] 工具结果:", 2: "[C2] 工具调用:"}


def deterministic_c2_summary(
	left: list[dict],
	*,
	max_text: int = 160,
	style: str | None = None,
	id_to_name: dict[str, str] | None = None,
	budget: int | None = None,
	with_citation: bool | None = None,
) -> str:
	"""无 session.md 时用确定性摘要代替左段（不 fork 模型）。

	new 风格：按类型配额分配每行 max_text，全局 ``budget`` 封顶；
	优先错误/取值/用户确认，耗尽预算后只留 id/kind/tokens。
	with_citation（引用锚点已固化开启）：每条压进行追加 ``⟦notes:msg:<i>:<kind>⟧``
	引用锚点，使压缩可追溯回原消息，且计入预算估算。
	"""
	import os as _os

	use_style = (style or _os.environ.get("XEYO_C2_SUMMARY_STYLE", "new")).strip().lower()
	style_kind = "old" if use_style in ("legacy", "old") else "new"
	names = id_to_name if id_to_name is not None else build_tool_use_names(left)
	cap = int(budget if budget is not None else C2_SUMMARY_BUDGET)
	cite_on = (with_citation if with_citation is not None else _c2_citation_enabled()) and style_kind == "new"
	cite_len = len(" ⟦notes:msg:0:msg⟧")
	lines = [f"[C2] compacted {len(left)} earlier messages"]
	used = len(lines[0])
	# 高优先行先占预算：错误 > 取值 > user > 其它
	order = list(range(len(left)))
	if style_kind == "new":
		def _prio(i: int) -> tuple[int, int]:
			q = _msg_quota(left[i], id_to_name=names)
			# 配额越大优先级越高；同档按原序
			return (-q, i)

		order.sort(key=_prio)
	assigned: dict[int, int] = {}
	# P4 角色组预算保底：new 风格给角色组0（assistant/user 结论）保留 share 份额预算。
	# 否则 quota 更高的 tool_result（错误/取值 400/320）优先吃满预算，把结论消息挤成
	# 仅 metadata 行，叙述事实（表A 探针所问）整条消失。默认 0.35（XEYO_C2_ROLE_SHARE 可调/关）。
	# P5 用户信息保底：组0 池内再拆 user 子池（默认 30%，XEYO_C2_USER_SHARE），
	# 保证用户请求（目标/意图，不可再生）不被 quota 更高的 assistant 挤掉。
	role_share = _c2_role_share() if style_kind == "new" else 0.0
	user_sub = _c2_user_share() if style_kind == "new" else 0.0
	if role_share > 0:
		_g0_cap = int(cap * role_share)
		if user_sub > 0:
			_user_cap = int(_g0_cap * user_sub)
			_ass_cap = _g0_cap - _user_cap
		else:
			_user_cap = 0
			_ass_cap = _g0_cap
		_other_cap = cap - _g0_cap
		g0_used = 0
		user_used = 0
		ass_used = 0
		other_used = 0
	# 去重复用预算：同一 kind+内容（含 11 份循环副本/重复工具结果）只占一次预算，
	# 避免把预算全耗在冗余内容上、挤掉承载事实的 assistant/user 消息（B2 摘要保真）。
	sig_seen: set[str] = set()
	for i in order:
		raw = _msg_text(left[i], limit=140, id_to_name=names).strip()
		sig = f"{_msg_kind(left[i])}:{len(raw)}:{raw[:80]}"
		is_dup = sig in sig_seen
		if not is_dup:
			sig_seen.add(sig)
		q = _msg_quota(left[i], id_to_name=names) if style_kind == "new" else max_text
		# 角色组预算保底：组0(assistant/user)/其它 各自封顶；组0 内再按 user/assistant 子池分。
		if role_share > 0:
			_kind = _msg_kind(left[i])
			_role = _role_group(_kind)
			if _role == 0:
				if _kind == "user" and user_sub > 0:
					pool_used = user_used
					pool_cap = _user_cap
				else:
					pool_used = ass_used
					pool_cap = _ass_cap
			else:
				pool_used = other_used
				pool_cap = _other_cap
			room = max(0, pool_cap - pool_used - 80 - (cite_len if cite_on else 0))
		else:
			room = max(0, cap - used - 80 - (cite_len if cite_on else 0))
		take = min(q, room, max_text * 3)
		if is_dup and take > 24:
			# 重复内容：默认只留元数据（B2 防预算耗尽），但「同 sig 的最后一个」保留——
			# 模板式重复（如 20 次 grep：每次同 pattern）末条承载「最后 id/末次事实」
			# （合成源 s05 grep_019、真实源末次工具调用），dedup 全丢会丢尾事实。
			kind_now = _msg_kind(left[i])
			# 预扫：是否还有同 sig 的后续消息（若无 → 我是最后一个，保留）
			has_later = any(
				j > i and _msg_kind(left[j]) == kind_now
				and _msg_text(left[j], limit=140, id_to_name=names).strip().startswith(raw[:40])
				for j in range(i + 1, len(left))
			)
			if not has_later:
				assigned[i] = take
			else:
				assigned[i] = 0  # 重复内容不再占预算，只留元数据行
			continue
		if take < 24 and style_kind == "new":
			assigned[i] = 0  # 仅 metadata
			continue
		assigned[i] = take if style_kind == "new" else max_text
		# 粗估占用
		_cost = 40 + assigned[i] + (cite_len if cite_on else 0)
		used += _cost
		if role_share > 0:
			_kind = _msg_kind(left[i])
			_role = _role_group(_kind)
			if _role == 0:
				if _kind == "user" and user_sub > 0:
					user_used += _cost
				else:
					ass_used += _cost
			else:
				other_used += _cost
	# 只输出携带片段的行（事实都在片段行里）；无片段（预算耗尽/重复）消息聚合为一行，
	# 避免把摘要撑成"每条一行"的字墙（B2 去噪：摘要精炼、高密度、模型可定位事实）。
	# P2 深化：new 风格再加「近似重复折叠」——同一 kind 且正文去掉数字后相同的行
	# （如 16 条 "conclusion N"、多条 tool_use）只保留 1 条代表行 + 计数，进一步去噪。
	# 关键副作用：按优先序分桶即天然把同 kind 聚合，错误/取值仍在头部，更易定位事实。
	header = lines[0]
	buckets: dict[tuple[str, str], list[int]] = {}
	order_keys: list[tuple[str, str]] = []
	# P2 折叠仅作用于「低事实、模板式重复」种类：assistant 结论 / tool_use 调用记录。
	# user 与 tool_result 一律不折叠——用户意图与工具结果里才承载真正事实（键值/报错），
	# 折叠会丢掉「仅数字不同」的独立事实（如 port=8080 与 port=9090）。
	fold_kinds = {"assistant", "tool_use"} if (style_kind == "new" and _c2_fold_enabled()) else set()
	for i in order:  # order = 优先序（new）或下标序（legacy）
		mt = assigned.get(i, max_text)
		if mt <= 0:
			continue
		kind = _msg_kind(left[i])
		if kind in fold_kinds:
			snippet = _msg_text(left[i], mt, id_to_name=names).strip()
			key = (kind, _norm_sig(snippet))
		else:
			key = (kind, str(i))  # 不折叠：user / tool_result / legacy
		if key not in buckets:
			buckets[key] = []
			order_keys.append(key)
		buckets[key].append(i)
	out = [header]
	# P3 绑定：new 风格按角色分节（叙事结论 → 工具结果 → 工具调用），模仿 session.md
	# 的 Goal/Completed 叙事，让已吸收的事实更可绑定/定位。仅在开启时生效（可关）。
	role_group_on = style_kind == "new" and _c2_role_group_enabled()
	if role_group_on:
		order_keys = sorted(order_keys, key=lambda k: _role_group(k[0]))
	# 折叠只在「≥3 次重复」时生效（清楚的可判定的模板重复）；<3 次的近似对保留逐条，
	# 避免把「仅数字不同」的独立事实（如 port=8080/port=9090 成对出现）误折叠。
	_last_role: int | None = None
	for key in order_keys:
		role = _role_group(key[0])
		if role_group_on and role != _last_role:
			# 只在对应角色有桶时才插分节头
			role_buckets = [k for k in order_keys if _role_group(k[0]) == role]
			if role_buckets:
				out.append(_ROLE_HEADERS[role])
				_last_role = role
		idxs = buckets[key]
		should_fold = style_kind == "new" and len(idxs) >= 3
		if should_fold:
			# P2 折叠改进（2026-09-06）：重复桶保留「首+尾」两条而非仅首条。
			# 模板式重复（20 次 grep：每次 21 行 TODO + X 填充）首条给"每次行数/样本"、
			# 尾条给"最后一个 id/末次事实"（如 grep_019、s05）；且尾条带编号
			# [+N 条同类] 计数，模型可由"首 21 行 × 20 次"推导 400/4000（s07/s09/s10）。
			rep_first, rep_last = idxs[0], idxs[-1]
			mt1 = assigned.get(rep_first, max_text)
			mt2 = assigned.get(rep_last, max_text)
			cite1 = message_citation(rep_first, kind=_msg_kind(left[rep_first])) if cite_on else None
			cite2 = message_citation(rep_last, kind=_msg_kind(left[rep_last])) if cite_on else None
			line1 = _summary_msg_line(left[rep_first], rep_first, max_text=mt1, style=style_kind, id_to_name=names, cite=cite1)
			line1 += f" [+{len(idxs) - 1} 条同类]"
			out.append(line1)
			if rep_last != rep_first:
				line2 = _summary_msg_line(left[rep_last], rep_last, max_text=mt2, style=style_kind, id_to_name=names, cite=cite2)
				out.append(line2)
		else:
			for rep in idxs:
				mt = assigned.get(rep, max_text)
				cite = message_citation(rep, kind=_msg_kind(left[rep])) if cite_on else None
				out.append(
					_summary_msg_line(left[rep], rep, max_text=mt, style=style_kind, id_to_name=names, cite=cite)
				)
	meta_count = len(left) - sum(len(b) for b in buckets.values())
	if meta_count:
		out.append(f"[C2] ... 另有 {meta_count} 条消息仅保留索引/类型，详见会话原文")
	return "\n".join(out)


def c2_summary_extension(
	region: list[dict],
	*,
	start_index: int = 0,
	max_text: int = 160,
	id_to_name: dict[str, str] | None = None,
) -> str:
	"""追加式扩展摘要：只覆盖新区间，绝不重写旧摘要文本（保证 KV 前缀命中）。"""
	names = id_to_name if id_to_name is not None else build_tool_use_names(region)
	# 扩展段用同一套配额逻辑，预算按新区长度缩放
	body = deterministic_c2_summary(
		region,
		max_text=max_text,
		style="new",
		id_to_name=names,
		budget=max(2_000, min(C2_SUMMARY_BUDGET, 400 * max(1, len(region)))),
	)
	# 替换头行标记为 EXT，并把行号偏移
	out_lines = [f"[C2+EXT] covered {len(region)} more messages"]
	for line in body.splitlines()[1:]:
		# 行格式 i:uid:kind:tokens — 把相对下标换成绝对
		parts = line.split(":", 3)
		if len(parts) >= 4 and parts[0].isdigit():
			parts[0] = str(start_index + int(parts[0]))
			out_lines.append(":".join(parts))
		else:
			out_lines.append(line)
	return "\n".join(out_lines)


def load_session_md(working: WorkingSnapshot) -> str | None:
	"""读取本会话 session.md；不存在或 Wave 2 未落地时返回 None"""
	sid = (working.session_id or "").strip()
	if not sid:
		return None
	try:
		from memory.session_md import load as _load_session_md
	except ImportError:
		return None
	return _load_session_md(sid)


# --------------------------------------------------------------------------- #
# A3 逃生舱 + A2 压缩碎片还原（v61建议采纳说明.md §1）
# --------------------------------------------------------------------------- #

#: 栈原文封顶：超过则保头（Traceback 帧起点）+ 保尾（异常收尾行）。
C2_ESCAPE_TRACEBACK_CAP = 2000
#: 逃生舱整块字符上限（先扣预留再分预算的固定预留量级）。
C2_ESCAPE_MAX_CHARS = 2600
#: 保留的最后文件路径条数。
C2_ESCAPE_PATH_COUNT = 3

_PATH_VALUE_RE = re.compile(r"^(?:[A-Za-z]:)?[\\/][^\s]{1,160}$")
_TOOL_PATH_KEYS = frozenset({"file_path", "path", "notebook_path", "abs_path", "file"})
#: 复合命令键：可能内嵌任意文本，不做路径提取（避免把整条 bash 命令当路径）。
_TOOL_NONPATH_KEYS = frozenset({"command", "cmd", "script", "input", "content"})


def _c2_escape_hatch_enabled() -> bool:
	"""A3 逃生舱：**已固化开启**（原 XEYO_C2_ESCAPE_HATCH 键已删，回退只能改源码）。"""
	return True


def _restore_enabled() -> bool:
	"""A2 压缩碎片还原：**已固化开启**（原 XEYO_MEMORY_RESTORE 键已删，回退只能改源码）。"""
	return True


def _msg_payload_texts(msg: dict[str, Any]) -> list[str]:
	"""消息里承载事实正文的文本（tool_result content / text 块），供原子分段。"""
	content = msg.get("content")
	out: list[str] = []
	if isinstance(content, str):
		out.append(content)
	elif isinstance(content, list):
		for block in content:
			if not isinstance(block, dict):
				continue
			if block.get("type") == "tool_result":
				txt = block.get("content")
				out.append(txt if isinstance(txt, str) else str(txt))
			elif isinstance(block.get("text"), str):
				out.append(str(block.get("text")))
	return out


def _msg_tool_inputs(msg: dict[str, Any]) -> list[dict[str, Any]]:
	"""消息里的 tool_use 调用参数 dict（两种消息形状都兼容）。"""
	out: list[dict[str, Any]] = []
	content = msg.get("content")
	if isinstance(content, list):
		for block in content:
			if isinstance(block, dict) and block.get("type") == "tool_use":
				inp = block.get("input")
				out.append(inp if isinstance(inp, dict) else {})
	calls = msg.get("tool_calls")
	if isinstance(calls, list):
		for call in calls:
			if not isinstance(call, dict):
				continue
			fn = call.get("function") or {}
			raw_args = fn.get("arguments") or call.get("input") or {}
			if isinstance(raw_args, str):
				try:
					parsed = json.loads(raw_args)
				except Exception:  # noqa: BLE001
					parsed = {}
				out.append(parsed if isinstance(parsed, dict) else {})
			elif isinstance(raw_args, dict):
				out.append(raw_args)
	return out


def _last_traceback_atom(left: list[dict]) -> tuple[int, str] | None:
	"""最近 1 条完整报错栈 → (绝对下标, 原文)。从新到旧扫，复用 segmenter 栈识别。

	确定性纯函数；segmenter 不可用/断言失败时回退正则抓整块。
	"""
	try:
		from memory.fidelity_segmenter import split_into_atoms
	except ImportError:  # pragma: no cover
		split_into_atoms = None  # type: ignore[assignment]
	for i in range(len(left) - 1, -1, -1):
		for text in _msg_payload_texts(left[i]):
			if "traceback (most recent call last)" not in text.lower():
				continue
			if split_into_atoms is not None:
				try:
					stacks = [a.text for a in split_into_atoms(text) if a.kind == "stack"]
				except AssertionError:
					stacks = []
				if stacks:
					return i, stacks[-1]
			m = re.search(
				r"traceback \(most recent call last\):[\s\S]*?(?=\n\S|\Z)",
				text,
				re.IGNORECASE,
			)
			if m:
				return i, m.group(0)
			return i, text
	return None


def _last_tool_paths(
	left: list[dict], k: int = C2_ESCAPE_PATH_COUNT
) -> list[tuple[int, str]]:
	"""最后 k 个不同文件路径 → [(绝对下标, path)]。优先工具调用参数，从新到旧。

	路径语义键（file_path/path/…）宽松接受；其它键要求值本身是路径形状；
	复合命令键（command/cmd/script）明确不提取（避免把整条命令当路径）。
	"""
	out: list[tuple[int, str]] = []
	seen: set[str] = set()
	for i in range(len(left) - 1, -1, -1):
		for inp in _msg_tool_inputs(left[i]):
			for key, val in inp.items():
				if key in _TOOL_NONPATH_KEYS or not isinstance(val, str):
					continue
				v = val.strip().strip('"').strip("'")
				if not v or v.startswith("-"):
					continue
				if key not in _TOOL_PATH_KEYS and not _PATH_VALUE_RE.match(v):
					continue
				norm = v.replace("\\", "/").lower()
				if norm in seen:
					continue
				seen.add(norm)
				out.append((i, v))
				if len(out) >= k:
					return out
	return out


def _clip_traceback(text: str, cap: int = C2_ESCAPE_TRACEBACK_CAP) -> str:
	"""栈原文超限：保头（帧起点）+ 保尾（异常收尾行），中间省略号衔接。"""
	t = (text or "").rstrip()
	if len(t) <= cap:
		return t
	head = t[: cap - 320]
	tail = t[-300:]
	return head + "\n…[栈中段省略]…\n" + tail


def c2_escape_hatch_block(left: list[dict]) -> str:
	"""A3 逃生舱块：最近 1 条完整 Traceback（逐字 ≤2KB）+ 最后 3 个文件路径。

	确定性纯函数（同 left → 同字节）；无栈且无路径返回 ""。锚点 id
	``notes:msg:<绝对下标>`` 与 citation 锚点同构，可 Memory(action=retrieve) 还原。
	"""
	tb = _last_traceback_atom(left)
	paths = _last_tool_paths(left)
	if tb is None and not paths:
		return ""
	lines = ["[C2] 逃生舱（不可压缩·最近现场，供调试定位）:"]
	if tb is not None:
		idx, text = tb
		lines.append(f'<last_traceback src="notes:msg:{idx}">')
		lines.append(_clip_traceback(text))
		lines.append("</last_traceback>")
	if paths:
		lines.append("<last_paths>")
		for idx, p in paths:
			lines.append(f"- {p}  (notes:msg:{idx})")
		lines.append("</last_paths>")
	block = "\n".join(lines)
	if len(block) > C2_ESCAPE_MAX_CHARS:
		block = block[: C2_ESCAPE_MAX_CHARS - 1] + "…"
	return block


def _store_c2_fragments(working: WorkingSnapshot, left: list[dict]) -> None:
	"""A2：把左区结构化原子全文抓拍进 sqlite（``notes:msg:<i>`` 可 retrieve 还原）。

	优先级保证：最近报错栈永远排第一（总量封顶也轮不到它被裁掉）；其余按
	(kind, 出现序) 抓拍。同文本去重（12× 循环副本不再浪费封顶额度）。同时写
	C1 因果边（tool_use→tool_result）。失败静默——还原/边表是增强项。
	"""
	try:
		if not _restore_enabled() or not (working.session_id or "").strip():
			return
		from memory import memindex
		from memory.fidelity_segmenter import split_into_atoms

		keep_kinds = {"stack", "kv", "path", "json", "tree", "table"}
		rows: list[dict] = []
		seen_text: set[str] = set()

		def _push(i: int, kind: str, seq: int, text: str) -> None:
			sig = f"{kind}:{hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()}"
			if sig in seen_text or not text.strip():
				return
			seen_text.add(sig)
			rows.append({"msg_index": i, "kind": kind, "seq": seq, "text": text})

		# ① 最近报错栈优先
		tb = _last_traceback_atom(left)
		if tb is not None:
			_push(tb[0], "stack", 0, tb[1])
		# ② 全区结构化原子
		for i, msg in enumerate(left):
			for text in _msg_payload_texts(msg):
				try:
					atoms = split_into_atoms(text)
				except AssertionError:
					continue
				seq_by_kind: dict[str, int] = {}
				for atom in atoms:
					if atom.kind not in keep_kinds:
						continue
					seq = seq_by_kind.get(atom.kind, 0)
					seq_by_kind[atom.kind] = seq + 1
					_push(i, atom.kind, seq, atom.text)
				if len(rows) >= 2000:
					break
			if len(rows) >= 2000:
				break
		# ③ C1 地基：tool_use → 其 tool_result 因果边
		edge_rows: list[dict] = []
		for i, msg in enumerate(left):
			for uid in _assistant_tool_ids(msg):
				j = i + 1
				while j < len(left):
					if uid in _tool_result_ids(left[j]):
						edge_rows.append({"from_msg": i, "to_msg": j, "kind": "tool_use"})
						break
					j += 1
		memindex.store_fragments(working.session_id, rows)
		if edge_rows:
			memindex.add_edges(working.session_id, edge_rows)
	except Exception:  # noqa: BLE001 — 增强项绝不阻塞压缩热路径
		pass


def apply_c2_messages(
	messages: list[dict],
	working: WorkingSnapshot,
	*,
	summary_provider=None,
) -> list[dict]:
	"""左段替换为一条 system/summary，右段从 cursor 起再跑 C0+C1。

	摘要文本在首次压缩时冻结进 ``working.c2_summary_text``，后续请求复用同一文本，
	保证压缩投影字节稳定（KV 缓存可命中）。右段按 c1_frozen_until（相对 cursor 的
	绝对下标换算）冻结中间 tool_result，避免压缩态「压完即回血」——中间区重新
	长满原文导致降智恢复与尾部体积失控（缺口②）。

	T8：首压摘要经 ``_resolve_c2_summary`` 生成——LLM 旁路（注入 provider / 预取）优先，
	失败/未开启回退确定性摘要；同时写入 ``compact_checkpoint``（投影锚点 + 窗口链 + 首压摘要）。
	"""
	left, right = split_at_cursor(messages, working.compact_cursor)
	# P1 缺失1：把 C2 左段（M 区）的原子分段记入 working，供按原子计权与审计。
	try:
		from memory.fidelity_segmenter import atoms_enabled, atoms_histogram

		if atoms_enabled():
			working.current_atoms = atoms_histogram(left)
	except Exception:
		pass
	if not working.c2_summary_text:
		summary = (
			load_session_md(working)
			or _resolve_c2_summary(working, left, messages, summary_provider)
		)
		# A3 逃生舱：最近 1 条完整 Traceback + 最后 3 个文件路径，先于冻结追加。
		# 挂在本层而非 summary 层——session.md 来源路径同样受保护；逃生舱随摘要
		# 一起冻结进 c2_summary_text（字节稳定，KV 命中不回归）。
		if _c2_escape_hatch_enabled():
			hatch = c2_escape_hatch_block(left)
			if hatch:
				summary = summary.rstrip() + "\n\n" + hatch
		working.c2_summary_text = summary
		# A2：压缩碎片抓拍（notes:msg:<i> 可 retrieve 还原）——与摘要冻结同点执行
		_store_c2_fragments(working, left)
		if working.compact_cursor > 0:
			note_compact_checkpoint(
				working,
				cursor=working.compact_cursor,
				frozen_until=working.c1_frozen_until,
				summary_text=working.c2_summary_text,
			)
	frozen_rel = max(0, working.c1_frozen_until - working.compact_cursor)
	head = [{"role": "system", "content": working.c2_summary_text, "name": "session_summary"}]
	return head + project_c0c1(right, frozen_until=frozen_rel)


def try_extend_c2(
	working: WorkingSnapshot,
	messages: list[dict],
	new_cursor: int,
	params,
	remaining_turns: int,
	force: bool = False,
) -> bool:
	"""已压缩态下追加式扩展冻结摘要（append-only），返回是否执行。

	旧摘要文本保持为前缀字节不变 → 后续请求仍命中 KV 缓存；扩展只把新区间的
	确定性摘要追加到旧文本尾部。不满足收益/稀发/摊薄条件时返回 False，调用方
	保持现有紧凑投影（字节稳定），绝不重写摘要。

	force=True（HardTop 必要性，缺口①）：绕过上述经济闸门，只保证 append-only
	与新摘要可代换旧段，强制把 cursor 前推，防止尾部增长越过窗口硬顶。
	"""
	if working.compact_cursor <= 0 or new_cursor <= working.compact_cursor:
		return False
	region = messages[working.compact_cursor:new_cursor]
	if not region:
		return False
	ext = c2_summary_extension(region, start_index=working.compact_cursor)
	if not force:
		region_chars = _region_chars(region)
		min_gain = int(getattr(params, "c2_min_gain_chars", 4000))
		ext_formula = _c2_formula_enabled("XEYO_C2_EXTEND_FORMULA")
		# Path A（XEYO_C2_EXTEND_FORMULA=1）：扩展闸同用经济公式，并允许 env 覆盖
		# margin / price_ratio / min_remain（闭环定参），不改 params 冻结常量。
		margin = float(getattr(params, "c2_extend_safety_margin", 2.0))
		price_ratio = float(getattr(params, "c2_extend_price_ratio", 30.0))
		min_remain = int(getattr(params, "c2_extend_min_remaining_turns", 5))
		if ext_formula:
			env_margin = os.environ.get("XEYO_C2_MARGIN", "").strip()
			if env_margin:
				try:
					margin = max(0.0, float(env_margin))
				except ValueError:
					pass
			env_pr = os.environ.get("XEYO_C2_PRICE_RATIO", "").strip()
			if env_pr:
				try:
					price_ratio = max(0.0, float(env_pr))
				except ValueError:
					pass
			env_remain = os.environ.get("XEYO_C2_MIN_REMAIN", "").strip()
			if env_remain:
				try:
					min_remain = max(0, int(env_remain))
				except ValueError:
					pass
		# 1) 收益：新区明显大于摘要增量（否则扩展只会增加 miss 面）
		if region_chars - len(ext) < min_gain:
			return False
		# 2) 稀发性：新区至少达到已冻结区的一半，避免频繁扩展破坏前缀
		frozen_chars = _region_chars(messages[:working.compact_cursor]) or 1
		ratio = float(getattr(params, "c2_extend_ratio", 0.5))
		if region_chars < max(min_gain, ratio * frozen_chars):
			return False
		# 3) 摊薄：剩余轮次必须够多，扩展当轮的一次性 miss 才划算
		if remaining_turns < min_remain:
			return False
		# 4) 经济门：miss 价是 hit 的约 30 倍，扩展当轮的一次性 miss 必须可被后续省 token 摊平
		#    再加 2x 安全边际：预计收益至少 2 倍于过渡成本才扩展（否则保持冻结、字节稳定）
		#    G66: token 计量统一走 memory.token.token_len(utf-8 字节/4),弃 字符/4 双口径
		#    (中文场景原先系统性低估约 3 倍)
		tail_tokens = _region_tokens(messages[new_cursor:])
		transition_miss_tok = token_len(ext) + tail_tokens
		saved_per_turn_tok = _region_tokens(region)
		if transition_miss_tok > 0 and remaining_turns * saved_per_turn_tok < margin * price_ratio * transition_miss_tok:
			return False
	old_text = working.c2_summary_text or ""
	working.c2_summary_text = (old_text.rstrip() + "\n" + ext) if old_text.strip() else ext
	working.compact_cursor = new_cursor
	working.c1_frozen_until = max(working.c1_frozen_until, new_cursor)
	working.turns_since_c2 = 0
	working.proj_cache = None
	# T8：append-only 扩展也写入 checkpoint 窗口链（锚点推进），resume 可重现窗口演进
	append_compact_window(
		working,
		cursor=working.compact_cursor,
		frozen_until=working.c1_frozen_until,
		summary_text=working.c2_summary_text,
	)
	# 与 note_c2 一致：cursor 前进后清空嵌套路径，下一枪按需再发现
	working.loaded_nested_instruction_paths = []
	return True


def _branch_x(d: Any, action: str) -> str:
	"""取该动作分支的 simulator 投影 X，作为下一轮 Ĥ 的 x_prev；取不到返回空串"""
	try:
		br = (d.branches or {}).get(action)
	except Exception:
		return ""
	if br is None:
		return ""
	try:
		return str(br.x or "")
	except Exception:
		return ""


def update_projection_digest(working: WorkingSnapshot, s0) -> None:
	"""把 s0 的冻结前缀（P = p_s + p_c）计量为 ``working.last_projection``（P1 缺失2）。

	只存可重入计量信息，**不存全文**：对 P 做 sha256、记下各段 token 长度。这样
	杀进程重启后，``decide`` 的 keep 分支仍能算 ``lcp_keep``（= frozen_len），无需
	重放整段投影。任何失败都静默（不阻塞热路径）。
	"""
	try:
		from memory.simulator.projection import emit_segment, project as sim_project
		from memory.working import ProjectionDigest

		frozen = s0.p_s + s0.p_c
		prefix_text = "".join(emit_segment(seg) for seg in frozen)
		frozen_len = sum(token_len(emit_segment(seg)) for seg in frozen)
		total_len = sim_project(s0).length
		working.last_projection = ProjectionDigest(
			prefix_hash=hashlib.sha256(prefix_text.encode("utf-8")).hexdigest(),
			total_len=int(total_len),
			frozen_len=int(frozen_len),
			tail_len=max(0, int(total_len) - int(frozen_len)),
		)
	except Exception:
		# 计量失败不阻塞热路径：保持既有 last_projection，或保守为 None（=0）
		pass


MEMORY_INDEX_HEADER = "# Memory index (background only — NOT the user request)"


def _memory_index_digest(index_text: str | None) -> str:
	"""把 MEMORY.md 原文压成一行计数摘要；无条目返回空串。

	P0（B1 一行化）：索引块只回答「有什么类型、各多少条、怎么取」，
	条目标题 / 路径一律不进投影——条目正文属于 topics/*.md，检索走 Memory 工具。
	背景：整份索引尾插在用户文本后、贴近生成点，弱模型会把条目当成任务对象
	（实测 glm-4.5-air 把「帮我修改」绑定到记忆条目上，见会话 sess_mtiche8l）。
	"""
	counts: dict[str, int] = {}
	for line in (index_text or "").splitlines():
		s = line.strip()
		if not s or s.startswith("#"):
			continue
		m = re.match(r"\[([A-Za-z_]+)\]", s)
		key = m.group(1).lower() if m else "other"
		counts[key] = counts.get(key, 0) + 1
	if not counts:
		return ""
	total = sum(counts.values())
	parts = ", ".join(
		f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
	)
	return f"Memory index: {total} entries ({parts}) · 检索: Memory(action=search)"


def _memory_index_block(index_text: str | None) -> str:
	"""组装 Memory index T_now 块（P0：B1 一行化 + C1 围栏 + C2 去条件化）。

	- C1 围栏：摘要数据包在 ``<memory_index readonly>`` 内，与 tool_output /
	  user_message 围栏同一房风（prompt/fence.py）——弱模型对「标签内=引用数据」
	  有训练级先验，比文字声明可靠。
	- C2 去条件化：不再要求模型先判断「用户是否在问记忆」（弱模型判不对），
	  改为无条件禁止 + 锚定到可观察信号（用户消息含「记忆 / memory」字样）。
	- 块头保留 ``# Memory index`` 前缀：query_loop._content_parts 的用量统计
	  与既有测试断言依赖该前缀。
	"""
	digest = _memory_index_digest(index_text)
	if not digest:
		return ""
	return (
		f"{MEMORY_INDEX_HEADER}\n"
		'<memory_index readonly="true">\n'
		f"{digest}\n"
		"</memory_index>\n"
		"本块是背景引用数据，不是用户请求：禁止就本块内容向用户提问、确认或发起任何操作。\n"
		"仅当用户消息本身明确提到「记忆 / memory」时，才调用 Memory 工具检索；否则完全忽略本块。"
	)


def memory_index_context_block() -> str:
	"""Memory 索引文案（背景上下文，不得被当成用户提问）。"""
	try:
		from memory.memdir import load_index_text, workspace_id
		from engine.workspace_context import get_cwd

		index = load_index_text(workspace_id(get_cwd()))
	except Exception:
		return ""
	return _memory_index_block(index or "")


def _append_memory_index(messages: list[dict]) -> list[dict]:
	"""把易变的 MEMORY.md 导航索引放到投影 T_now。

	system 左段不再嵌索引：任何 MemoryWrite/Forget 改索引都会让后续整个请求
	（system+对话）从改点起 miss。挂到 T_now 后索引变化只影响本轮尾部。

	末条是 tool 时由 ``append_text_blocks_to_last_user`` 投影尾插一条 user，
	不修改入参列表与既有消息对象（避免污染 query_loop 投影缓存 / JSONL）。
	"""
	if not messages:
		return messages
	block = memory_index_context_block()
	if not block:
		return messages
	from prompt.turn_context import append_text_blocks_to_last_user

	return append_text_blocks_to_last_user(messages, [block])


def _region_chars(messages: list[dict]) -> int:
	"""消息区间的字符数（近似，供 C2 收益门用）。"""
	n = 0
	for m in messages:
		c = m.get("content")
		if isinstance(c, str):
			n += len(c)
		elif isinstance(c, list):
			for b in c:
				if not isinstance(b, dict):
					continue
				txt = b.get("content") or b.get("text") or b.get("input")
				if isinstance(txt, str):
					n += len(txt)
	return n


def _region_tokens(messages: list[dict]) -> int:
	"""消息区间的 token 估参（G66: 统一 utf-8 字节/4，替代 字符/4）。"""
	n = 0
	for m in messages:
		c = m.get("content")
		if isinstance(c, str):
			n += token_len(c)
		elif isinstance(c, list):
			for b in c:
				if not isinstance(b, dict):
					continue
				txt = b.get("content") or b.get("text") or b.get("input")
				if isinstance(txt, str):
					n += token_len(txt)
	return n


def _c2_formula_enabled(key: str) -> bool:
	"""Path A 公式门（2026-09-06 固化后）：**project 模式恒 True，v61 模式恒 False**。

	- project：超长会话 C2 由 Path A 压力/收益/扩展公式裁决（原 `XEYO_C2_*_FORMULA`
	  注册表默认 1，已删键）；
	- v61：decide 每轮自主接管 C2 触发，公式不参与（恒 False，保 decide 语义）。
	- 保留 `XEYO_C2_FORMULA_OVERRIDE` 一次性注入通道（A/B 定参脚本，0/1）。
	"""
	override = os.environ.get("XEYO_C2_FORMULA_OVERRIDE", "").strip()
	if override:
		try:
			for pair in override.split(","):
				k, _, v = pair.partition(":")
				if k.strip() == key:
					return v.strip() in ("1", "true", "yes", "on")
		except Exception:
			pass
	try:
		from memory.l5_flag import use_v61

		return not use_v61()
	except Exception:
		return True


def _c2_gain_enough(messages: list[dict], working: WorkingSnapshot, new_cursor: int, params, remaining_turns: int = 8) -> bool:
	"""C2 收益门：待压缩区比摘要文本大出足够多、且压缩后投影显著小于全量才压缩。

	避免每轮重压缩破坏 KV 缓存（命中率下降）；收益不足时退回保持现有紧凑投影。
	尺寸比用区间字符统计，不再全量 project + dumps。

	Path A（XEYO_C2_GAIN_FORMULA=1）：改用成本模型经济公式——
	「剩余轮次 × 每轮省 token ≥ margin × price_ratio × 改写一次性 miss」，随
	remaining_turns 动态（不再拍固定 0.40/8000 常量）。默认关，走冻结行为。
	"""
	if _c2_formula_enabled("XEYO_C2_GAIN_FORMULA"):
		region = messages[working.compact_cursor:new_cursor]
		if not region:
			return False
		region_chars = _region_chars(region)
		names = build_tool_use_names(messages)
		summary_chars = len(working.c2_summary_text) if working.c2_summary_text else len(
			deterministic_c2_summary(region, id_to_name=names)
		)
		tail_chars = _region_chars(messages[new_cursor:])
		price_ratio, margin = _c2_price_ratio_margin(params)
		# 显式豁免下限：仍要求明显缩小（引用原 c2_min_* 作为可回退的保守默认）
		min_gain = int(getattr(params, "c2_min_gain_chars", 4000) or 0)
		min_save = float(getattr(params, "c2_min_save_ratio", 0.25) or 0.0)
		# Path A 定参：save{0.30,0.40} 映射到经济公式的 price_ratio 缩放（唯一线性敏感参数，
		# 任何场景都能扫出差异）。语义：save 越小 → 允许的过渡 miss 倍率越低 → 越容易压。
		env_save = os.environ.get("XEYO_C2_SAVE_RATIO", "").strip()
		if env_save:
			try:
				save = max(0.05, float(env_save))
				# price_ratio=30 是 DeepSeek miss/hit 价比；save 作为其缩放系数
				# （0.30 → price_ratio=9，即「需摊回 9×miss」；0.40 → 12×）。
				price_ratio = price_ratio * save
			except ValueError:
				pass
		env_margin = os.environ.get("XEYO_C2_MARGIN", "").strip()
		if env_margin:
			try:
				margin = max(0.0, float(env_margin))
			except ValueError:
				pass
		try:
			from memory.simulator.c2_gate import economic_gain_ok

			return economic_gain_ok(
				region_chars=region_chars,
				summary_chars=summary_chars,
				tail_chars=tail_chars,
				remaining_turns=int(remaining_turns),
				margin=margin,
				price_ratio=price_ratio,
				min_save_ratio=min_save,
				min_gain_chars=min_gain,
			)
		except Exception:
			pass  # 公式失败回退冻结行为（fail-closed 到保守路径）
	if not params.c2_min_gain_chars:
		return True
	region = messages[working.compact_cursor:new_cursor]
	if not region:
		return False
	left_chars = _region_chars(region)
	names = build_tool_use_names(messages)
	if working.c2_summary_text:
		summary_chars = len(working.c2_summary_text)
	else:
		summary_chars = len(deterministic_c2_summary(region, id_to_name=names))
	if left_chars - summary_chars < params.c2_min_gain_chars:
		return False
	# 尺寸比收益门：摘要+右尾 相对 全量 必须省够比例（否则尾消息体积大，压缩形同虚设）
	try:
		save_ratio = max(0.0, float(params.c2_min_save_ratio))
	except (TypeError, ValueError):
		save_ratio = 0.0
	if save_ratio <= 0:
		return True
	full_chars = _region_chars(messages)
	if full_chars <= 0:
		return True
	compact_chars = summary_chars + _region_chars(messages[new_cursor:])
	if compact_chars / full_chars > 1.0 - save_ratio:
		return False
	return True


def _c2_price_ratio_margin(params) -> tuple[float, float]:
	"""Path A 经济公式的 (price_ratio, margin)：复用 try_extend_c2 已有常量。"""
	try:
		from memory.simulator.c2_gate import price_ratio_margin

		return price_ratio_margin(params)
	except Exception:
		return 30.0, 2.0


def project_for_model(
	messages: list[dict],
	working: WorkingSnapshot,
	*,
	remaining_turns: int = 8,
	system_prompt: str | None = None,
	include_memory_index: bool = True,
	summary_provider=None,
	context_limit: int | None = None,
) -> list[dict]:
	"""按开关生成送模型投影。

	- 默认 project：字节级等于 compact.project（硬不变量），不跑 decide；
	    仅当 XEYO_C2_GATE 打开（超长会话单开）时才允许公式 C2。
	- v61：实验通道，每轮 decide（keep/C1/C2）。

	``context_limit``：**真实模型上下文窗口**（用户添加模型时必填的上下文窗口 / route capacity）。
	Path A 压力门据此推导「离硬顶留够余量才压」。**必需**：缺省 None 时压力门返回 None（窗口未知
	→ 不触发压力 C2），**绝不回退 params.window_tokens=128k**——主流模型已 1M，回退会让 C2
	误以为窗口只有 128k。
	"""
	if l5_mode() == "project":  # 2026-09-06：C2_GATE 固化恒 True（已删开关）→ 快路径只看 L5
		if aging_enabled():
			maybe_advance_aging_boundary(messages, working)
			working.last_action = "project"
			out = project_c0c1(messages, frozen_until=working.c1_frozen_until)
		else:
			working.last_action = "project"
			out = project_c0c1(messages)
		return _append_memory_index(out) if include_memory_index else out

	# T38 解耦（条件 import）：默认 project 路径（上方 return）不 import 离线 simulator，
	# 仅 v61 实验通道 / C2 gate 真正需要 decide 时才加载，且绑定为局部名。
	from memory.simulator.params import load_params
	from memory.simulator.scenarios import DEFAULT_SYSTEM, state_from_messages
	from memory.simulator.cache_model import CacheState
	from memory.simulator.decision import decide

	p = load_params()
	# r_cap 接线（原死参数）：剩余轮数估计按 params.r_cap 封顶（与 replay.estimate_remaining 一致）
	try:
		remaining_turns = min(max(1, int(remaining_turns)), int(p.r_cap))
	except (TypeError, ValueError):
		remaining_turns = max(1, remaining_turns)
	s0 = state_from_messages(
		messages,
		cursor=working.compact_cursor,
		system=system_prompt or DEFAULT_SYSTEM,
	)
	# P1 缺失2：为 keep 分支的可重入 lcp_keep 记录上一枪投影 P 的计量。
	prev_proj = getattr(working, "last_projection", None)
	prev_frozen_len = int(prev_proj.frozen_len or 0) if prev_proj is not None else 0
	update_projection_digest(working, s0)  # 刷新为当前 s0 的 P 计量（供下一枪/重启）
	# P1 缺失3：把剩余轮数降级为约束条件——按窗口使用率 + 待读文件数给 {4,8,16} 分级。
	try:
		from memory.simulator.projection import project as sim_project
		from memory.simulator.r_estimator import (
			count_unread_files,
			estimate_r_gate,
			usage_ratio_from_tokens,
		)

		cur_tokens = sim_project(s0).length
		usage_ratio = usage_ratio_from_tokens(cur_tokens, p.window_tokens)
		unread_count = count_unread_files(getattr(working, "read_file_state", {}) or {})
		# B3 证据门：窗口余量 ÷ 近期增速（≈ cur_tokens / 历史轮数）作 R_base 输入；
		# env 关闭时传 None → 静态规则（与 P1 缺失3 冻结行为逐位一致）。
		avg_turn = None
		from memory.simulator.r_estimator import _dynamic_enabled as _dyn_on

		if _dyn_on():
			n_turns = max(1, len(messages) // 2)
			avg_turn = float(cur_tokens) / float(n_turns)
		r_gate = estimate_r_gate(
			usage_ratio,
			unread_count,
			params=p,
			avg_turn_tokens=avg_turn,
			window_tokens=p.window_tokens,
			current_tokens=cur_tokens,
		)
	except Exception:
		r_gate = None
	age = idle_seconds(working)
	cache = CacheState(
		age_seconds=age,  # 距上次打模型的空闲秒数
		x_prev=working.last_x_sim,  # 上一轮真实发送的投影 X → keep 的 Ĥ 不再恒 0
		x_prev_frozen_len=prev_frozen_len,  # 上一枪冻结前缀长度 → restart 可重入 lcp_keep
		provider=p.provider,  # 计价/TTL 画像所用厂商
		model=p.model,  # 计价所用模型名
	)
	d = decide(s0, cache, remaining_turns=remaining_turns, params=p, forecast="p0", r_gate=r_gate)
	if r_gate is not None and r_gate.force_hardtop:
		# P1 缺失3 兜底：全档不可行 → 强制 HardTop（先保窗口）。当前 allow[4] 恒真，
		# 正常不触发；这里防御性接管，交给 HardTop 强制压缩保护窗口。
		working.last_action = "C2"
		note_c2(working, max(working.compact_cursor, c2_cut_index(messages, s0)))
		return apply_c2_messages(messages, working, summary_provider=summary_provider)

	# Path A（XEYO_C2_PRESSURE_FORMULA=1）：**压力门单一触发**。
	# C2 触发只由「压力门（必要）∧ 收益门（充分）」决定，**接管 decide 的 C2 分支**
	# （未达压 → keep，投影字节稳定；压后进稳定压缩态，扩展只走 try_extend_c2 稀疏触发）。
	# 这正是「减改写、提命中」：decide 每轮都可能点 C2，压力门把它收敛为
	# 「窗口压力跨过才压一次」的稀发事件。HardTop 兜底永远保留（窗口真快溢出仍强制压）。
	# 公式关（默认）时逐字节冻结，走下方 decide 原路径。
	formula_c2 = (
		_c2_formula_enabled("XEYO_C2_PRESSURE_FORMULA")
		and working.compact_cursor == 0
	)
	if formula_c2:
		try:
			from memory.simulator.projection import project as _sim_project

			cur_tokens = _sim_project(s0).length
			# 真实窗口：**必须**是传入的 model.context_limit（用户添加模型时必填的上下文窗口）。
			# 不再回退 params.window_tokens=128k（那会让 C2 误以为窗口只有 128k，主流模型已 1M）。
			win = int(context_limit) if context_limit and int(context_limit) > 0 else None
			pressure_ratio = _c2_pressure_ratio(working, p, window_override=context_limit)
			# 窗口未知（未填）→ 压力门不触发（安全：宁可不压，也不拿错窗口压）；
			# pressure_ratio 是相对真实窗口的比例（= (l_hard_send−reserve−tail)/window）。
			pressure_ok = (
				win is not None
				and pressure_ratio is not None
				and cur_tokens / max(1, win) >= pressure_ratio
			)
			new_cursor = max(working.compact_cursor, c2_cut_index(messages, s0))
			gain_ok = bool(
				new_cursor > working.compact_cursor
				and _c2_gain_enough(messages, working, new_cursor, p, remaining_turns)
			)
			working.last_x_sim = _branch_x(d, "keep")
			if pressure_ok and gain_ok:
				working.last_action = "C2"
				note_c2(working, new_cursor)
				try:
					from usage.ledger import record_c2_event

					record_c2_event(session_id=working.session_id, cursor=new_cursor)
				except Exception:
					pass
				return _append_memory_index(
					apply_c2_messages(messages, working, summary_provider=summary_provider)
				) if include_memory_index else apply_c2_messages(
					messages, working, summary_provider=summary_provider
				)
			# 未达压 / 收益不足：keep（投影字节稳定，KV 命中）
			working.last_action = "keep"
			out = project_c0c1(messages, frozen_until=working.c1_frozen_until)
			return _append_memory_index(out) if include_memory_index else out
		except Exception:
			pass  # 公式失败回退下方 decide 路径（fail-closed 到冻结行为）

	def send(action: str) -> list[dict]:
		"""把已选动作的投影记为 last_x_sim，再追加记忆索引尾部（只影响 T_now）"""
		working.last_action = action
		working.last_x_sim = _branch_x(d, action)
		if action == "C2" or working.compact_cursor > 0:
			# 已压缩态保持：后续请求继续发紧凑投影（摘要+右尾），字节稳定 → KV 命中
			out = apply_c2_messages(messages, working, summary_provider=summary_provider)
		else:
			out = project_c0c1(messages, frozen_until=working.c1_frozen_until)
		return _append_memory_index(out) if include_memory_index else out

	cooling = (not d.hardtop) and working.turns_since_c2 < p.min_middle_edit_gap

	# C2：长会话压缩（冷却或无可前进切点则退回 keep）
	if d.a_star == "C2" and not cooling:
		new_cursor = max(working.compact_cursor, c2_cut_index(messages, s0))
		if new_cursor > working.compact_cursor:
			if working.compact_cursor > 0 and working.c2_summary_text:
				# 已压缩态：append-only 扩展冻结摘要，绝不重写旧文本（KV 前缀稳定）
				# HardTop（缺口①）：必要性高于经济闸——窗口临近/越过时强制扩展，防止尾部
				# 增长越过硬顶（否则扩展被拒后降级 keep，投影溢出窗口）。
				if try_extend_c2(working, messages, new_cursor, p, remaining_turns, force=bool(d.hardtop)):
					try:
						from usage.ledger import record_c2_event

						record_c2_event(session_id=working.session_id, cursor=new_cursor)
					except Exception:
						# 监控记录失败不阻塞热路径
						pass
					try:
						from memory.instruction import clear_instruction_cache

						clear_instruction_cache()
					except Exception:
						pass
					return send("C2")
				# 收益/摊薄不足：保持现有紧凑投影（字节稳定），不破坏缓存
				return send("keep")
			if d.hardtop or _c2_gain_enough(messages, working, new_cursor, p, remaining_turns):
				try:
					from memory.agent_scope import may_touch_session_md
					from memory.session_md import maybe_update

					if may_touch_session_md(working.agent_id):
						maybe_update(working.session_id, messages, working=working)
				except ImportError:
					pass
				note_c2(working, new_cursor)  # 同时清 loaded_nested_instruction_paths
				try:
					from usage.ledger import record_c2_event

					record_c2_event(session_id=working.session_id, cursor=new_cursor)
				except Exception:
					# 监控记录失败不阻塞热路径
					pass
				try:
					from memory.instruction import clear_instruction_cache

					clear_instruction_cache()
				except Exception:
					pass
				return send("C2")

	# 可选：压缩态扩展与 θ 门解耦——已压缩后只按 append 四闸门扩展，不再等 decide 返回 C2
	# （C2Q 首压后常低于 θ，θ 门会卡死扩展、让尾部无限增长）。默认关（c2_extend_decouple=False）。
	if working.compact_cursor > 0 and p.c2_extend_decouple and d.a_star != "C2":
		new_cursor = max(working.compact_cursor, c2_cut_index(messages, s0))
		if new_cursor > working.compact_cursor and try_extend_c2(working, messages, new_cursor, p, remaining_turns):
			# try_extend_c2 已清 nested paths / proj_cache
			try:
				from usage.ledger import record_c2_event

				record_c2_event(session_id=working.session_id, cursor=new_cursor)
			except Exception:
				# 监控记录失败不阻塞热路径
				pass
			try:
				from memory.instruction import clear_instruction_cache

				clear_instruction_cache()
			except Exception:
				pass
			return send("C2")

# C1：冻结中间段（仅 v61 实验通道；project+gate 不启用公式 C1）
	if use_v61() and d.a_star == "C1" and not cooling:
		new_until = max(
			working.c1_frozen_until,
			keep_tail_cut(messages),
		)
		if new_until > working.c1_frozen_until:
			note_c1(working, new_until)
			return send("C1")

	# project+gate：C2 未触发时回到既有 C0+C1 路径；若已压缩则保持紧凑投影
	if l5_mode() == "project":
		if aging_enabled():
			maybe_advance_aging_boundary(messages, working)
		if working.compact_cursor > 0:
			working.last_action = "C2"
			out = apply_c2_messages(messages, working, summary_provider=summary_provider)
		else:
			working.last_action = "project"
			out = project_c0c1(messages, frozen_until=working.c1_frozen_until)
		return _append_memory_index(out) if include_memory_index else out

	# 日常 keep：投影只按既有冻结边界走，旧消息字节稳定
	return send("keep")


def _c2_pressure_ratio(working: WorkingSnapshot | None, params=None, window_override: int | None = None) -> float:
	"""Path A 压力门：从窗口硬顶几何推导，**窗口自适应**（不拍固定 0.62 / 0.90）。

	公式 = (l_hard_send − output_reserve − tail_budget) / window。
	- l_hard_send = window − reserve（随窗口变，替代旧的 l_max=alpha_win·window——后者在
	  窗口大时与硬顶严重错位）。
	- output_reserve：给本轮输出预留的 token（c2_output_reserve，默认 0，overlay 可设）。
	- tail_budget = 每轮均 token × 保留轮数（从真录统计，不再拍 24k）。

	``window_override``：**真实模型窗口**（用户添加模型时必填的上下文窗口 / route capacity，如 1M）。
	**必须传入**——不再回退 ``params.window_tokens``（恒 128k，会让 C2 误以为窗口只有 128k，
	主流模型已 1M）。缺省 None → 返回 None（窗口未知 → 不触发压力 C2）。

	仅 XEYO_C2_PRESSURE_FORMULA=1 时启用；否则回退冻结的 context_compact_ratio。
	可用 XEYO_C2_PRESSURE_RATIO 环境变量直接覆盖结果（闭环定参用，不改公式）。
	"""
	if not _c2_formula_enabled("XEYO_C2_PRESSURE_FORMULA"):
		return context_compact_ratio()
	# 显式 env 覆盖（A/B 定参脚本用）：优先级最高，绕过窗口校验（脚本可无窗口直接注入比值）。
	raw = os.environ.get("XEYO_C2_PRESSURE_RATIO", "").strip()
	if raw:
		try:
			v = float(raw)
			if 0.0 <= v <= 1.0:
				return v
		except ValueError:
			pass
	try:
		from memory.simulator.params import load_params as _lp

		p = params or _lp()
		from memory.simulator.c2_gate import pressure_ratio

		# 真实模型窗口：**必须**由上层传入（用户添加模型时必填的上下文窗口）。
		# 不再回退 params.window_tokens（恒 128k）——那会让 C2 误以为窗口只有 128k。
		# 无真实窗口 → 返回 None（未知），调用方按「窗口未知 → 不触发压力 C2」处理（安全）。
		win = int(window_override) if window_override and int(window_override) > 0 else None
		if win is None:
			return None
		per_turn = _c2_per_turn_tokens(working)
		rounds = _c2_retain_rounds()
		tail_budget = _c2_tail_budget_tokens(per_turn, rounds)
		# Path A 压力门（**窗口自适应**）：= (l_hard_send − output_reserve − tail_budget) / window。
		# 用 l_hard_send（随窗口变）替代 l_max，保证任何模型窗口下都「离硬顶留够输出+保尾
		# 余量才压」——切换模型/窗口大小不一致时结果不串味。output_reserve 默认 0，
		# overlay 可设（如 50000），代表「再给本轮输出预留这么多 token」。
		res = pressure_ratio(
			window=win,
			l_hard_send=int(win - getattr(p, "reserve_tokens", 2048)),
			output_reserve=int(getattr(p, "c2_output_reserve", 0) or 0),
			tail_budget=tail_budget,
		)
	except Exception:
		res = context_compact_ratio()
	return res


def _c2_per_turn_tokens(working: WorkingSnapshot | None) -> float:
	"""每轮均 token（Path A 保尾输入）。优先用投影计量，其次环境覆盖。"""
	raw = os.environ.get("XEYO_C2_PER_TURN_TOKENS", "").strip()
	if raw:
		try:
			return max(1.0, float(raw))
		except ValueError:
			pass
	try:
		from memory.simulator.projection import project as sim_project

		if working is not None:
			cur = sim_project(working)
			if cur and int(getattr(cur, "length", 0) or 0) > 0:
				# 用消息数折半估轮数（与 project_for_model 的 B3 avg_turn 口径一致）
				n = max(1, int(getattr(working, "msg_count", 0) or 0))
				return float(getattr(cur, "length", 0)) / max(1.0, n / 2.0)
	except Exception:
		pass
	return 717.0  # 基线 fallback：sess_real_200turn_c2 实测每轮均 token


def _c2_retain_rounds() -> int:
	"""保尾保留轮数：默认 3（对齐 KEEP_TAIL_TOOL_ROUNDS），可用环境覆盖。"""
	raw = os.environ.get("XEYO_C2_RETAIN_ROUNDS", "").strip()
	if raw:
		try:
			return max(1, int(raw))
		except ValueError:
			pass
	return 3


def _c2_tail_budget_tokens(per_turn: float, rounds: int) -> int:
	"""保尾 ≈ 每轮均 token × 保留轮数。A/B 网格允许直接覆盖尾预算（闭环定参）。"""
	raw = os.environ.get("XEYO_C2_TAIL_BUDGET_TOKENS", "").strip()
	if raw:
		try:
			return max(0, int(raw))
		except ValueError:
			pass
	try:
		from memory.simulator.c2_gate import tail_budget_tokens

		return tail_budget_tokens(per_turn_tokens=per_turn, retain_rounds=rounds)
	except Exception:
		return int(per_turn * rounds)


def context_compact_ratio() -> float:
	"""厂商上下文占用达到该比例时强制压缩；可用 XEYO_CONTEXT_COMPACT_RATIO 覆盖。

	默认 0.80（主动压缩阈值）：长会话在 80% 就
	压缩，避免顶到上下文窗口；短会话远低于 80%，永不触发。

	Path A（XEYO_C2_PRESSURE_FORMULA=1）：改用窗口几何推导的 (l_max − tail)/window。
	"""
	raw = os.environ.get("XEYO_CONTEXT_COMPACT_RATIO", "").strip()
	if raw:
		try:
			v = float(raw)
			if 0.5 <= v <= 0.99:
				return v
		except ValueError:
			pass
	return 0.80


def should_force_compact_on_pressure(
	*,
	prompt_tokens: int,
	context_limit: int | None,
	ratio: float | None = None,
	working: WorkingSnapshot | None = None,
	params=None,
) -> bool:
	"""上一枪（或本会话累计）prompt 已达厂商 context_limit 的 ratio 时返回 True。

	ratio 缺省：Path A 压力公式开启时按 (l_max−tail)/window 推导，否则冻结 0.80。
	"""
	limit = int(context_limit or 0)
	prompt = int(prompt_tokens or 0)
	if limit <= 0 or prompt <= 0:
		return False
	# pressure_ratio 必须用**真实窗口**（context_limit）推导，与分母 limit 同一窗口——
	# 否则 ratios 用 params.window_tokens=128k、分母用真实 1M，会不一致（C2 误判窗口）。
	# 窗口未知（_c2_pressure_ratio 返回 None）→ 不触发（宁可不压，也不拿错窗口压）。
	thr = ratio if ratio is not None else _c2_pressure_ratio(working, params, window_override=context_limit)
	if thr is None:
		return False
	return prompt >= int(limit * thr)


def maybe_force_compact_on_pressure(
	messages: list[dict],
	working: WorkingSnapshot,
	*,
	context_limit: int | None,
	prompt_tokens: int | None = None,
	remaining_turns: int = 16,
	system_prompt: str | None = None,
	summary_provider=None,
) -> bool:
	"""达压则 ``force_compact`` 并清空投影缓存；返回是否触发了压缩。"""
	tokens = (
		int(prompt_tokens)
		if prompt_tokens is not None
		else int(working.last_prompt_tokens or 0)
	)
	if not should_force_compact_on_pressure(
		prompt_tokens=tokens, context_limit=context_limit, working=working
	):
		return False
	before = int(working.compact_cursor or 0)
	force_compact(
		messages,
		working,
		remaining_turns=remaining_turns,
		system_prompt=system_prompt,
		summary_provider=summary_provider,
	)
	working.proj_cache = None
	return int(working.compact_cursor or 0) > before or bool(working.c2_summary_text)


def force_compact(
	messages: list[dict],
	working: WorkingSnapshot,
	*,
	remaining_turns: int = 16,
	system_prompt: str | None = None,
	summary_provider=None,
) -> list[dict]:
	"""手动 /compact：强制前进 cursor 并返回 C2 投影（忽略 gate/θ）。

	JSONL 不变；仅改 working sidecar 与送模型投影。
	"""
	_ = remaining_turns, system_prompt
	new_cursor = max(working.compact_cursor, c2_cut_index(messages, None))
	if new_cursor > working.compact_cursor:
		try:
			from memory.agent_scope import may_touch_session_md
			from memory.session_md import maybe_update

			if may_touch_session_md(working.agent_id):
				maybe_update(working.session_id, messages, working=working)
		except ImportError:
			pass
		if working.compact_cursor > 0 and working.c2_summary_text:
			from memory.simulator.params import load_params

			try_extend_c2(
				working, messages, new_cursor, load_params(), remaining_turns, force=True
			)
		else:
			note_c2(working, new_cursor)
		try:
			from usage.ledger import record_c2_event

			record_c2_event(session_id=working.session_id, cursor=working.compact_cursor)
		except Exception:
			pass
		working.last_action = "C2"
		return apply_c2_messages(messages, working, summary_provider=summary_provider)
	if working.compact_cursor > 0:
		working.last_action = "C2"
		return apply_c2_messages(messages, working, summary_provider=summary_provider)
	working.last_action = "project"
	return project_c0c1(messages, frozen_until=working.c1_frozen_until)
