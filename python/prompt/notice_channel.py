"""环境通报的**唯一载体决策点**（阶段 2：把三处策略分支收敛到这里）。

为什么要有这个模块：2026-09-15 默认档切到声道 B（原生 system）时，``query_loop``
的首轮嗅探路径还**硬编码伪造 tool 对**——同一份"按策略选形态"的判断散落在
``pre_llm_inject`` / ``query_loop`` / ``first_sniff`` 三处，改一处漏一处，伪对缺陷
只修了一半。本模块是唯一出口：任何要注入环境通报的地方都调
:func:`render_notice`，不再自己 if 策略。

同时承担阶段 0（可归因）：每次真投递/被跳过都落一条 ``notice.channel`` 审计，
带解析到的档位与 ``provider:model``。此前 37402 行审计里查不到一次厂商 400 的
归因——档位是运行时学的（进程级、重启即忘），不记就永远只能猜。

包封词法身份（标签、维度 key、归属判据）定义在 :mod:`msgtypes.notice_markers`
——那里是纯数据层，WSC 算法层（``synaptic/``，被隔离门禁止 import 生产模块）
也从那里取判据；本模块只 re-export 它并负责渲染与档位归因。
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from msgtypes.notice_markers import (  # noqa: F401  （re-export：全站唯一真相在 msgtypes）
	NOTICE_ENVELOPE_CLOSE,
	NOTICE_ENVELOPE_OPEN,
	NOTICE_KEY_ATTR,
	OPEN_TAG_RE as _OPEN_TAG_RE,
	is_notice_message,
	is_notice_text,
	matches_notice_text,
	notice_key_of,
	notice_open_tag,
)
from prompt.t_now_strategy import (
	STRATEGY_ENV_CHANNEL,
	STRATEGY_NOTICE_FRAGMENT,
	STRATEGY_SKIP,
	STRATEGY_SYSTEM_CHANNEL,
	env_unsupported_key,
	format_env_notice,
	resolve_t_now_strategy,
)

#: 定义式来源声明（2026-09-08 C 口径）：只说"这是什么、从哪来、说话人是谁"，
#: 不写"按其中约束处理/请注意"类抬格或祈使文本——对待方式由模型从属性自推，
#: 兜底一律在执行层（引擎铁律 1/3）。
#:
#: 2026-09-22 措辞改向：旧写法"来源=引擎运行时"是在向模型解释**我是什么**，
#: 实测有模型据此判为"外部注入、我无法验证，故不作为事实依据"（把引擎实测当
#: 未经核实的转述）。改为陈述可核对性——路径/任务号/时间戳都是本机可验证值，
#: 仍是定义式事实，不含祈使。
NOTICE_SOURCE_LINE = (
	"[引擎实测] 本节由 XEYO 运行时在本地执行环境采集，非用户消息；"
	"其中的路径、任务号、时间戳均为本机可核对值。"
)

#: 正文里出现的闭合标签转义为惰性占位：包封内文本不得自己提前终止包封。
#: 只转义尖括号、保留标签名（写成 `[&lt;</tag>&gt;]` 会把真闭合标签原样留在里面，
#: 等于没转义——test_body_cannot_break_out_of_the_envelope 就是钉这条的）。
_NOTICE_CLOSE_ESCAPED = f"[&lt;/{NOTICE_ENVELOPE_CLOSE[1:-1]}&gt;]"

#: 对齐 Codex ``MAX_ADDITIONAL_CONTEXT_VALUE_TOKENS = 1_000`` 的中段截断。
#: 用字符预算近似（本仓无跨厂商 token 计数的无副作用入口），截断保头尾、丢中段，
#: 与 Codex 的 truncate_middle 同向：两端最可能含结论与最新状态。
NOTICE_BODY_MAX_CHARS = 4000
_NOTICE_TRUNCATED_MARK = "\n…[中段已截断]…\n"

#: 引擎当前态聚合成**一条** world_state 片段（对齐 Codex 的 world_state 段）。
#: 聚合的整段正文上限 = T_now 总预算：单条上限 4000 会把多个状态段一起吃掉，
#: 聚合反而丢信息，故这条维度单独放宽，仍由中段截断兜住总占用。
WORLD_STATE_KEY = "world_state"
WORLD_STATE_MAX_CHARS = 6000


def _body_limit(key: str) -> int:
	return (
		WORLD_STATE_MAX_CHARS
		if (key or "").strip() == WORLD_STATE_KEY
		else NOTICE_BODY_MAX_CHARS
	)


def truncate_notice_body(body: str, limit: int = NOTICE_BODY_MAX_CHARS) -> str:
	"""中段截断（保头尾、丢中段）：一条通报不得吃掉整个上下文窗口。"""
	t = body or ""
	if len(t) <= limit or limit <= len(_NOTICE_TRUNCATED_MARK) * 2:
		return t
	keep = (limit - len(_NOTICE_TRUNCATED_MARK)) // 2
	return t[:keep] + _NOTICE_TRUNCATED_MARK + t[-keep:]

_SPAN_RE = re.compile(
	r"<system-reminder(?:\s+key=\"[^\"]*\")?[\s\S]*?</system-reminder>",
	re.IGNORECASE,
)

__all__ = [
	"NOTICE_ENVELOPE_CLOSE",
	"NOTICE_ENVELOPE_OPEN",
	"NOTICE_SOURCE_LINE",
	"WORLD_STATE_KEY",
	"WORLD_STATE_MAX_CHARS",
	"append_notice_fragment",
	"matches_notice_text",
	"notice_key_of",
	"notice_open_tag",
	"truncate_notice_body",
	"is_notice_message",
	"is_notice_text",
	"notice_texts",
	"render_notice",
	"render_notices",
	"strip_notice_fragments",
	"wrap_notice",
]


def wrap_notice(body: str, key: str = "") -> str:
	"""把已渲染好的正文装进包封；正文为空/非字符串 → 返回空串（无信息即不注入）。

	幂等：入参已包封则先解包再重包，绝不套娃。只加包封与来源声明，不生成任何
	劝导文本（引擎铁律 1）。``key`` 是维度身份（对齐 Codex content_kind）。
	"""
	if not isinstance(body, str):
		return ""
	inner = truncate_notice_body(
		_unwrap_notice(body).strip(), _body_limit(key)
	)
	if not inner:
		return ""
	inner = inner.replace(NOTICE_ENVELOPE_CLOSE, _NOTICE_CLOSE_ESCAPED)
	return f"{notice_open_tag(key)}\n{NOTICE_SOURCE_LINE}\n{inner}\n{NOTICE_ENVELOPE_CLOSE}"


def strip_notice_fragments(text: str, key: str | None = None) -> str:
	"""从一段文本里剥掉注入片段，宿主原文逐字保留。

	``key`` 非 None 时只剥该维度的片段（用于"换掉旧的那条、留下别的"）。
	片段紧邻的空白分隔符算片段的一部分（包封渲染时引入的），因此"宿主 + 片段"
	剥离后回到宿主原样。未闭合的孤立开标签**不**剥离——词法上无从判断片段边界，
	删到串尾会吃掉宿主原文（宁留残片，绝不错删）。
	"""
	out = text if isinstance(text, str) else ""
	while True:
		m = _SPAN_RE.search(out)
		if not m:
			return out
		if key is not None and notice_key_of(m.group(0)) != key.strip():
			# 不是目标维度：跳过它，继续往后找（避免把别的通报误删）。
			rest = strip_notice_fragments(out[m.end():], key)
			head = out[: m.end()]
			return head if not rest else f"{head}\n{rest}"
		head = out[: m.start()].rstrip(" \t\r\n")
		tail = out[m.end():]
		out = head + tail if head else tail.lstrip(" \t\r\n")


def _unwrap_notice(text: str) -> str:
	"""包封内正文（去掉开标签与来源声明行）；非包封文本原样返回。"""
	s = text.strip()
	if not matches_notice_text(s):
		return text
	m = _OPEN_TAG_RE.match(s)
	open_len = len(m.group(0)) if m else len(NOTICE_ENVELOPE_OPEN)
	inner = s[open_len:-len(NOTICE_ENVELOPE_CLOSE)].strip()
	if inner.startswith(NOTICE_SOURCE_LINE):
		inner = inner[len(NOTICE_SOURCE_LINE):].strip()
	return inner


def append_notice_fragment(
	messages: list[dict[str, Any]],
	text: str,
	key: str = "",
) -> list[dict[str, Any]]:
	"""声道 C：以**一条 user 消息**尾插包封片段（对齐 Codex：片段自成一个 item）。

	与 ``append_system_notice`` 的差别只在角色：user 角色所有厂商都接受，因此
	厂商拒 mid-history system 时不必再降级到伪造 tool 对。与 ``legacy`` 尾插的
	差别是本片段**独立成一条消息**、不夹进用户原文，且带可词法识别的包封。

	copy-on-write：不修改入参列表与既有消息对象，绝不进 MessageStore / JSONL。
	"""
	t = (text or "").strip()
	if not messages or not t:
		return messages
	return [*messages, {"role": "user", "content": wrap_notice(t, key)}]


def _record_channel(
	*,
	session_id: str,
	turn_id: str,
	strategy: str,
	key: str,
	injected: bool,
	reason: str,
) -> None:
	"""档位归因；审计不可用绝不影响主链（fail-open）。"""
	try:
		from audit.log import default_audit_log

		default_audit_log().record(
			"notice.channel",
			session_id=session_id,
			turn_id=turn_id,
			strategy=strategy,
			provider_model=key,
			injected=bool(injected),
			reason=reason,
		)
	except Exception:  # noqa: BLE001 — 归因不得挡推理
		pass


def render_notice(
	messages: list[dict[str, Any]],
	text: str,
	*,
	strategy: str | None = None,
	dimension: str = "",
	provider: str = "",
	model: str = "",
	session_id: str = "",
	turn_id: str = "",
) -> list[dict[str, Any]]:
	"""按档位把通报装进宿主形态——**唯一的注入出口**。

	``strategy=None`` 时按 ``provider:model`` 解析（厂商能力备忘会在此生效）。
	``dimension`` 是该通报的维度身份（对齐 Codex 的 content_kind）：有了它，
	同一维度的旧片段才谈得上被认出、被替换、被单独计预算。
	未知档位一律不注入（宁缺毋滥），而不是回落到某个形态。
	"""
	pm_key = env_unsupported_key(provider, model)
	resolved = (strategy or "").strip().lower() or resolve_t_now_strategy(provider, model)
	t = (text or "").strip()
	if not messages or not t:
		return messages
	if resolved == STRATEGY_SKIP:
		_record_channel(
			session_id=session_id,
			turn_id=turn_id,
			strategy=resolved,
			key=pm_key,
			injected=False,
			reason="strategy_skip",
		)
		return messages
	if resolved == STRATEGY_ENV_CHANNEL:
		from prompt.turn_context import append_env_notice_pair

		out = append_env_notice_pair(messages, t)
	elif resolved == STRATEGY_NOTICE_FRAGMENT:
		out = append_notice_fragment(messages, t, dimension)
	elif resolved in (STRATEGY_SYSTEM_CHANNEL, "legacy_head", "legacy"):
		# legacy 档由调用方自行决定头/尾插位置；到这里只说明"要注入"，
		# 形态按 system 处理会改变 legacy 的评测语义，故显式不接。
		if resolved != STRATEGY_SYSTEM_CHANNEL:
			_record_channel(
				session_id=session_id,
				turn_id=turn_id,
				strategy=resolved,
				key=pm_key,
				injected=False,
				reason="legacy_position_managed_by_caller",
			)
			return messages
		from prompt.turn_context import append_system_notice

		out = append_system_notice(messages, t)
	else:
		_record_channel(
			session_id=session_id,
			turn_id=turn_id,
			strategy=resolved,
			key=pm_key,
			injected=False,
			reason="unknown_strategy",
		)
		return messages
	_record_channel(
		session_id=session_id,
		turn_id=turn_id,
		strategy=resolved,
		key=pm_key,
		injected=len(out) > len(messages),
		reason="",
	)
	return out


def notice_texts(messages: Iterable[Any]) -> list[str]:
	"""挑出投影里的通报正文（供测试与审计核对形态，不用于改写历史）。"""
	out: list[str] = []
	for m in messages:
		if not isinstance(m, dict):
			continue
		content = m.get("content")
		if isinstance(content, str) and is_notice_text(content):
			out.append(content)
		elif isinstance(content, list):
			for block in content:
				if isinstance(block, dict):
					text = block.get("text") or block.get("content")
					if isinstance(text, str) and is_notice_text(text):
						out.append(text)
	return out


def render_notices(
	messages: list[dict[str, Any]],
	sections: Iterable[tuple[str, str]],
	*,
	strategy: str | None = None,
	provider: str = "",
	model: str = "",
	session_id: str = "",
	turn_id: str = "",
) -> list[dict[str, Any]]:
	"""逐条投递通报：每个 ``(key, body)`` 一个片段。

	默认档 ``notice_fragment`` 的输入已经是"维度 → 正文"：当前态由
	``pre_llm_inject._aggregate_state_sections`` 先合成**一条** ``world_state``
	整段（对齐 Codex：整段重渲染，任何组件出现/消失/变化都改整段文本，撤回由差分
	完成——逐块记账表达不了"这个状态不再存在"），事件与刻意常驻的块各自一条。
	每个维度仍是独立 item：单独认出、单独替换、单独计预算。

	``system_channel`` / ``env_channel`` 是对照档，其形状被回归测试钉死（"尾部只
	新增一条"），故走单条整体投递。
	"""
	pm_key = env_unsupported_key(provider, model)
	resolved = (strategy or "").strip().lower() or resolve_t_now_strategy(provider, model)
	pairs = [
		(str(k or "").strip(), (v or "").strip())
		for k, v in (sections or [])
		if (v or "").strip()
	]
	if not messages or not pairs:
		return messages
	if resolved != STRATEGY_NOTICE_FRAGMENT:
		return render_notice(
			messages,
			format_env_notice([body for _k, body in pairs]),
			strategy=resolved,
			provider=provider,
			model=model,
			session_id=session_id,
			turn_id=turn_id,
		)
	out = messages
	for key, body in pairs:
		out = append_notice_fragment(out, body, key)
	_record_channel(
		session_id=session_id,
		turn_id=turn_id,
		strategy=resolved,
		key=pm_key,
		injected=len(out) > len(messages),
		reason=f"dimensions={len(pairs)}",
	)
	return out
