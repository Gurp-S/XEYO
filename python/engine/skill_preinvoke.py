"""技能直呼宿主注入（skill pre-invoke）。

问题：GUI/CLI 的 ``/name 任务…`` 直呼技能，旧链路是客户端改写成
``[slash:/name] 请用 Skill 工具加载技能…`` 的提示词——是否真的加载取决于模型
自觉，多一次「决定调工具」的往返，且 ``model_invocable:false`` 的技能模型侧
目录里根本没有、直呼必然落空。

本模块（旁路形态，AGENTS.md 新功能准入）：把「用户消息首个非空行以
``/name`` 开头且命中 **user_invocable** 技能」识别为确定性加载手势，渲染
SKILL.md 正文交由 T_now 管线注入本轮上下文。约束：

- **命令命名空间优先**：``name`` 命中 slash registry（含别名）→ 不是技能手势，
  交给既有 slash 分发，本模块返回 None（决不与命令撞名）；
- 只有 **user** 消息可触发手势（投影末条 user 文本），``user_invocable:false``
  的技能不注入（模型侧目录照常由 Skill 工具负责）；
- 查不到的名字保持普通散文（绝不报错、绝不拦截）；
- ``$ARGUMENTS`` 语义与 ``tools/skill_tool._apply_args`` 一致：首行
  token 之后的剩余文本作为调用参数（替换占位或追加「## 调用参数」节）。

开关：环境变量 ``XEYO_SKILL_PREINVOKE``（默认开；``0/off/false`` 关——
消融/应急回退到客户端改写链路）。注入经 ``prompt.pre_llm_inject`` 的
``skill_preinvoke`` 登记块（T_now 环境声道），不进 MessageStore/JSONL、
不碰 tools 数组、不进 system prompt。
"""

from __future__ import annotations

import os
import re

#: 正文截断阈值（与 tools/skill_tool.BODY_MAX 对齐）。
BODY_MAX = 12_000

_FLAG_ENV = "XEYO_SKILL_PREINVOKE"
_FALSE = frozenset({"0", "off", "false", "no", "关"})


def preinvoke_enabled() -> bool:
	raw = (os.environ.get(_FLAG_ENV) or "").strip().lower()
	return raw not in _FALSE


def _leading_slash_token(text: str) -> tuple[str, str] | None:
	"""首个非空行若以 ``/token`` 开头（前无空白粘滞），返回 (token, 剩余文本)。

	词边界与 GUI ``slashTokenAt`` / 技能语法一致：``/`` 前是行首；
	``https://…``、``src/foo`` 不命中（``/`` 不在行首）。
	"""
	for raw_line in (text or "").splitlines():
		line = raw_line.strip()
		if not line:
			continue
		# token 必须止于空白或行尾：/nfs-hg/xxx 这类路径不命中
		# （/name 后跟 / 说明是路径，不是手势）。
		m = re.match(r"^/([^\s/]+)(?:\s+(.*))?$", line)
		if m is None:
			return None
		rest = (m.group(2) or "").strip()
		# 同行 token 之后的文本 + 后续所有行都是任务材料。
		after = rest
		if after:
			return m.group(1), after
		lines = (text or "").splitlines()
		idx = next(i for i, l in enumerate(lines) if l.strip() == line)
		return m.group(1), "\n".join(lines[idx + 1 :]).strip()
	return None


def _is_slash_command_name(name: str) -> bool:
	"""命令命名空间优先：命中 slash registry（name/别名）即非技能手势。"""
	try:
		from slash.registry import _ALIAS_INDEX

		return name.lower() in _ALIAS_INDEX
	except Exception:  # noqa: BLE001
		return False


def _apply_arguments(body: str, args: str) -> str:
	"""与 ``tools/skill_tool._apply_args`` 的字符串分支同语义。"""
	if not args:
		return body
	if "$ARGUMENTS" in body:
		return body.replace("$ARGUMENTS", args)
	return f"{body}\n\n## 调用参数\n{args}"


def preinvoke_skill_block(cwd: str, user_text: str) -> str:
	"""识别 ``/name`` 直呼手势，返回 T_now 块文本；非手势返回空串。

	失败一律空串（宁可退回旧「请用 Skill 工具」链路，不让直呼路径报错）。
	"""
	if not preinvoke_enabled():
		return ""
	parsed = _leading_slash_token(user_text or "")
	if parsed is None:
		return ""
	name, args = parsed
	if not name or _is_slash_command_name(name):
		return ""
	try:
		from tools.skill_tool.skill_tool import _entry, _skill_entries_with_descriptions

		entries = _skill_entries_with_descriptions(cwd)
		entry = _entry(entries, name)
		if entry is None or entry.broken or not entry.user_invocable:
			return ""
		body = (entry.path / "SKILL.md").read_text(encoding="utf-8")
	except Exception:  # noqa: BLE001
		return ""
	body = _apply_arguments(body.strip(), args)
	if len(body) > BODY_MAX:
		body = body[:BODY_MAX].rstrip() + "\n\n…（技能正文过长已截断；完整内容在 "
		f"{entry.path / 'SKILL.md'}，Read 可读。）"
	return (
		"# Skill invocation（用户直呼技能 — background only）\n"
		f"用户在本轮消息里以 /{entry.name} 直接调用了技能「{entry.name}」。"
		"以下是其 SKILL.md 全文（调用 Skill 工具返回的也是该内容）。\n\n"
		"<skill_content>\n"
		f"{body}\n"
		"</skill_content>"
	)


__all__ = [
	"preinvoke_enabled",
	"preinvoke_skill_block",
]
