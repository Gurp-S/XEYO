"""系统提示词组装。

左段顺序：Identity → env → XEYO.md → Tool policy → append。
项目结构/依赖不自动注入：人写进 XEYO.md，需要时用工具现查。
记忆行为规则已下沉到各记忆工具的 description。
MEMORY.md 索引不在左段（mutation 会弄废整段 KV 前缀），由 runtime 追加到投影 T_now 尾部。
custom_system_prompt / append_system_prompt 只允许 append，不得整段替换 default+instructions。
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from typing import Any, Sequence

from prompt.fence import FENCE_POLICY

# 单一身份入口（中文主场景；GUI / CLI / side-chat / 子 agent 前缀共用）
IDENTITY = (
	"你是 XEYO，桌面与微信场景下的编程助手。"
	"回答简洁；需要时用工具；代码用 fenced code block。"
)

# 左段只留跨工具纪律；细则在各工具短 description（schema 预算）与全文 prompt。
TOOL_POLICY = (
	"工具策略：可并行的只读工具同一回合一起调用；信息够了就停，勿重复空搜或重读已读文件。"
	"文件操作只用专用工具：找文件名→Glob（可 path/分页）、找内容→Grep（path/glob 过滤）、"
	"读→Read（offset/limit）、改→Edit、写→Write、git 只读→Git；"
	"Bash 只用于无专用工具的命令（构建/测试/安装/进程/网络），勿用 Bash cat/find/ls/rg 绕开。"
	"时刻用 getTime，勿臆造日期。TodoWrite 仅在步骤状态变化时 merge 更新，勿用相同清单刷屏。"
	"长流程用 Skill 按需加载，勿塞进 XEYO.md；项目约定写短指针，结构用工具现查。"
	"分钟级长命令用 Bash run_in_background 先领活再干别的；完成会自动通知，"
	"凭通知 job_output 收结果；终答前收掉仍相关的任务，不再重要的 job_kill，勿空转轮询。"
	"改码后 Diagnostics(path=文件)；仓库用 Git(summary)；外网需确认："
	"已知文档 URL 只 WebFetch；不知 URL 则一次 WebSearch，不够再 Fetch 最相关 1 条；勿连搜或批量 Fetch。"
	"宣布任务完成前，反问自己一遍：是否有遗漏或缺失的步骤？是否真的满足原始要求的全部条目？"
	"对照要求逐项确认，未验证过的先验证，再结束。"
	+ FENCE_POLICY
)

# 子 agent：短工人附录（勿塞整份 XEYO.md / Memory 索引）；scope 由硬门禁强制。
SUBAGENT_APPEND = (
	"你是短命子 Agent。只完成指派任务；"
	"写文件仅限任务 scope（空 scope 则只读，系统会拒写）；"
	"仓库状态用 Git 工具；Bash 仅短只读命令（echo/dir/git status/rg 等），"
	"不可解释器脚本、管道复合、后台或写盘；不要 spawn 子 Agent、不要用 Memory。"
	"信息够就立刻停：禁止空转重复 Glob/Grep/Read；"
	"结论用简洁中文要点，勿粘贴整文件，供主 Agent 汇总。"
)

# 基准评测工作契约（todo 驱动）：完成定义先行 + 先交付再深化 + 执行即验证。
# 仅 bench 最小档案注入（XEYO_BENCH_MINIMAL=1），XEYO_TODO_CONTRACT=0 关闭；
# 追加在系统提示尾部（append-only，不影响既有前缀的 KV 命中）。
BENCH_TODO_CONTRACT = (
	"# 工作契约（todo 驱动）\n"
	"接到任务后，第一个动作是用 TodoWrite 建立工作契约，清单由两类条目组成：\n"
	"- 验收项（content 以「验收:」开头，2-4 条）：任务完成的可检验标准，从任务"
	"陈述推导——交付物路径、字段/格式、命令 exit 0、指标阈值。禁止空泛表述"
	"（「完成任务」不合格；「/app/results.json 存在且含 x0/gamma/omega 三键」合格）。\n"
	"- 执行项：第一批必须构成最小端到端交付路径（朴素但完整，尽快落盘可交付"
	"成果）；深化/优化项只允许排在全部交付项之后。\n"
	"规则：\n"
	"1. 执行项标 completed 前必须有真实验证动作（跑命令或读文件核对对应验收项），"
	"并在 content 末尾附一行证据（如「(证据: exit 0)」）；验收项未全部完成不得"
	"宣称任务完成。\n"
	"2. 执行中途获知新的完成要求，立即补进验收区再继续。\n"
	"3. 保持轻量：更新只改状态与证据行，不重写未变化条目，不重复提交相同清单。\n"
	"4. 效率/性能类验收项的证据标准：预热后 ≥5 轮交替计时取中位数，与基线"
	"同条件对比；单轮计时不足以证明快慢——不达标就继续改，达不了标就如实记录。\n"
	"5. 提取/检索类验收项的证据标准：交付值必须与源文档逐字段交叉核对（重读"
	"原文比对，而非凭记忆填写），字段间不得错位。\n"
	"6. 数值/模型类验收项的证据标准：若环境存在带标签或已知答案的参照数据，"
	"先在参照数据上实测自己的输出质量（如准确率），质量不达标说明管线有误，"
	"迭代修正后再交付；不得用未经验证的管线直接产出最终数值。\n"
)


@dataclass
class SystemPromptParts:
	"""build_system 的中间结果：默认段 + 用户/系统上下文"""

	default_system_prompt: list[str] = field(default_factory=list)  # 身份与工具说明段落
	user_context: dict[str, str] = field(default_factory=dict)  # 含 instructions（XEYO.md）
	system_context: dict[str, str] = field(default_factory=dict)  # 保留字段；不再注入左段


def get_default_system_prompt_parts(
	*,
	cwd: str,
	model: str,
	tool_names: Sequence[str],
	date_iso: str | None = None,
) -> list[str]:
	"""身份 + 环境 + 工具策略。

	Date / Model 都不进左段：避免换日/换模型打爆 KV；需要时刻时用 getTime。
	``date_iso`` / ``model`` 仍保留在签名与 memo 键中（兼容调用方），但不写入正文。
	工具名清单不进左段：以 API ``tools`` schemas 为准。
	侧聊（side）模式不注入 CWD 行：侧聊不绑定工作区叙事，路径由工具按需现查。
	"""
	_ = tool_names, model, date_iso
	from permissions.policy import side_mode

	# 基准评测最小档案（XEYO_BENCH_MINIMAL=1）：文件/Skill/Agent 等工具未注册，
	# 提示词同步去除相应句段（bash-only 工作方式，与 Terminus-2 对齐），其余逐字节不变。
	policy = TOOL_POLICY
	bench_contract = False
	if os.environ.get("XEYO_BENCH_MINIMAL") == "1":
		bench_contract = os.environ.get("XEYO_TODO_CONTRACT", "").strip() != "0"
		policy = policy.replace("长流程用 Skill 按需加载，勿塞进 XEYO.md；项目约定写短指针，结构用工具现查。", "")
		policy = policy.replace(
			"文件操作只用专用工具：找文件名→Glob（可 path/分页）、找内容→Grep（path/glob 过滤）、"
			"读→Read（offset/limit）、改→Edit、写→Write、git 只读→Git；"
			"Bash 只用于无专用工具的命令（构建/测试/安装/进程/网络），勿用 Bash cat/find/ls/rg 绕开。",
			"本会话为 bash-only 环境：文件的查找/读取/编辑/写入一律用 Bash（cat/heredoc/sed/find/grep 等），"
			"写文件优先 heredoc（cat > 路径 <<'EOF'），编辑优先 python3 或 sed；产物必须写到任务要求的精确路径。",
		)

	if side_mode():
		return [
			IDENTITY,
			policy,
		]
	parts = [
		IDENTITY,
		f"CWD: {cwd}",
		policy,
	]
	if bench_contract:
		parts.append(BENCH_TODO_CONTRACT)
	return parts


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
	# 前两段固定为身份 + 环境；其余为 tool policy
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
