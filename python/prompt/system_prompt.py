"""系统提示词组装。

左段顺序：Identity → env → FENCE → XEYO.md → append。
项目结构/依赖不自动注入：人写进 XEYO.md，需要时用工具现查。
记忆行为规则已下沉到各记忆工具的 description。
MEMORY.md 索引不在左段（mutation 会弄废整段 KV 前缀），由 runtime 追加到投影 T_now 尾部。
custom_system_prompt / append_system_prompt 只允许 append，不得整段替换 default+instructions。

理念红线（2026-09-08 用户裁决）：引擎不向模型注意力注入任何纪律/建议/劝导
文本——行为约束一律由执行层（权限/路由/工具门）静默强制。左段只保留身份、
环境事实与安全围栏声明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from prompt.fence import FENCE_POLICY

# 单一身份入口（中文主场景；GUI / CLI / side-chat / 子 agent 前缀共用）。
# 裁决 2：身份句不含行为要求（"回答简洁/需要时用工具"已删）。
IDENTITY = (
	"你是 XEYO，桌面与微信场景下的编程助手。"
)


@dataclass
class SystemPromptParts:
	"""build_system 的中间结果：默认段 + 用户/系统上下文"""

	default_system_prompt: list[str] = field(default_factory=list)  # 身份与工具说明段落
	user_context: dict[str, str] = field(default_factory=dict)  # 含 instructions（XEYO.md）
	system_context: dict[str, str] = field(default_factory=dict)  # 保留字段；不再注入左段


def _display_cwd(cwd: str) -> str:
	"""模型可见的工作目录：容器路由下显示**容器内**的 pwd（2026-09-16）。

	为什么必须改：Bash 经容器路由在容器里执行，而左段此前一律报宿主 ``cwd``
	（评测里是适配器建的空 scratch 目录）。模型得到一个"工作目录"，在那里既
	找不到题面文件、也写不出产物——它会先怀疑路径、再怀疑自己，白烧轮次。

	KV 前缀稳定性：容器 pwd 在会话内固定 ⇒ 左段逐字节稳定，不破坏前缀缓存
	（左段只在会话起点组装一次，见 ``prompt/assembler.py``）。

	口径单一来源：与各工具错误文案共用 ``tools.container_fs.display_cwd``，
	避免"提示词说 /app、错误说 D:\\..."的自相矛盾。
	"""
	try:
		from tools.container_fs import display_cwd

		return display_cwd(cwd)
	except Exception:  # noqa: BLE001 — 探测失败绝不挡系统提示词组装
		return cwd


def get_default_system_prompt_parts(
	*,
	cwd: str,
	model: str,
	tool_names: Sequence[str],
	date_iso: str | None = None,
) -> list[str]:
	"""身份 + 环境 + 安全围栏。

	Date / Model 都不进左段：避免换日/换模型打爆 KV；需要时刻时用 getTime。
	``date_iso`` / ``model`` 仍保留在签名与 memo 键中（兼容调用方），但不写入正文。
	工具名清单不进左段：以 API ``tools`` schemas 为准。
	侧聊（side）模式不注入 CWD 行：侧聊不绑定工作区叙事，路径由工具按需现查。

	TOOL_POLICY / SUBAGENT_APPEND 已删（2026-09-08 理念裁决 A1/A2）：
	行为约束由执行层（权限/路由/工具门）静默强制，不再写进注意力。
	左段 defaults = [identity, env, FENCE_POLICY]。
	"""
	_ = tool_names, model, date_iso
	from permissions.policy import side_mode

	# XEYO_BENCH_MINIMAL 不再改写左段文本（原 TOOL_POLICY 替换段已随 A1 删除；
	# bench 最小化只由工具注册面控制）。
	if side_mode():
		return [
			IDENTITY,
			FENCE_POLICY,
		]
	return [
		IDENTITY,
		f"CWD: {_display_cwd(cwd)}",
		FENCE_POLICY,
	]


def get_user_context(*, cwd: str) -> dict[str, str]:
	"""用户侧上下文；instructions 由 fetch 填 XEYO.md。"""
	return {
		"cwd": cwd,
	}


def get_system_context() -> dict[str, str]:
	"""保留 API；组装时不再注入 OS 等字段（避免无用字节）。"""
	return {}


def _load_instructions(cwd: str) -> str:
	"""读取 L1 XEYO.md 族；失败则空串。"""
	try:
		from memory.instruction import load_instruction_text

		return load_instruction_text(cwd, cwd)
	except Exception:
		return ""


async def fetch_system_prompt_parts(
	*,
	cwd: str,
	model: str,
	tool_names: Sequence[str],
	custom_system_prompt: str | None = None,
	date_iso: str | None = None,
) -> SystemPromptParts:
	"""拉取 default / user_context；custom 只允许后续 append，不得整段替换 default+instructions"""
	_ = custom_system_prompt
	from permissions.policy import side_mode

	if side_mode():
		# 侧聊：跳过 XEYO.md 维护与 instructions 注入——不读也不写工作区约定文件。
		return SystemPromptParts(
			default_system_prompt=get_default_system_prompt_parts(
				cwd=cwd,
				model=model,
				tool_names=tool_names,
				date_iso=date_iso,
			),
			user_context={},
			system_context=get_system_context(),
		)
	user_ctx = get_user_context(cwd=cwd)
	user_ctx["instructions"] = _load_instructions(cwd)
	return SystemPromptParts(
		default_system_prompt=get_default_system_prompt_parts(
			cwd=cwd,
			model=model,
			tool_names=tool_names,
			date_iso=date_iso,
		),
		user_context=user_ctx,
		system_context=get_system_context(),
	)


def assemble_system_prompt_parts(
	parts: SystemPromptParts,
	*,
	custom_system_prompt: str | None = None,
	append_system_prompt: str | None = None,
	include_context_blocks: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
	"""按锁死顺序拼 system 左段，并返回每段对应的上下文构成（供用量条分类）。

	顺序：Identity → env → XEYO.md → tool policy → custom → append。
	defaults 约定：[identity, env, tool_policy]。
	"""
	defaults = [s.strip() for s in parts.default_system_prompt if s and s.strip()]
	# 前两段固定为身份 + 环境；其余为安全围栏（FENCE_POLICY）
	identity_env = defaults[:2]
	rest = defaults[2:]
	chunks: list[str] = []
	breakdown: list[dict[str, Any]] = []

	def add(text: str, category: str, label: str) -> None:
		if not text:
			return
		chunks.append(text)
		breakdown.append({"category": category, "label": label, "chars": len(text)})

	for t in identity_env:
		add(t, "system", "System prompt")

	instr = ""
	if parts.user_context:
		instr = str(parts.user_context.get("instructions") or "").strip()
	if include_context_blocks and instr:
		add("# Instructions (XEYO.md)\n" + instr, "rules", "Rules")
		try:
			from memory.instruction_maintain import soft_instruction_budget

			soft = soft_instruction_budget()
			if len(instr) >= soft:
				breakdown[-1]["soft_over"] = True
				breakdown[-1]["chars_raw"] = len(instr)
		except Exception:
			pass

	for t in rest:
		add(t, "system", "System prompt")

	# custom 与 append 合并去重：相同内容只保留一次；剥掉误拼的第二段身份
	extras: list[str] = []
	for blob in (custom_system_prompt, append_system_prompt):
		s = (blob or "").strip()
		if s.startswith(IDENTITY):
			s = s[len(IDENTITY) :].lstrip("\n").strip()
		if s and s not in extras:
			extras.append(s)
	for s in extras:
		add(s, "system", "System prompt")

	return "\n\n".join(chunks), breakdown


def assemble_system_prompt(
	parts: SystemPromptParts,
	*,
	custom_system_prompt: str | None = None,
	append_system_prompt: str | None = None,
	include_context_blocks: bool = True,
) -> str:
	"""按锁死顺序拼 system 左段。MEMORY.md 索引不在左段，由 runtime 追加到投影 T_now 尾部"""
	text, _breakdown = assemble_system_prompt_parts(
		parts,
		custom_system_prompt=custom_system_prompt,
		append_system_prompt=append_system_prompt,
		include_context_blocks=include_context_blocks,
	)
	return text


def tool_names_from_registry(tools: Any) -> list[str]:
	"""从 ToolRegistry 或带 schemas() 的对象取出工具名。"""
	if tools is None:
		return []
	if hasattr(tools, "schemas"):
		return [str(s.get("name", "")) for s in tools.schemas() if s.get("name")]
	if hasattr(tools, "_tools"):
		return list(getattr(tools, "_tools").keys())
	return []
