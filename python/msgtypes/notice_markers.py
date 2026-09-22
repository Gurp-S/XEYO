"""通报包封的**词法身份**（唯一实现）。

放在 `msgtypes`（纯数据类型层，非生产根）而不是 `prompt/`：WSC 算法层
（``synaptic/``，见 ``synaptic/metrics.py::PRODUCTION_ROOTS`` 的隔离门）必须能
认出"这条 role=user 是引擎注入的通报"，又**绝不许** import 生产模块——旁路要能
整目录删掉。归属判据因此下沉成数据事实：包封标签是消息格式的一部分，不是策略。

``prompt/notice_channel`` 从这里 re-export，全站仍只有一个真相源。
"""

from __future__ import annotations

import re
from typing import Any

#: 引擎注入通报的包封标签。渲染与清理共用同一对字面量，否则认不出自己注入的东西。
#: 用 ``system-reminder`` 而不是自造词：这个字面量在公开语料里被大量模型见过，
#: 语义正是"这是系统上下文，不是用户说的话"；自造标签拿不到这份训练约定，
#: 只能靠模型从字面猜（说话人归属因此不稳）。
NOTICE_ENVELOPE_OPEN = "<system-reminder>"
NOTICE_ENVELOPE_CLOSE = "</system-reminder>"

#: 对齐 Codex ``ContextualUserFragment.content_kind()``：每条注入带**维度身份**，
#: 这样"同一维度上一版给模型看过什么"才可判定——替换旧片段、压缩后认出残留、
#: 按维度算预算，全都依赖这个 key。
NOTICE_KEY_ATTR = "key"

#: 开标签（可带 key）的解析式：``<system-reminder>`` 或 ``<system-reminder key="x">``。
OPEN_TAG_RE = re.compile(r'^<system-reminder(?:\s+key="([^"]*)")?\s*>')


def notice_open_tag(key: str = "") -> str:
	"""按维度身份拼开标签；key 为空即通用包封。"""
	k = (key or "").strip()
	if not k:
		return NOTICE_ENVELOPE_OPEN
	return f'<system-reminder {NOTICE_KEY_ATTR}="{k}">'


def notice_key_of(text: object) -> str:
	"""从包封文本里取维度 key；非通报文本或无 key → 空串。"""
	if not isinstance(text, str):
		return ""
	m = OPEN_TAG_RE.match(text.strip())
	return (m.group(1) or "").strip() if m else ""


def matches_notice_text(text: object, key: str | None = None) -> bool:
	"""对齐 Codex ``matches_text``：词法判断整段是否通报，可按维度 key 收窄。

	``key=None`` = 任意通报；``key=""`` = 只认无 key 的通用通报；
	``key="x"`` = 只认该维度。替换旧片段与压缩后清残留都靠它。
	"""
	s = (text if isinstance(text, str) else "").strip()
	if not s or not OPEN_TAG_RE.match(s):
		return False
	if not s.endswith(NOTICE_ENVELOPE_CLOSE):
		return False
	if key is None:
		return True
	return notice_key_of(s) == key.strip()


def is_notice_text(text: object) -> bool:
	"""词法判断：整段是否引擎注入的通报（任意维度）。"""
	return matches_notice_text(text)


def _flatten_content(content: object) -> str:
	"""消息正文取纯文本（str / 文本块列表 / Message.content 三态）。"""
	if isinstance(content, str):
		return content.strip()
	if isinstance(content, list):
		parts: list[str] = []
		for b in content:
			if isinstance(b, dict):
				for k in ("text", "content"):
					v = b.get(k)
					if isinstance(v, str) and v.strip():
						parts.append(v)
						break
		return "\n".join(parts).strip()
	return ""


def is_notice_message(msg: object) -> bool:
	"""这条"用户消息"其实是引擎注入的通报？（说话人归属的唯一判据）

	通报片段声道把状态块落成 **role=user** 条目，于是所有"role==user 即用户说
	的话"的下游判据（会话摘要、C2 摘要的用户子池、折叠节奏、rewind 轮锚点、
	离线重放的轮数……）会把引擎当用户。判据两级，绝不猜测：

	1. 结构化身份优先——``note_key``（Message 属性或 transcript 行字段）非空即留痕；
	2. 词法包封兜底——投影 dict 不带 note_key，只能按包封标签整段匹配。

	宿主原文里夹了片段（legacy 尾插）不算通报：那是用户消息，剥掉片段仍是它。
	"""
	if msg is None:
		return False
	if getattr(msg, "hidden", False):
		return True
	if isinstance(msg, dict):
		if str(msg.get("note_key") or "").strip():
			return True
		content: Any = msg.get("content")
	else:
		content = getattr(msg, "content", None)
	body = _flatten_content(content)
	return bool(body) and matches_notice_text(body)


__all__ = [
	"NOTICE_ENVELOPE_CLOSE",
	"NOTICE_ENVELOPE_OPEN",
	"NOTICE_KEY_ATTR",
	"OPEN_TAG_RE",
	"is_notice_message",
	"is_notice_text",
	"matches_notice_text",
	"notice_key_of",
	"notice_open_tag",
]
