"""LLM 调用前注入：易变上下文只挂投影 T_now，不进 system 左段。

铁律：
- 只改投影（copy-on-write），不改 MessageStore / JSONL
- 易变块只进 T_now；禁止插入 system 左段（保住 KV 前缀）
- 工具续写轮：不挂 Memory / Stale；**本轮新发现的 Nested 仍挂**
  （Continue 已声明 background），避免刚 Read 完就看不到子目录规则
- 批次1：Proposals digest 已下线推送（模型无可执行动作，拉取走 /proposals）；
  上一轮思考回顾仅工具续写轮注入（fresh-user 轮是旧任务残留）

新增易变上下文候选前，先读根目录 AGENTS.md 的「T_now 接入规范」：
判断标准、现有候选查重、contextvar / 块头 / 预算截断的既定范式都在那里。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from memory.working import WorkingSnapshot
from permissions.policy import (
	agent_mode as current_agent_mode,
	browser_preview_url,
	code_compact_enabled,
	code_mode as current_code_mode,
	output_compact_enabled,
	output_mode as current_output_mode,
	side_mode,
)
from prompt.t_now_strategy import (
	STRATEGY_ENV_CHANNEL,
	STRATEGY_PREFILL,
	format_env_notice,
	t_now_strategy,
)
from prompt.turn_context import (
	CONTINUE_AFTER_TOOLS,
	append_env_notice_pair,
	append_text_blocks_to_last_user,
	build_mode_context_blocks,
	ends_with_tool_result,
	prepend_text_blocks_to_last_user,
)

_log = logging.getLogger(__name__)

# Ask / Plan / Wrap-up 文案（与 query_loop 历史常量同源，供单测与薄封装复用）
_READONLY_MODE_BASE = (
	"你只能用只读工具查看或搜索工作区，禁止写文件、改文件、跑命令、发消息或持久化记忆。"
)

ASK_MODE_INSTRUCTIONS = (
	"# Agent mode: Ask\n"
	"你以只读助手回答用户。"
	+ _READONLY_MODE_BASE
	+ "不要写或提出实现计划。直接回答后结束。"
)

PLAN_MODE_INSTRUCTIONS = (
	"# Agent mode: Plan\n"
	"你在改代码前只产出实现计划。"
	+ _READONLY_MODE_BASE
	+ "最后调用 ExitPlanMode，附上简洁的 Markdown 实现计划。"
)

WRAP_UP_INSTRUCTIONS = (
	"# Wrap-up required\n"
	"本请求已进入收尾(预算/回合已到上限):收尾工具配额内仍可落盘/验证,"
	"但不得开始新的探索、安装或长时间任务。"
	"优先把当前已完成的成果写入其目标产物路径,然后立刻给出尽力而为的最终回答;"
	"写明已确认的事实与仍不确定或未完成之处。"
)


def _wrap_up_block_text() -> str:
	"""完整 wrap_up 指令文本 = 基础指令 + 引擎 stat 出的缺口清单(若存在)。

	缺口清单经 engine.wrap_gap 模块级发布(query_loop 在进收尾窗时写入),
	消费前即时读取;失败/为空则回落纯基础指令(不挡 wrap 主路径)。
	"""
	try:
		from engine.wrap_gap import current_gap

		gap = current_gap()
	except Exception:  # noqa: BLE001
		gap = ""
	if not gap:
		return WRAP_UP_INSTRUCTIONS
	return f"{WRAP_UP_INSTRUCTIONS}\n\n[engine] {gap}"

# ── 方案一/三b：无主语背景块统一身份标记 + 分隔符 ──
# 所有挂在「最后一条 user 内部」的系统背景块，用 [system-background] 前缀
# 声明身份，用 --- 与正文/用户意图隔开，降低模型把系统背景误判成用户指令
# 而导致的注意力漂移。只加标记与分隔，不改任何保护清单/安全边界内容。
BG_HEADER = "[system-background]"
BG_SEP = "\n---\n"


def bg_wrap(text: str) -> str:
	"""给无主语背景块包身份头 + 分隔符；空串原样返回。"""
	if not text or not text.strip():
		return text
	return f"{BG_HEADER}{BG_SEP}{text.strip()}"


# 输出精简（设置开关打开后注入 T_now；不进 system 左段，保住 KV 前缀）。
OUTPUT_COMPACT_RULES = (
	"# 输出压缩铁律（所有模式强制）\n"
	"1. 保护清单（原样保留，禁改）：代码块、路径、报错原文、API名称、CLI命令、"
	"not/no/never/only/except。\n"
	"2. 禁止：自创缩写、→箭头、新增文字、输出模式前缀。\n"
	"3. 仅删减，不改写。若删减后语义受损或引发技术歧义，立即停止压缩，输出完整原文。\n"
	"4. 非“直接回复用户”的输出（写文件/注释/commit/issue/报告），跳过压缩，输出完整原文。"
)

OUTPUT_MODE_VARIANTS: dict[str, str] = {
	"lite": (
		"句子风格：完整语法，保留冠词\n"
		"开场白：简短\n"
		"工具告知：简短意图\n"
		"过渡语：极简\n"
		"思考：精简完整推理\n"
		"回复用户：简洁完整句\n"
		"报错：精简,高危除外"
	),
	"full": (
		"句子风格：碎片短句，删冠词\n"
		"开场白：直接切入\n"
		"工具告知：核心意图\n"
		"过渡语：1-2短句\n"
		"思考：碎片推理\n"
		"回复用户：短句去冗余\n"
		"报错：精简（高危除外）\n"
		"长会话约束:\n"
		"每轮输出长度不得递增禁止随对话变冗长。"
		"若检测到单轮输出超过上一轮 120%自动截断并重写。"
	),
	"ultra": (
		"句子风格：极简碎片\n"
		"开场白：省略\n"
		"工具告知：尽量省略\n"
		"过渡语：省略\n"
		"思考：仅关键节点\n"
		"回复用户：事实裸奔\n"
		"报错：完整原文\n"
		"长会话约束:\n"
		"每轮输出长度不得递增禁止随对话变冗长。"
		"若检测到单轮输出超过上一轮 120%自动截断并重写。"
	),
}


def output_compact_block() -> str:
	"""输出精简注入块；开关关闭返回空串（T_now 不挂，历史保持干净）。"""
	if not output_compact_enabled():
		return ""
	variant = OUTPUT_MODE_VARIANTS.get(current_output_mode())
	if not variant:
		variant = OUTPUT_MODE_VARIANTS["lite"]
	return f"{OUTPUT_COMPACT_RULES}\n\n{variant}"


# 写代码精简（设置开关打开后注入 T_now；不进 system 左段）。
CODE_COMPACT_RULES = (
	"# 写代码压缩铁律（所有模式强制）\n"
	"1. 保护清单（原样保留，禁砍）：用户明确要求的功能、既有测试与接口契约、"
	"报错原文、安全边界。\n"
	"2. 禁止：未要求的抽象层、新配置、示例、文档、顺手重构、顺手加测试脚手架。\n"
	"3. 仅少写，不改需求。若少写会导致功能缺失、行为漂移或安全回退，"
	"立即停止精简，按完整需求实现。\n"
	"4. 本块只约束“写代码/改代码”。回复用户的文风走输出精简；"
	"解释、报错原文、计划正文不套本块。"
)

CODE_MODE_VARIANTS: dict[str, str] = {
	"lite": (
		"# 写代码精简：lite\n"
		"实现范围：用户所求，不扩\n"
		"复用优先：本仓库已有、标准库\n"
		"更短做法：一行点出，仍按所求交付\n"
		"抽象：不主动加\n"
		"依赖：不主动加\n"
		"diff：正常完成功能即可\n"
		"注释：只写非写不可的"
	),
	"full": (
		"# 写代码精简：full\n"
		"实现范围：仅明确要求\n"
		"复用梯子：仓库已有 → 标准库 → 成熟依赖 → 一行 → 才手写\n"
		"抽象：禁止顺手加\n"
		"依赖：禁止顺手加\n"
		"diff：最短\n"
		"注释：能省则省\n"
		"# 长任务约束\n"
		"每轮改动面不得递增，禁止顺手扩大范围。"
		"发现可删的未要求代码时优先删，而不是再包一层。"
	),
	"ultra": (
		"# 写代码精简：ultra\n"
		"实现范围：仅明确要求（不挑战已确认需求）\n"
		"复用梯子：能复用绝不新写；一行能做就一行\n"
		"抽象：禁止\n"
		"依赖：禁止（标准库除外）\n"
		"diff：能删不增\n"
		"注释：省略\n"
		"# 长任务约束\n"
		"每轮改动面不得递增，禁止顺手扩大范围。"
		"发现可删的未要求代码时优先删，而不是再包一层。"
	),
}


def code_compact_block() -> str:
	"""写代码精简注入块；开关关闭返回空串。"""
	if not code_compact_enabled():
		return ""
	variant = CODE_MODE_VARIANTS.get(current_code_mode())
	if not variant:
		variant = CODE_MODE_VARIANTS["lite"]
	return f"{CODE_COMPACT_RULES}\n\n{variant}"


def compact_block() -> str:
	"""统一压缩块（输出精简 + 写代码精简）；相关开关全关返回空串。

	③：把 output_compact 与 code_compact 合并为一个 ``compact`` 块（两者都是
	"压缩开关生效"的行为规则，拆两块冗余）。仍保留 output_compact_block/code_compact_block
	供 bench 等旧调用。任一开关开启即非空；都以空串结尾表示不注入。
	"""
	parts: list[str] = []
	if output_compact_enabled():
		variant = OUTPUT_MODE_VARIANTS.get(current_output_mode()) or OUTPUT_MODE_VARIANTS["lite"]
		parts.append(f"{OUTPUT_COMPACT_RULES}\n\n{variant}")
	if code_compact_enabled():
		variant = CODE_MODE_VARIANTS.get(current_code_mode()) or CODE_MODE_VARIANTS["lite"]
		parts.append(f"{CODE_COMPACT_RULES}\n\n{variant}")
	return "\n\n".join(p for p in parts if p)


def browser_preview_block() -> str:
	"""用户右侧预览浏览器当前 URL；空则跳过（T_now，省 token）。"""
	if side_mode():
		return ""
	url = browser_preview_url()
	if not url:
		return ""
	return (
		"# 浏览器预览（background only）\n"
		f"url: {url}\n"
		"读页面正文用 WebFetch(url=…)；非用户新提问。"
	)


def runtime_mode_snapshot_block(session_id: str) -> str:
	"""审批模式活状态快照（T_now 广播，仅易变维度，turn 首一次）。

	- #1：**只在 turn 首发一次**（``begin_permission_turn`` 复位后再发），
	  轮内不再注入 —— 避免弱模型在回合中途被新增背景块带偏而重做任务；
	  真开关（门禁）本身已即时生效，不依赖此广播。
	- 头带「（background only）」；措辞含 supersedes，明确最新覆盖此前。
	- 只改投影（copy-on-write），绝不写历史；子代理/side 上下文跳过。
	"""
	if not (session_id or "").strip():
		return ""
	try:
		from permissions.runtime_mode import (
			get_runtime_mode_store,
			runtime_mode_snapshot_text,
		)

		store = get_runtime_mode_store()
		mode = store.effective(session_id)
		if not mode:
			return ""
		if not store.mark_turn_broadcast(session_id, mode):
			return ""
		return runtime_mode_snapshot_text(mode)
	except Exception:  # noqa: BLE001
		_log.debug("runtime_mode_snapshot_block failed", exc_info=True)
		return ""


# T_now 增量硬顶（字符）；Continue 优先，Nested 预留。
T_NOW_EXTRA_BUDGET = 6_000


def pending_jobs_block() -> str:
	"""42 号：待领 job 完成通知补投块（人类下一轮开工时注入，一次性消费）。

	通知即输入的被动通道（主动通道 = 唤醒轮）。属「一次性待领信息」——
	模型看不见就永久丢失，故装配为 KLASS_DIRECTIVE（预算内不裁剪、模糊
	指代轮不静默），与 forced_wrap_up / settlement 同纪律（42 号开放 #2）。
	"""
	try:
		from permissions.policy import pending_jobs_digest

		digest = pending_jobs_digest()
	except Exception:  # noqa: BLE001
		digest = ""
	digest = (digest or "").strip()
	if not digest:
		# docker 后台 job 回退（评测 headless）：已完成未领取的 job 一次性补投
		try:
			from tools.bash_tool.bash_tool import (
				docker_bg_mark_delivered,
				docker_bg_snapshot,
			)

			done = [
				j for j in docker_bg_snapshot()
				if j.get("status") == "done" and not j.get("delivered")
			]
			if done:
				rows = "\n".join(
					f"- {j['job_id']}（exit_code={j.get('exit_code')}）："
					f"{(j.get('command') or '').strip().splitlines()[0][:100]}"
					for j in done
				)
				for j in done:
					docker_bg_mark_delivered(j["job_id"])
				return (
					"# Background jobs（background only）\n"
					"以下后台任务已完成，输出尚未领取。用 job_output(job_id=…) 收结果"
					"后继续或收尾。\n" + rows
				)
		except Exception:  # noqa: BLE001
			return ""
		return ""
	return (
		"# Background jobs（background only）\n"
		"以下后台任务在你看不到的时机完成了。这是完成通知，不是新任务；"
		"用 job_output 收结果后继续或收尾，不再相关的可 job_kill。\n"
		+ digest
	)
def budget_mirror_block(budget: Any, working: Any) -> str:
	"""禀赋①：预算镜像块——把真实预算状态与待交付项如实渲染给模型。

	数据源（全部既有字段，零新表单）：
	- BudgetTracker：turn_count/max_turns、used_usd/usd_limit、墙钟死线进度；
	- WorkingSnapshot.todos：模型自己写的计划项（pending = 待交付视图）。

	无死线 / 无数据时返回空串（正常会话零注入）。
	"""
	if budget is None:
		return ""
	parts: list[str] = []
	try:
		if budget.max_turns:
			parts.append(f"回合 {budget.turn_count}/{budget.max_turns}")
		if getattr(budget, "wall_deadline_ts", None) and getattr(budget, "wall_started_ts", None):
			total = budget.wall_deadline_ts - budget.wall_started_ts
			if total > 0:
				remain_min = max(0, int((budget.wall_deadline_ts - time.time()) / 60))
				pct = min(100, int((time.time() - budget.wall_started_ts) / total * 100))
				parts.append(f"剩余时间 ~{remain_min}m（已用 {pct}%）")
		if budget.usd_limit:
			parts.append(f"${budget.used_usd:.2f}/${budget.usd_limit:.2f}")
	except Exception:  # noqa: BLE001
		pass

	todo_lines: list[str] = []
	try:
		for t in (getattr(working, "todos", None) or []):
			if not isinstance(t, dict):
				continue
			st = str(t.get("status", ""))
			if st in ("completed", "done"):
				continue
			content = str(t.get("content") or t.get("text") or "").strip()
			if content:
				todo_lines.append(f"- [{st or 'pending'}] {content[:80]}")
	except Exception:  # noqa: BLE001
		pass

	if not parts and not todo_lines:
		return ""
	out = "# Budget mirror（background only — 事实呈现，决策归你）\n"
	if parts:
		out += " | ".join(parts) + "\n"
	if todo_lines:
		out += "未完成计划项（交付前自查）：\n" + "\n".join(todo_lines[:12]) + "\n"
	return out


NESTED_MAX_CHARS = 4_000
NESTED_RESERVE_CHARS = 2_000
# 只扫投影尾部，避免长会话每轮全历史 O(n)
READ_SCAN_TAIL = 64


@dataclass
class InjectContext:
	"""单次 model.stream 前的注入上下文。"""

	working: WorkingSnapshot | None = None
	cwd: str = ""
	approved_plan: str | None = None
	#: Approved plan 首写收敛后的指针块开关：全量正文已进历史，只留"实施中"
	#: 锚点（见 prompt.turn_context.PLAN_POINTER_BLOCK）。
	plan_pointer: bool = False
	forced_wrap_up: bool = False
	runtime_notice: str | None = None
	include_memory_index: bool = True
	#: 是否注入 Nested / Stale / Proposals（工人短上下文关）。
	#: None → 跟随 include_memory_index（兼容旧调用）。
	inject_instructions: bool | None = None
	multi_agent: bool = False
	#: 上一轮模型思考的结尾截选（OpenAI 系厂商不回传 reasoning，历史里没有；
	#: 不回填会驱使弱模型每轮从零重推同样的内容）。仅工具续写轮注入——
	#: fresh-user 轮里它是上一个任务的残留推理，注入反而造成锚定污染。
	#: 空串 = 不注入。
	previous_reasoning_tail: str = ""
	#: 当前顶层会话 id（多会话 peer 提醒）；空则跳过 peer 块。
	session_id: str = ""
	#: T14：子代理（侧链）上下文——净化清单跳过 peer/冲突/预览/repeat 等易变块。
	subagent: bool = False
	#: T9：Goal 投影块（仅 blocked / pending_complete 时由调用方给出非空文本；active 常态静默=空串不注入）。
	#: 头 `# Goal（background only）`。
	goal: str = ""
	#: T_now 声道策略（方案 A）。空串 = 跟随全局 ``t_now_strategy()``；
	#: ``env_channel`` = 全部块装进伪造 tool 对（环境声道）；
	#: ``legacy`` = 块文本尾插末条 user（原行为，回退档）。
	#: ``prefill`` 预留档在解析时回落 env_channel。
	strategy: str = ""
	#: 禀赋①：BudgetTracker（仅当调用方设置墙钟死线时用于预算镜像渲染；None = 不注入）。
	budget: Any | None = None

	def instructions_enabled(self) -> bool:
		if self.inject_instructions is None:
			return bool(self.include_memory_index)
		return bool(self.inject_instructions)


def _tool_result_is_error(msg: dict[str, Any]) -> bool:
	content = msg.get("content")
	if isinstance(content, list):
		for block in content:
			if isinstance(block, dict) and block.get("type") == "tool_result":
				if block.get("is_error"):
					return True
		return False
	if isinstance(content, str) and content.lstrip().startswith("["):
		lower = content[:80].lower()
		if "error" in lower or "failed" in lower:
			return True
	return False


def _path_from_tool_use_input(inp: object) -> str:
	if isinstance(inp, dict):
		return str(inp.get("file_path") or inp.get("path") or "").strip()
	if isinstance(inp, str) and inp.strip():
		# 偶发序列化成 JSON 字符串
		s = inp.strip()
		if "file_path" in s or s.endswith((".py", ".ts", ".tsx", ".md", ".json")):
			try:
				import json

				obj = json.loads(s)
				if isinstance(obj, dict):
					return str(obj.get("file_path") or obj.get("path") or "").strip()
			except Exception:
				pass
		if ("/" in s or "\\" in s) and not s.startswith("{"):
			return s
	return ""


def _tool_result_content_hint(msg: dict[str, Any]) -> str:
	"""从 tool_result 正文猜路径（input 丢失时的弱回退）。"""
	content = msg.get("content")
	texts: list[str] = []
	if isinstance(content, str):
		texts.append(content)
	elif isinstance(content, list):
		for block in content:
			if isinstance(block, dict):
				t = block.get("content") or block.get("text")
				if isinstance(t, str):
					texts.append(t)
	blob = "\n".join(texts)[:500]
	# 常见 Read 错误/成功头：`path/to/file.py` 或 `File: ...`
	for line in blob.splitlines()[:8]:
		line = line.strip()
		if line.lower().startswith("file:"):
			return line.split(":", 1)[1].strip().strip("'\"")
		if ("/" in line or "\\" in line) and len(line) < 260:
			# 像路径的一行
			cand = line.split()[0].strip("'\"")
			if "." in cand:
				return cand
	return ""


def _collect_successful_read_paths(
	projected: list[dict[str, Any]],
	*,
	tail: int = READ_SCAN_TAIL,
	tool_names: frozenset[str] = frozenset({"Read"}),
) -> list[str]:
	"""从投影**尾部**扫出成功工具调用的 file_path。

	T17：默认只看 Read；``tool_names`` 传 Write/Edit 等即得写触碰路径
	（写文件也可能落在嵌套 XEYO.md 附近，驱动增量发现）。
	"""
	if not projected:
		return []
	window = projected[-tail:] if tail > 0 else projected
	id_to_path: dict[str, str] = {}
	error_ids: set[str] = set()
	ok_ids: set[str] = set()
	tool_msg_by_id: dict[str, dict[str, Any]] = {}

	for msg in window:
		if not isinstance(msg, dict):
			continue
		role = msg.get("role")
		if role == "assistant":
			content = msg.get("content")
			if not isinstance(content, list):
				continue
			for block in content:
				if not isinstance(block, dict) or block.get("type") != "tool_use":
					continue
				if str(block.get("name") or "").strip() not in tool_names:
					continue
				uid = str(block.get("id") or "").strip()
				path = _path_from_tool_use_input(block.get("input"))
				if uid and path:
					id_to_path[uid] = path
				elif uid:
					# input 缺失：占位，稍后用 tool_result 弱回退
					id_to_path.setdefault(uid, "")
		elif role == "tool":
			uid = str(msg.get("tool_call_id") or "").strip()
			if not uid:
				content = msg.get("content")
				if isinstance(content, list):
					for block in content:
						if isinstance(block, dict) and block.get("type") == "tool_result":
							uid = str(block.get("tool_use_id") or "").strip()
							break
			name = str(msg.get("name") or "").strip()
			if name and name not in tool_names:
				if uid and uid not in id_to_path:
					continue
			if not uid:
				continue
			tool_msg_by_id[uid] = msg
			if _tool_result_is_error(msg):
				error_ids.add(uid)
			else:
				ok_ids.add(uid)

	paths: list[str] = []
	seen: set[str] = set()
	for uid in ok_ids:
		if uid in error_ids:
			continue
		path = (id_to_path.get(uid) or "").strip()
		if not path and uid in tool_msg_by_id:
			path = _tool_result_content_hint(tool_msg_by_id[uid])
		if not path:
			continue
		key = path.replace("\\", "/").lower()
		if key in seen:
			continue
		seen.add(key)
		paths.append(path)
	return paths


def collect_session_touched_paths(
	projected: list[dict[str, Any]],
	*,
	tail: int = READ_SCAN_TAIL,
) -> list[str]:
	"""从投影**尾部**扫出本会话触碰过的路径（Read/Write/Edit/NotebookEdit input）。

	用于"文件冲突" T_now 块：这些路径若被另一个会话树写入过，写入前先行提醒。
	"""
	if not projected:
		return []
	window = projected[-tail:] if tail > 0 else projected
	touch_names = {"Read", "Write", "Edit", "NotebookEdit"}
	paths: list[str] = []
	seen: set[str] = set()
	for msg in window:
		if not isinstance(msg, dict) or msg.get("role") != "assistant":
			continue
		content = msg.get("content")
		if not isinstance(content, list):
			continue
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_use":
				continue
			if str(block.get("name") or "").strip() not in touch_names:
				continue
			path = _path_from_tool_use_input(block.get("input"))
			key = path.replace("\\", "/").lower()
			if path and key not in seen:
				seen.add(key)
				paths.append(path)
	return paths


def file_conflict_block(cwd: str, self_id: str, paths: list[str]) -> str:
	"""T_now 块：本会话触碰过的文件被其他会话树写入 -> 前景冲突提醒；无则空串。"""
	if not (cwd or "").strip() or not (self_id or "").strip() or not paths:
		return ""
	try:
		from engine.session_presence import default_session_presence

		conflicts = default_session_presence().peer_conflict_files(
			cwd, self_id, paths
		)
	except Exception:  # noqa: BLE001
		_log.debug("file_conflict_block failed", exc_info=True)
		return ""
	if not conflicts:
		return ""
	lines = ["# 文件冲突（background only — 写入前请先重新 Read）"]
	for rel, (label, ts) in sorted(conflicts.items()):
		try:
			when = time.strftime("%H:%M", time.localtime(ts))
		except Exception:  # noqa: BLE001
			when = "不久前"
		lines.append(f"- `{rel}` 于 {when} 被会话「{label}」写入")
	lines.append("这些文件与你所见快照不同，写入/编辑前先 Read 再重放你的修改。")
	return "\n".join(lines)


def _discover_nested_from_projection(
	projected: list[dict[str, Any]],
	working: WorkingSnapshot,
	cwd: str,
) -> list[str]:
	"""按成功 Read / Write / Edit 路径发现嵌套 XEYO.md，写入 working；返回本轮新路径。"""
	if not cwd:
		return []
	try:
		from memory.instruction_maintain import note_read_path_for_nested
	except Exception:
		_log.debug("note_read_path_for_nested import failed", exc_info=True)
		return []
	new_all: list[str] = []
	# T17：读与写/编辑触碰都驱动发现（写文件也可能落在嵌套指令附近）
	touched: list[str] = []
	touched.extend(_collect_successful_read_paths(projected))
	touched.extend(
		_collect_successful_read_paths(
			projected, tool_names=frozenset({"Write", "Edit", "NotebookEdit"})
		)
	)
	for path in touched:
		try:
			new_all.extend(note_read_path_for_nested(working, path, cwd) or [])
		except Exception:
			_log.debug("note_read_path_for_nested failed path=%s", path, exc_info=True)
			continue
	return new_all


def _format_nested_block(paths: list[str], *, max_chars: int = NESTED_MAX_CHARS) -> str:
	if not paths:
		return ""
	try:
		from memory.instruction_maintain import load_nested_instruction_text

		nested = load_nested_instruction_text(paths, max_chars=max_chars)
	except Exception:
		_log.debug("load_nested_instruction_text failed", exc_info=True)
		return ""
	if not nested:
		return ""
	# background 头：弱模型勿当新提问
	old = "# Nested instructions（按需，读到该目录才加载）"
	new = "# Nested instructions（background only — 按需，读到该目录才加载）"
	if nested.lstrip().startswith("# Nested"):
		return nested.replace(old, new, 1)
	return (
		"# Nested instructions（background only — NOT the user request）\n" + nested
	)


def _nested_paths_for_touched(
	loaded: list[str], touched: list[str]
) -> list[str]:
	"""批次2：过滤出「目录包含尾窗触碰文件」的嵌套规则路径（保装配序）。

	挂载集合（loaded_nested_instruction_paths）不淘汰——滚出尾窗的目录规则
	只是本轮静默，再次触碰自动恢复注入。触碰文件在其规则目录的子树内
	（pkg/sub/x.py 恢复 pkg/XEYO.md）即算命中。
	"""
	if not loaded or not touched:
		return []
	from pathlib import Path

	touched_dirs: set[str] = set()
	for p in touched:
		if not p:
			continue
		try:
			touched_dirs.add(
				str(Path(p).parent).replace("\\", "/").rstrip("/").lower()
			)
		except Exception:  # noqa: BLE001
			continue
	out: list[str] = []
	for nested in loaded:
		if not nested:
			continue
		try:
			nd = str(Path(nested).parent).replace("\\", "/").rstrip("/").lower()
		except Exception:  # noqa: BLE001
			continue
		if any(td == nd or td.startswith(nd + "/") for td in touched_dirs):
			out.append(nested)
	return out


def _trim_blocks_to_budget(
	blocks: list[str],
	*,
	budget: int = T_NOW_EXTRA_BUDGET,
	nested_reserve: int = NESTED_RESERVE_CHARS,
) -> list[str]:
	"""硬顶截断；Continue 优先；Nested 预留配额不被 Runtime notice 挤掉。"""
	if budget <= 0 or not blocks:
		return blocks

	continue_blocks: list[str] = []
	nested_blocks: list[str] = []
	other: list[str] = []
	for raw in blocks:
		b = (raw or "").strip()
		if not b:
			continue
		if b.lstrip().startswith("# Continue"):
			continue_blocks.append(b)
		elif "Nested instructions" in b[:80] or "### nested:" in b:
			nested_blocks.append(b)
		else:
			other.append(b)

	out: list[str] = []
	used = 0

	def _take(items: list[str], limit: int) -> None:
		nonlocal used
		for b in items:
			room = limit - used
			if room <= 0:
				return
			if len(b) <= room:
				out.append(b)
				used += len(b)
			elif room >= 64:
				out.append(b[:room].rstrip() + "…")
				used = limit
				return
			else:
				return

	# 1) Continue（续跑块）
	_take(continue_blocks, budget)
	# 2) Nested 先于其它易变块（预留语义靠顺序，上限 NESTED_MAX）
	if nested_blocks:
		room = budget - used
		# nested_reserve：至少争取这么多；有余量可吃到 NESTED_MAX
		want = min(NESTED_MAX_CHARS, room)
		if want < nested_reserve and room >= nested_reserve:
			want = min(NESTED_MAX_CHARS, nested_reserve)
		_take(nested_blocks, used + want)
	# 3) 其余
	_take(other, budget)
	return out


_PLAN_DECAY_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})


def approved_plan_decays_on(name: str, is_error: bool) -> bool:
	"""批次4：Approved plan 首写收敛——首次成功写盘后计划块静默。

	计划正文在批准轮已进会话历史（紧邻实施现场）；实施一旦落笔，每枪
	重发的 ≤4k 计划块只剩冗余。query_loop 在工具结果落库后调用本判定，
	命中即清空 approved_plan（本 query 内生效；跨 submit 本就重建 None）。
	"""
	return (str(name or "").strip() in _PLAN_DECAY_TOOLS) and not is_error


# ---------------------------------------------------------------------------
# P1：F3 块性质标签（治理位——新增块必须声明类别，遗漏按 inventory 处理）
# ---------------------------------------------------------------------------
# DIRECTIVE：模型必须服从的行为指令。贴生成点（尾插），预算内绝不裁剪。
KLASS_DIRECTIVE = "directive"
# EVENT：事件驱动的必须生效通知（文件冲突 / 子代理结算 / queued notices /
# reconcile / MCP required 故障）。部分含 drain 语义——静默即永久丢失，
# 绝不门控、绝不裁剪。
KLASS_EVENT = "event"
# INVENTORY：参考数据 / 能力宣告（索引、proposals、nested 正文、浏览器预览）。
# 非任务内容：fresh-user 轮前插到用户文本之前；模糊指代轮整类静默；预算紧时先裁。
KLASS_INVENTORY = "inventory"

# F1 真硬顶：覆盖**全部**块（原 bypass 组取消）。
# directive/event 由构造处各自有界（plan ≤4k、reasoning ≤600 等），全保；
# inventory 受双闸：自身配额 与 (总预算 - 指令已用) 取小。
T_NOW_TOTAL_BUDGET = 6_000
T_NOW_INVENTORY_MAX = 2_500

# ---------------------------------------------------------------------------
# 硬准入（2026-09-04，问题#2 修复）：块登记表 + 装配点标记，机器执法。
# 规则：
#   1. run_pre_llm_inject 里每个 `tagged.append` 装配点必须带 `# block: <名>`
#      标记，且 <名> 必须在本表登记——未登记的新块，契约测试即红。
#   2. 登记数硬顶 = 当前存量（加一必须删一；显式调高 T_NOW_BLOCK_HARD_CAP
#      需在 commit message 给出预算不破的理由）。
#   3. 每条登记必须回答「为什么必须在上下文」；答不出的候选先问
#      「能不能不进上下文」（引擎能强制的，一律不给模型看）。
# 执法：tests/test_t_now_block_registry.py。
# ---------------------------------------------------------------------------
T_NOW_BLOCK_HARD_CAP = 23  # 22→23：补登 23ca693 预算镜像块（预算不破——仅死线会话渲染且受 6k 总预算闸，正常会话零字节）

T_NOW_BLOCK_REGISTRY: dict[str, dict[str, str]] = {
	"continue": {
		"klass": "directive",
		"why": "工具续写轮无此块模型把 tool_result 当终点，不回用户问题",
	},
	"mode_instructions": {
		"klass": "directive",
		"why": "Ask/Plan/批准计划是本轮行为模式合同，决定能否写盘",
	},
	"wrap_up": {
		"klass": "directive",
		"why": "收尾窗引导:配额内可落盘/验证但不得开新探索;缺口清单来自引擎 stat",
	},
	"runtime_budget": {
		"klass": "directive",
		"why": "预算透明：模型需知剩余额度以决定收敛节奏",
	},
	"budget_mirror": {
		"klass": "directive",
		"why": "死线会话每轮稳态预算/时间镜像（23ca693 禀赋①）；正常会话零注入，与 runtime_budget 瞬时通知互补",
	},
	"reasoning_tail": {
		"klass": "directive",
		"why": "续写轮延续上轮推理（GUI 设置默认关；弱模型锚定风险已评估）",
	},
	"multi_agent_hint": {
		"klass": "directive",
		"why": "多代理分解/汇总的协作合同，缺了会单干或重复汇总",
	},
	"repeat_guard": {
		"klass": "directive",
		"why": "轮内防复读提醒（引擎 clear_advice 逐轮重置）",
	},
	"nested_instructions": {
		"klass": "inventory",
		"why": "子目录规则按需加载；限窗注入，滚出尾窗静默",
	},
	"nested_change": {
		"klass": "inventory",
		"why": "嵌套规则变更墓碑 diff；确认送达后才 commit（T17）",
	},
	"stale_xeyo_md": {
		"klass": "directive",
		"why": "规则文件已过时的提醒；确认进投影才刷 stamp",
	},
	"compact": {
		"klass": "directive",
		"why": "输出/写码压缩开关生效的统一行为规则（任一开关开启即注入；③合并两块减一）",
	},
	"mcp_required_warn": {
		"klass": "event",
		"why": "required MCP server 启动失败的可见警告（fail-visible）",
	},
	"reconcile_events": {
		"klass": "event",
		"why": "工具面/技能目录变更，consume 语义——静默即永久丢失",
	},
	"peer_presence": {
		"klass": "event",
		"why": "多会话交叉活动提醒，冲突预防（drain 队列）",
	},
	"file_conflict": {
		"klass": "event",
		"why": "触碰文件被其他会话写入——静默即丢，覆盖风险",
	},
	"browser_preview": {
		"klass": "inventory",
		"why": "用户预览页 URL：读页面正文的必要指针",
	},
	"runtime_mode_snapshot": {
		"klass": "directive",
		"why": "审批模式活状态（supersedes）；真门禁在 permissions 层",
	},
	"agent_settlement": {
		"klass": "event",
		"why": "子代理结算通知，drain 语义——静默即永久丢失",
	},
	"goal": {
		"klass": "directive",
		"why": "仅 blocked/pending_complete 注入：恢复执行/完成确认的锚",
	},
	"resume_directive": {
		"klass": "event",
		"why": "续跑富化指令投影-only 送达（修订2）：落库只存用户真实文本",
	},
	"pending_jobs": {
		"klass": "directive",
		"why": "job 完成补投：一次性待领信息，模型不读则任务结果不可见",
	},
	"skill_preinvoke": {
		"klass": "directive",
		"why": "用户 /name 直呼技能的宿主确定性加载；不注入则直呼依赖模型自觉调 Skill 工具，user 只见技能的直呼即失效",
	},
}

# 块级旁路开关（消融/应急）：XEYO_T_NOW_SKIP="a,b" —— 名单内块本轮不注入。
# 消融用途见 evals/block_ablation.py；注意 event 类（drain 语义）被跳过即
# **永久丢失**（consume 已清空），消融跑分可接受，生产应急慎用。
_SKIP_ENV = "XEYO_T_NOW_SKIP"


def _skipped_blocks() -> frozenset[str]:
	raw = os.environ.get(_SKIP_ENV, "")
	return frozenset(s.strip() for s in raw.split(",") if s.strip())


def _tag_block(
	tagged: list[tuple[str, str]],
	name: str,
	block: tuple[str, str],
) -> None:
	"""装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
	if name in _skipped_blocks():
		return
	tagged.append(block)

# D1：模糊指代轮识别。仅 fresh-user 轮 + 确有上文（≥1 条 assistant）才判，
# 首轮不门控（无从指代，且首问依赖 discovery 块）。
# fail-open：误判只丢一轮参考数据；指令/事件永不受影响。
_VAGUE_ACK = {
	"好", "好的", "好吧", "好呀", "行", "可以", "嗯", "嗯嗯", "ok", "okay",
	"yes", "go", "确认", "同意", "开始吧", "就这样", "这么办", "照做",
	"继续", "接着来", "辛苦了",
}
_VAGUE_MARKERS = (
	"帮我", "麻烦", "继续", "接着", "改一下", "修改", "弄一下", "做一下",
	"处理一下", "优化一下", "重构", "那个", "这个", "刚才", "上面",
	"按你", "按刚才", "按上面", "按之前", "提交吧", "动手", "开干",
	"执行吧", "搞定", "试试", "跑一下",
)
_VAGUE_MAX_CHARS = 24
_VAGUE_CODE_MARKERS = (
	"http", "`", "/", "\\", ".py", ".ts", ".tsx", ".json", ".md", ".toml",
	"#", "def ", "class ",
)


def _last_user_text(projected: list[dict[str, Any]]) -> str:
	"""取末条 user 的首个文本块（无则空串）。"""
	last = projected[-1]
	content = last.get("content")
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		for b in content:
			if isinstance(b, dict) and b.get("type") == "text":
				return str(b.get("text") or "")
	return ""


def _is_vague_referent_turn(projected: list[dict[str, Any]]) -> bool:
	"""D1：当前 fresh-user 轮是否为「模糊指代型短追问」（如「帮我修改」）。

	命中即静默本轮全部 INVENTORY 块——事故复盘：弱模型把尾插背景内容当成
	模糊请求的对象（glm-4.5-air 把「帮我修改」绑定到 Memory index 条目）。
	带路径/代码标记的请求不算模糊（对象自明）。
	"""
	if not projected:
		return False
	last = projected[-1]
	if last.get("role") != "user" or ends_with_tool_result(projected):
		return False
	if not any(m.get("role") == "assistant" for m in projected[:-1]):
		return False
	s = _last_user_text(projected).strip()
	if not s or len(s) > _VAGUE_MAX_CHARS:
		return False
	if any(m in s for m in _VAGUE_CODE_MARKERS):
		return False
	if s in _VAGUE_ACK:
		return True
	return any(m in s for m in _VAGUE_MARKERS)


def _trim_tagged_blocks(
	tagged: list[tuple[str, str]],
	*,
	total: int = T_NOW_TOTAL_BUDGET,
	inventory_max: int = T_NOW_INVENTORY_MAX,
) -> list[tuple[str, str]]:
	"""F1：类感知预算。directive/event 全保（构造处各自有界）；inventory 按
	装配序填充 min(inventory_max, total - 指令已用) 的配额，末块超限截断（带 …）。

	与旧 ``_trim_blocks_to_budget`` 的差异：覆盖原 bypass 组（compact / mcp /
	reconcile / peer / conflict / preview / snapshot / settlements / goal），
	使 T_now 总量真正有闸；Continue / Wrap-up 属 directive 天然全保。
	"""
	kept: list[tuple[str, str]] = []
	inv: list[tuple[str, str]] = []
	used = 0
	for k, raw in tagged:
		b = (raw or "").strip()
		if not b:
			continue
		if k == KLASS_INVENTORY:
			inv.append((k, b))
		else:
			kept.append((k, b))
			used += len(b)
	room = max(0, min(inventory_max, total - used))
	for k, b in inv:
		if room <= 0:
			break
		if len(b) <= room:
			kept.append((k, b))
			room -= len(b)
		elif room >= 64:
			kept.append((k, b[:room].rstrip() + "…"))
			room = 0
		else:
			break
	return kept


def run_pre_llm_inject(
	projected: list[dict[str, Any]],
	ctx: InjectContext,
) -> list[dict[str, Any]]:
	"""在 model.stream 前把易变块挂到 T_now；不修改入参列表与既有消息对象。"""
	if not projected:
		return projected

	out = projected
	# P1/F3：所有块以 (类别, 文本) 装配；类别决定放置（A1）、门控（D1）与
	# 预算（F1）。新增块必须声明 KLASS_*，遗漏按 INVENTORY 处理（最保守）。
	tagged: list[tuple[str, str]] = []
	after_tools = ends_with_tool_result(out)

	if after_tools:
		_tag_block(tagged, "continue", (KLASS_DIRECTIVE, CONTINUE_AFTER_TOOLS))

	for blk in build_mode_context_blocks(
		mode=current_agent_mode(),
		approved_plan=ctx.approved_plan,
		ask_instructions=ASK_MODE_INSTRUCTIONS,
		plan_instructions=PLAN_MODE_INSTRUCTIONS,
		plan_pointer=ctx.plan_pointer,
	):
		_tag_block(tagged, "mode_instructions", (KLASS_DIRECTIVE, blk))
	# forced_wrap_up 的收尾指令开了就必须生效：装配进 directive（预算内绝不
	# 裁剪），trim 后再兜底强挂一次（去重）——挤掉它会让模型只看到"没有工具"
	# 却不知道要立即作答，空响应/硬停概率上升。
	if ctx.forced_wrap_up:
		_tag_block(tagged, "wrap_up", (KLASS_DIRECTIVE, _wrap_up_block_text()))
	if ctx.runtime_notice:
		_tag_block(
			tagged,
			"runtime_budget",
			(KLASS_DIRECTIVE, f"# Runtime budget notice\n{ctx.runtime_notice}"),
		)
	# 批次1：仅工具续写轮注入——fresh-user 轮里它是上一个任务的推理残留，
	# 对新任务无用，还可能把弱模型锚定回旧任务（指代污染同族）。
	if after_tools and ctx.previous_reasoning_tail.strip():
		_tag_block(
			tagged,
			"reasoning_tail",
			(
				KLASS_DIRECTIVE,
				"# 上一轮思考回顾（截选）\n"
				"你在上一轮模型调用中已经推理过，结尾如下。这是延续，不是新任务；"
				"不要逐字重复同样的推理，直接在此基础上决定下一步动作。\n"
				f"{ctx.previous_reasoning_tail.strip()}",
			)
		)
	if ctx.multi_agent:
		try:
			from tools.agent_tool.prompt import MULTI_AGENT_HINT

			_tag_block(tagged, "multi_agent_hint", (KLASS_DIRECTIVE, MULTI_AGENT_HINT.strip()))
		except Exception:
			_log.debug("MULTI_AGENT_HINT load failed", exc_info=True)

	# T6：重复调用递进提醒（background only）——query_loop 轮内状态，
	# 不进历史、不改写 ToolResult；每次 submit 由引擎 clear_advice 重置。
	# T14 净化清单：子代理上下文不继承主循环的 repeat guard。
	# 停滞监测（todo 契约执行侧）同块消费：同为 advice-only、逐 submit
	# 重置、子代理豁免——不新增注册条目、不动 T_NOW_BLOCK_HARD_CAP。
	try:
		from engine.repeat_guard import current_advice
		from engine.stagnation_watch import current_stall_advice

		rep = current_advice()
		stall = current_stall_advice()
		combined = "\n".join(x for x in (rep, stall) if x)
		if combined and not ctx.subagent:
			_tag_block(
			tagged,
			"repeat_guard",
				(KLASS_DIRECTIVE, f"# Repeat guard（background only）\n{combined}"),
			)
	except Exception:
		_log.debug("repeat advice inject failed", exc_info=True)

	pending_stale_commit_cwd: str | None = None
	pending_nested_change = False
	allow_instr = bool(
		ctx.instructions_enabled() and ctx.working is not None and (ctx.cwd or "").strip()
	)
	if allow_instr and ctx.working is not None:
		cwd = ctx.cwd.strip()
		new_paths = _discover_nested_from_projection(out, ctx.working, cwd)
		# after_tools：只挂本轮新 Nested；非 after_tools：批次2 限窗——
		# 只注入「目录包含尾窗触碰文件」的已加载规则；滚出尾窗静默，
		# 再次触碰自动恢复（挂载集合不淘汰，仅注入过滤）。
		if after_tools:
			nested_block = _format_nested_block(new_paths)
		else:
			recent_touched = _collect_successful_read_paths(out)
			recent_touched += _collect_successful_read_paths(
				out, tool_names=frozenset({"Write", "Edit", "NotebookEdit"})
			)
			nested_block = _format_nested_block(
				_nested_paths_for_touched(
					list(ctx.working.loaded_nested_instruction_paths or []),
					recent_touched,
				)
			)
		if nested_block:
			_tag_block(tagged, "nested_instructions", (KLASS_INVENTORY, nested_block))

		# T17：已加载嵌套指令的更新/移除墓碑 diff（commit 仅在块幸存后发生）
		try:
			from memory.instruction_maintain import nested_change_notice

			change = nested_change_notice(ctx.working, commit=False)
			if change:
				_tag_block(tagged, "nested_change", (KLASS_INVENTORY, change))
				pending_nested_change = True
		except Exception:
			_log.debug("nested change notice failed", exc_info=True)

		if not after_tools:
			try:
				from memory.instruction_maintain import stale_instruction_notice

				# commit=False：确认进最终 blocks 后再刷 stamp
				stale = stale_instruction_notice(cwd, commit=False)
				if stale:
					_tag_block(tagged, "stale_xeyo_md", (KLASS_DIRECTIVE, stale))
					pending_stale_commit_cwd = cwd
			except Exception:
				_log.debug("stale inject failed", exc_info=True)
		# 批次1：Proposals digest 不再推送 T_now——模型对候选晋升无可执行
		# 动作（NightShift / 人工确认），纯 ambient 噪音。拉取通道：
		# /proposals slash 命令；Memory(action=search) 结果附带候选计数行
		# （memory_tool._proposals_notice_line，批次1 同步落地）。

	# 批次3：Memory index 不再推送 T_now——事故源头块退役。能力宣告住
	# Memory 工具 description（含「依赖历史上下文/偏好先 search」指引），
	# 检索走 Memory(action=search) 拉取。include_memory_index 字段保留
	# 兼容（决定 inject_instructions 默认值）；runtime._append_memory_index
	# 仍供脚本/评测使用。生产投影层的重开走 XEYO_MEMORY_INDEX_LIVE
	# （engine/query_loop._memory_index_live_enabled，用户决策默认开），不经 T_now。

	# ---- P1/F1：原 bypass 组全部纳入装配（真硬顶，不再有无闸块）----
	# 压缩块（输出精简/写代码精简合并为一个 compact；相关开关全关时不挂，T_now 与历史保持干净）。
	_compact = compact_block()
	if _compact:
		_tag_block(tagged, "compact", (KLASS_DIRECTIVE, bg_wrap(_compact)))

	# F1：MCP required server 启动失败 → T_now 警告块（background only，带归属头）。
	if (ctx.cwd or "").strip() and not ctx.subagent:
		try:
			from extension.mcp_manager import mcp_required_warning_block

			mcp_warn = mcp_required_warning_block(ctx.cwd.strip())
			if mcp_warn:
				_tag_block(tagged, "mcp_required_warn", (KLASS_EVENT, mcp_warn))
		except Exception:
			_log.debug("mcp required warning inject failed", exc_info=True)

	# F2.5：reconcile push/pull 活页块（# 工具面变更 / # 技能目录变更）。
	# consume 语义（取走即清）→ EVENT：绝不门控、绝不裁剪；子代理不继承（T14）。
	if not ctx.subagent:
		try:
			from extension.reconcile import consume_reconcile_blocks

			for blk in consume_reconcile_blocks():
				if blk and str(blk).strip():
					_tag_block(tagged, "reconcile_events", (KLASS_EVENT, str(blk).strip()))
		except Exception:
			_log.debug("reconcile inject failed", exc_info=True)

	# 多会话 peer 提醒 + 文件冲突：事件类（notices / conflict 有 drain 与安全
	# 语义，静默即丢失）。side_mode / 无 session_id / 无交叉 → 空串。
	# T14 净化清单：子代理上下文不见 peer presence / 文件冲突 / 浏览器预览。
	if (
		(ctx.cwd or "").strip()
		and (ctx.session_id or "").strip()
		and not ctx.subagent
	):
		try:
			# 逃生门 XEYO_PEER_PRESENCE_OFF（默认关=正常注入）：仅测试 harness 用。
			# FakeModelClient 的回声语义（model/fake.py）会把本块的环境声道
			# tool_result 当回声源，回 `echoed: [system-environment]…` 污染
			# e2e 断言（2026-09-05 排查）；真实 LLM 不受影响，生产默认照常注入。
			_off = os.environ.get("XEYO_PEER_PRESENCE_OFF", "").strip().lower()
			if _off in ("1", "true", "on"):
				peer = ""
			else:
				from engine.session_presence import peer_activity_block

				peer = peer_activity_block(ctx.cwd.strip(), ctx.session_id.strip())
			if peer:
				_tag_block(tagged, "peer_presence", (KLASS_EVENT, peer))
		except Exception:
			_log.debug("peer_activity_block failed", exc_info=True)
		# 文件冲突前景提醒：本会话触碰过的文件被其他会话树写入。
		# 只列冲突路径，静默即无冲突。
		try:
			touched = collect_session_touched_paths(out)
			conflict = file_conflict_block(
				ctx.cwd.strip(), ctx.session_id.strip(), touched
			)
			if conflict:
				_tag_block(tagged, "file_conflict", (KLASS_EVENT, conflict))
		except Exception:
			_log.debug("file_conflict_block failed", exc_info=True)

	preview = browser_preview_block()
	if preview and not ctx.subagent:
		_tag_block(tagged, "browser_preview", (KLASS_INVENTORY, preview))

	# 审批模式活状态快照（supersedes）：状态类块，开了就要生效；
	# T14 净化清单：子代理上下文不继承主会话 GUI 模式广播。
	if (ctx.session_id or "").strip() and not ctx.subagent:
		try:
			mode_block = runtime_mode_snapshot_block(ctx.session_id.strip())
			if mode_block:
				_tag_block(tagged, "runtime_mode_snapshot", (KLASS_DIRECTIVE, mode_block))
		except Exception:
			_log.debug("runtime mode snapshot inject failed", exc_info=True)

	# T14：子代理结算通知（turn 边界、source-attributed）。取走即清，幂等。
	if (ctx.session_id or "").strip() and not ctx.subagent:
		try:
			from engine.agent_settlement import (
				drain_agent_settlements,
				format_settlement_block,
			)

			settle_block = format_settlement_block(
				drain_agent_settlements(ctx.session_id.strip())
			)
			if settle_block:
				_tag_block(tagged, "agent_settlement", (KLASS_EVENT, settle_block))
		except Exception:
			_log.debug("agent settlement inject failed", exc_info=True)

	# T9：Goal 块（仅 blocked / pending_complete 注入，active 常态静默）；子代理上下文不注入。
	if (ctx.goal or "").strip() and not ctx.subagent:
		_tag_block(tagged, "goal", (KLASS_DIRECTIVE, ctx.goal.strip()))

	# 修订2（设计32）：续跑富化指令（[Resume] 契约）——chat 层不再把富化长文
	# 落库成 user 消息（JSONL 只存真实用户文本），指令经 contextvar 在本轮每次
	# model 调用前送达（事件类：必须生效；T14：子代理上下文不继承）。
	if not ctx.subagent:
		try:
			from engine.resume_directive import get_resume_directive

			rd = get_resume_directive()
			if rd:
				_tag_block(
			tagged,
			"resume_directive",
					(KLASS_EVENT, f"# Resume（续跑指令 — background only）\n{rd}"),
				)
		except Exception:
			_log.debug("resume directive inject failed", exc_info=True)

	# 42 号：job 完成通知补投块（一次性待领信息，chat.py 入口已 drain）。
	jobs_block = pending_jobs_block()
	if jobs_block and not ctx.subagent:
		_tag_block(tagged, "pending_jobs", (KLASS_DIRECTIVE, jobs_block))

	# 禀赋①：预算镜像（时间感来源）——仅当调用方设置了墙钟死线时渲染
	#（评测适配器 / 带超时的会话）。数据全部来自 BudgetTracker 与 WorkingSnapshot
	# 的既有字段，如实渲染，不含指令；正常无死线会话零输出（KV 无扰）。
	# block: budget_mirror —— 稳态仪表盘（每轮）；与 runtime_budget（跨阈值瞬时
	# 通知）、R1' 墙钟收口（100% 后 grace→wrap）互补，同钟不同层。
	try:
		_b = getattr(ctx.budget, "wall_deadline_ts", None)
		if _b is not None and not ctx.subagent:
			blk = budget_mirror_block(ctx.budget, ctx.working)
			if blk:
				_tag_block(tagged, "budget_mirror", (KLASS_DIRECTIVE, blk))
	except Exception:
		_log.debug("budget mirror inject failed", exc_info=True)

	# block: skill_preinvoke —— 用户直呼技能（fresh-user 轮首行 /name 命中
	# user-invocable 技能）：宿主确定性注入渲染正文（tool-skill pre-step），
	# 替代「请用 Skill 工具…」的客户端改写赌注。命令命名空间
	# 优先（slash registry 命中即非手势）；子代理不继承；工具续写轮不重放。
	if (ctx.cwd or "").strip() and not ctx.subagent and not after_tools:
		try:
			from engine.skill_preinvoke import preinvoke_skill_block

			skill_blk = preinvoke_skill_block(ctx.cwd.strip(), _last_user_text(out))
			if skill_blk:
				_tag_block(tagged, "skill_preinvoke", (KLASS_DIRECTIVE, skill_blk))
		except Exception:
			_log.debug("skill preinvoke inject failed", exc_info=True)

	# ---- P1/D1：模糊指代轮静默全部 INVENTORY。事件/指令绝不静默：
	# notices / settlements / reconcile 有 drain 语义，静默即永久丢失。----
	if not after_tools and _is_vague_referent_turn(out):
		tagged = [(k, t) for k, t in tagged if k != KLASS_INVENTORY]

	# ---- P1/F1：类感知真硬顶 ----
	kept = _trim_tagged_blocks(tagged)

	# forced_wrap_up 兜底：万一被裁则强挂（去重，单次）；消融跳过名单同样
	# 生效（XEYO_T_NOW_SKIP 含 wrap_up 时兜底也不挂，否则消融测不到该块缺席）。
	if (
		ctx.forced_wrap_up
		and "wrap_up" not in _skipped_blocks()
		and not any(t.startswith("# Wrap-up required") for _k, t in kept)
	):
		kept.append((KLASS_DIRECTIVE, _wrap_up_block_text()))

	# stale 只有真正进入 T_now 才 commit stamp，避免「刷过但模型看不见」
	if pending_stale_commit_cwd:
		stale_survived = any(
			(b or "").lstrip().startswith("# XEYO.md 可能过时") for _k, b in kept
		)
		if stale_survived:
			try:
				from memory.instruction_maintain import refresh_instruction_stamp

				refresh_instruction_stamp(pending_stale_commit_cwd)
			except Exception:
				_log.debug("refresh_instruction_stamp failed", exc_info=True)

	# T17：嵌套变更通知真正进入 T_now 才 commit（摘墓碑 / 刷新登记哈希）
	if pending_nested_change:
		change_survived = any(
			(b or "").lstrip().startswith("# Nested instructions 变更")
			for _k, b in kept
		)
		if change_survived:
			try:
				from memory.instruction_maintain import nested_change_notice

				nested_change_notice(ctx.working, commit=True)
			except Exception:
				_log.debug("nested change commit failed", exc_info=True)

	# ---- P1/A1 分仓 / 方案A 环境声道 ----
	# env_channel：全部块装进一对仅存在于投影的伪造 tool 对尾插——
	# 用户消息原文不再被任何注入块夹持（fresh-user 轮不再需要 inventory
	# 前插分仓），说话人身份由消息结构保证。
	# legacy：fresh-user 轮 inventory/capability 前插到用户文本之前（生成点
	# 紧邻用户请求，recency 为用户服务）；directive/event 尾插贴近生成点。
	# after_tools 轮维持原尾插合同（Continue 在前）。
	strategy = (ctx.strategy or "").strip() or t_now_strategy()
	if strategy == STRATEGY_PREFILL:
		# 预留档：prefill 厂商容忍度实测通过前回落环境声道。
		strategy = STRATEGY_ENV_CHANNEL
	if strategy == STRATEGY_ENV_CHANNEL:
		env_text = format_env_notice([t for _k, t in kept])
		if env_text:
			return append_env_notice_pair(out, env_text)
		return out
	if after_tools:
		return append_text_blocks_to_last_user(out, [t for _k, t in kept])
	head = [t for k, t in kept if k == KLASS_INVENTORY]
	tail = [t for k, t in kept if k != KLASS_INVENTORY]
	if head:
		out = prepend_text_blocks_to_last_user(out, head)
	if tail:
		out = append_text_blocks_to_last_user(out, tail)
	return out


__all__ = [
	"ASK_MODE_INSTRUCTIONS",
	"PLAN_MODE_INSTRUCTIONS",
	"WRAP_UP_INSTRUCTIONS",
	"OUTPUT_COMPACT_RULES",
	"OUTPUT_MODE_VARIANTS",
	"CODE_COMPACT_RULES",
	"CODE_MODE_VARIANTS",
	"T_NOW_EXTRA_BUDGET",
	"T_NOW_TOTAL_BUDGET",
	"T_NOW_INVENTORY_MAX",
	"pending_jobs_block",
	"KLASS_DIRECTIVE",
	"KLASS_EVENT",
	"KLASS_INVENTORY",
	"NESTED_RESERVE_CHARS",
	"InjectContext",
	"run_pre_llm_inject",
	"approved_plan_decays_on",
	"output_compact_block",
	"code_compact_block",
	"compact_block",
	"browser_preview_block",
	"runtime_mode_snapshot_block",
	"collect_session_touched_paths",
	"file_conflict_block",
]
