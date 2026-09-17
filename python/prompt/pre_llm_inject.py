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
from threading import Lock
from typing import Any

from memory.working import WorkingSnapshot
from prompt import inject_store
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
	STRATEGY_SKIP,
	STRATEGY_SYSTEM_CHANNEL,
	format_env_notice,
	t_now_strategy,
)
from prompt.turn_context import (
	CONTINUE_AFTER_TOOLS,
	append_env_notice_pair,
	append_system_notice,
	append_text_blocks_to_last_user,
	build_mode_context_blocks,
	ends_with_tool_result,
	prepend_text_blocks_to_last_user,
)

_log = logging.getLogger(__name__)

# provider 结构类 4xx 回退期间的事件暂存。
# 事件源采用 drain 语义：装配读取即清空，不能在回退重装时再次从源头读取。
# 这里保存已经取出的（登记名, 正文）投影材料；请求收到首个响应 chunk 后由
# query_loop 确认清除。空响应/结构错误则保留到下一次可送达的采样。
_prepared_event_lock = Lock()
_prepared_event_blocks: dict[str, list[tuple[str, str]]] = {}
_MAX_PREPARED_EVENT_SESSIONS = 64

# Ask / Plan / Wrap-up 文案（与 query_loop 历史常量同源，供单测与薄封装复用）
ASK_MODE_INSTRUCTIONS = (
	"# Agent mode: Ask\n"
	"当前 agent mode=ask；工具可用性与执行结果由权限层决定。"
)

PLAN_MODE_INSTRUCTIONS = (
	"# Agent mode: Plan\n"
	"当前 agent mode=plan；工具可用性与计划状态由权限层和回合状态决定。"
)

# ── 已撤文本（2026-09-15，用户裁定）：``# Wrap-up(预算已尽)`` ──
# 渲染器 ``_wrap_up_block_text`` 与常量 ``WRAP_UP_INSTRUCTIONS`` 连同装配点
# 一并删除（不是注释掉）：保留一个"预算已尽"文本生成器等于给它留了重新接线
# 的口子。撤块理由见下方 run_pre_llm_inject 的「已撤块」说明。

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


def acknowledge_prepared_events(session_id: str) -> None:
	"""确认当前会话最近一次已装配的事件已被 provider 接收。"""
	sid = (session_id or "").strip()
	if not sid:
		return
	with _prepared_event_lock:
		_prepared_event_blocks.pop(sid, None)


def _prepared_events_for(session_id: str) -> list[tuple[str, str]]:
	sid = (session_id or "").strip()
	if not sid:
		return []
	with _prepared_event_lock:
		return list(_prepared_event_blocks.get(sid, ()))


def _remember_prepared_events(
	session_id: str,
	events: list[tuple[str, str]],
) -> None:
	sid = (session_id or "").strip()
	if not sid or not events:
		return
	with _prepared_event_lock:
		if sid not in _prepared_event_blocks and len(_prepared_event_blocks) >= _MAX_PREPARED_EVENT_SESSIONS:
			_oldest = next(iter(_prepared_event_blocks), None)
			if _oldest is not None:
				_prepared_event_blocks.pop(_oldest, None)
		_prepared_event_blocks[sid] = list(events)


# 输出精简状态（设置开关打开后注入 T_now；不进 system 左段，保住 KV 前缀）。
OUTPUT_COMPACT_RULES = (
	"# 输出精简状态\n"
	"output_compact=enabled；保护对象=代码块/路径/报错原文/API名称/CLI命令；"
	"非直接回复用户的产物=完整文本。"
)

OUTPUT_MODE_VARIANTS: dict[str, str] = {
	"lite": (
		"# 输出模式\n"
		"mode=lite"
	),
	"full": (
		"# 输出模式\n"
		"mode=full"
	),
	"ultra": (
		"# 输出模式\n"
		"mode=ultra"
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


# 写代码精简状态（设置开关打开后注入 T_now；不进 system 左段）。
CODE_COMPACT_RULES = (
	"# 写代码精简状态\n"
	"code_compact=enabled；保护对象=用户明确功能/既有测试与接口契约/报错原文/安全边界；"
	"适用范围=写代码/改代码。"
)

CODE_MODE_VARIANTS: dict[str, str] = {
	"lite": (
		"# 写代码模式\n"
		"mode=lite"
	),
	"full": (
		"# 写代码模式\n"
		"mode=full"
	),
	"ultra": (
		"# 写代码模式\n"
		"mode=ultra"
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
	# 只报 URL。曾带「WebFetch 可以读页面正文；非用户新提问」——前者是动作提议
	# （替模型判断"这页值得读"），后者与块头 background only 重复（2026-09-09）。
	return (
		"# 浏览器预览（background only）\n"
		f"url: {url}"
	)


# 已撤块 runtime_mode_snapshot（2026-09-15 用户裁定）：登记表 why 自陈
# 「真门禁在 permissions 层」——删掉它模型能做的事一点不变，变的只是
# 模型"知道自己被看着"。按铁律 3「限制只在执行层」+ 铁律 4「能静默就不
# 说话」，审批模式状态由 GUI 呈现给用户，不占模型注意力。

# T_now 增量硬顶（字符）；Continue 优先，Nested 预留。
T_NOW_EXTRA_BUDGET = 6_000


def pending_jobs_block() -> str:
	"""42 号：待领 job 完成通知补投块（人类下一轮开工时注入，一次性消费）。

	通知即输入的被动通道（主动通道 = 唤醒轮）。属「一次性待领信息」——
	模型看不见就永久丢失，故装配为管道 3 事件类（预算内不裁剪、不去重）；
	与 reconcile / settlement 同纪律（42 号开放 #2）。
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
					"以下后台任务已完成，输出尚未领取。"
					"job_output(job_id=…) 可收取输出。\n" + rows
				)
		except Exception:  # noqa: BLE001
			return ""
		return ""
	# 只报 job 事实（id/exit_code/命令）。曾带「在你看不到的时机完成了。这是完成
	# 通知，不是新任务」——前者是叙事非状态，后者是预防性否定指令，块头已承担
	# background only 语义（2026-09-09）。
	return (
		"# Background jobs（background only）\n"
		+ digest
	)
# 已撤块 budget_mirror（2026-09-15 用户裁定）：唯一触发条件
# ``budget.wall_deadline_ts`` 全仓只有 tests 设置，产品链路从无调用
# ⇒ 真实会话里永远不注入（死块）。且它想讲的内容正是同日撤销的
# wrap_up / runtime_budget 同类文本（预算作用域不明 → 模型必然误标）。
# 要时间感走 ``BudgetTracker.check_wall_deadline`` 的 80%/90% 播报通道。

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
	#: 行为账本（engine.loop_ledger.LoopLedger 实例；None = 不渲染账本行）。
	#: repeat_guard 块内直读当前计数——每轮新鲜渲染，不走 publish/clear 槽位
	#: （账本需持续在场，信号清零自动消失）。子代理上下文不渲染（净化清单）。
	loop_ledger: Any | None = None
	#: 管道 2 去重的**真相源**：本轮投影里真实存在的留痕身份集合
	#: ``{(note_key, note_fp)}``（由调用方从 MessageStore + 压缩游标算出）。
	#: 为空集 = 本轮投影里没有任何留痕 ⇒ 一律重发；``None`` = 调用方未提供
	#: （脚本/评测/单测）⇒ 退化为只看台账。
	#: 「台账说值没变」不再足以跳过：必须这一版**真的还在模型输入里**。
	visible_notes: frozenset[tuple[str, str]] | None = None

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
	lines = ["# 文件冲突（background only）"]
	for rel, (label, ts) in sorted(conflicts.items()):
		try:
			when = time.strftime("%H:%M", time.localtime(ts))
		except Exception:  # noqa: BLE001
			when = "不久前"
		lines.append(f"- `{rel}` 于 {when} 被会话「{label}」写入")
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
# T_now v2：一个边界，三条管道（2026-09-16 重分类；治理位）
# ---------------------------------------------------------------------------
# 边界（唯一注入时机）：工具批次完成后 / 下一次模型采样前。
#
# 管道 1｜用户消息（``user``）：**不在本表**——真 user 消息进历史
#         （MessageStore/JSONL），可被引用、可被压缩。
# 管道 2｜引擎当前态（``PIPE_STATE``）：每轮可能变。块文本是"当前值"，值不变
#         不重注（``dedup=True`` 者过 prompt/inject_store 台账）；受总量预算。
# 管道 3｜引擎事件（``PIPE_EVENT``）：发生一次即消费（drain 语义，取走即清）。
#         静默即永久丢失 ⇒ 永不裁剪、永不门控、**永不去重**。
# 第零管道｜静默：引擎能强制的（折叠 / guard / 清理 / 回退）永不进上下文。
#
# 登记表逐条声明三件事，遗漏一律按最保守处理（未知块 = PIPE_STATE +
# quota=True + dedup=False，即最容易被裁）：
#   pipe  归哪条管道；
#   quota 是否受总量配额裁剪（False = 构造处自有界，全保）；
#   dedup 是否纳入"值不变不重注"台账（仅 PIPE_STATE 可声明为 True）。
# 类目不再按"模型该不该服从"划分（那是导演视角），只按"这条信息从哪来、
# 什么时候该重发"划分。
PIPE_STATE = "state"
PIPE_EVENT = "event"

# F1 真硬顶：覆盖**全部**块（原 bypass 组取消）。
# PIPE_EVENT 由构造处各自有界（drain 一次），全保；
# quota 类受双闸：自身配额 与 (总预算 - 已用) 取小。
T_NOW_TOTAL_BUDGET = 6_000
T_NOW_QUOTA_MAX = 2_500
#: 事件块体积告警阈值（不裁剪，只观测：超了说明上游该收敛/摘要）
T_NOW_EVENT_WARN_BLOCKS = 8
T_NOW_EVENT_WARN_CHARS = 6_000

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
T_NOW_BLOCK_HARD_CAP = 16  # =现存量：23→21（删 stale_xeyo_md / nested_change）→18→16（2026-09-15 删 budget_mirror / runtime_mode_snapshot，peer_presence 收窄为 peer_notices）

T_NOW_BLOCK_REGISTRY: dict[str, dict[str, Any]] = {
	"continue": {
		"pipe": PIPE_STATE,
		"quota": False,
		# 不去重：文本恒定但每批工具结果都需要它——"值没变"在这里不等于
		# "可以不再说"，它是边界提示（本轮语境），不是状态快照。
		"dedup": False,
		"why": "工具续写轮无此块模型把 tool_result 当终点，不回用户问题",
	},
	"mode_instructions": {
		"pipe": PIPE_STATE,
		"quota": False,
		"dedup": True,
		"why": "Ask/Plan/批准计划是本轮行为模式合同，决定能否写盘",
	},
	# ``wrap_up`` / ``runtime_budget`` 已于 2026-09-15 撤销（用户裁定）：
	# 二者都只讲「预算已尽」却不标预算作用域，模型必然误标（第五/第六轮各一次
	# 猜成"上下文窗口"）。按引擎铁律「限制只在执行层」，收尾窗与配额由
	# engine/query_loop 强制，无需模型可见文本 ⇒ 登记表相应收缩（更宽松）。
	# ``budget_mirror`` / ``runtime_mode_snapshot`` 已于 2026-09-15 撤销
	# （用户裁定，18→16）。理由：
	# ① budget_mirror：触发条件 ``wall_deadline_ts`` 产品链路从无设置（死块）；
	# ② runtime_mode_snapshot：登记表 why 自陈"真门禁在 permissions 层"，
	#    属"知道自己被看着"的状态展示而非信息（铁律 3/4）。
	# 同轮 ``peer_presence`` 未整块撤销而**收窄**为 ``peer_notices``：常驻
	# beacon 是噪声，但 notices 有 drain 语义，整块删＝静默丢跨会话事件。
	"multi_agent_hint": {
		"pipe": PIPE_STATE,
		"quota": False,
		"dedup": True,
		"why": "多代理分解/汇总的协作合同，缺了会单干或重复汇总",
	},
	"repeat_guard": {
		"pipe": PIPE_STATE,
		"quota": False,
		"dedup": True,
		"why": "轮内防复读提醒（引擎 clear_advice 逐轮重置）",
	},
	"nested_instructions": {
		"pipe": PIPE_STATE,
		"quota": True,
		"dedup": True,
		"why": "子目录规则按需加载；限窗注入，滚出尾窗静默",
	},
	"compact": {
		"pipe": PIPE_STATE,
		"quota": False,
		"dedup": True,
		"why": "输出/写码压缩开关生效的统一行为规则（任一开关开启即注入；③合并两块减一）",
	},
	"mcp_required_warn": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "required MCP server 启动失败的可见警告（fail-visible）",
	},
	"reconcile_events": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "工具面/技能目录变更，consume 语义——静默即永久丢失",
	},
	"peer_notices": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "跨会话事件通知的唯一投递口，drain 语义——静默即永久丢失（原 peer_presence 收窄而来，常驻 beacon 已删）",
	},
	"file_conflict": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "触碰文件被其他会话写入——静默即丢，覆盖风险",
	},
	"browser_preview": {
		"pipe": PIPE_STATE,
		"quota": True,
		"dedup": True,
		"why": "用户预览页 URL：读页面正文的必要指针",
	},
	"agent_settlement": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "子代理结算通知，drain 语义——静默即永久丢失",
	},
	"goal": {
		"pipe": PIPE_STATE,
		"quota": False,
		"dedup": True,
		"why": "仅 blocked/pending_complete 注入：恢复执行/完成确认的锚",
	},
	"resume_directive": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "续跑富化指令投影-only 送达（修订2）：落库只存用户真实文本",
	},
	"pending_jobs": {
		"pipe": PIPE_EVENT,
		"quota": False,
		"dedup": False,
		"why": "job 完成补投：一次性待领信息（chat 入口已 drain），模型不读则任务结果不可见",
	},
	"skill_preinvoke": {
		"pipe": PIPE_STATE,
		"quota": False,
		# 不去重：同一句 /name 直呼会在不同用户轮反复出现，文本相同而轮次
		# 语境不同——按值去重会静默掉后一次直呼。
		"dedup": False,
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


def _block_meta(name: str) -> dict[str, Any]:
	"""登记表查询：未登记名按最保守处理（state + 受配额 + 不去重）并告警。

	未登记名正常进不来（``tests/test_t_now_block_registry.py`` 双向核对源码里
	``_tag_block`` 的名字），这里是防御性兜底 + 可见告警。
	"""
	meta = T_NOW_BLOCK_REGISTRY.get(name)
	if meta is None:
		_log.warning("T_now block not registered: %s（按 state+quota+不去重 兜底）", name)
		return {"pipe": PIPE_STATE, "quota": True, "dedup": False}
	return meta


def _tag_block(
	tagged: list[tuple[str, str]],
	name: str,
	text: str,
) -> None:
	"""装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。

	装配点**不再自带类目**：块归哪条管道、受不受配额、要不要去重，一律由
	登记表决定（单一来源）。新增块只写名与正文，类目写在登记表那一行。
	"""
	if name in _skipped_blocks():
		return
	body = (text or "").strip()
	if not body:
		return
	tagged.append((name, body))


def _dedup_round(
	tagged: list[tuple[str, str]],
	*,
	visible: frozenset[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
	"""管道 2 纪律：值不变不重注（仅登记表 ``dedup=True`` 的块）。

	按块名分组、逐段独立成键（同名多段用 ``#i`` 后缀区分）——一段变了只重发
	那一段，不连带整组。
	跳过条件 = 台账指纹未变 **且** 这一版真的在本轮投影里（``visible``）：
	后者是真相源，台账只是快路径（历史被改写却没人清账时，这里兜底）。
	事件类**永不过此处**：drain 语义下"第二次发生"必须是第二次注入。
	"""
	groups: dict[str, list[int]] = {}
	counts: dict[str, int] = {}
	for i, (name, _text) in enumerate(tagged):
		counts[name] = counts.get(name, 0) + 1
	seen: dict[str, int] = {}
	for i, (name, _text) in enumerate(tagged):
		meta = _block_meta(name)
		if meta.get("pipe") != PIPE_STATE or not meta.get("dedup"):
			continue
		if counts[name] > 1:
			idx = seen.get(name, 0)
			seen[name] = idx + 1
			key = f"{name}#{idx}"
		else:
			key = name
		groups.setdefault(key, []).append(i)
	if not groups:
		return tagged
	drop: set[int] = set()
	for key, idxs in groups.items():
		joined = "\n".join(tagged[i][1] for i in idxs)
		if not inject_store.decide(key, joined, visible=visible):
			drop.update(idxs)
			continue
		# 本轮以「值变了 / 已不在可见面」送达：登记留痕 → 下一个边界落库进历史。
		# 此后历史里就有这一版 ⇒ 台账判「值没变」成立，尾部不再重发。
		inject_store.note(key, joined, kind="state")
	if not drop:
		return tagged
	return [item for i, item in enumerate(tagged) if i not in drop]

# D1「模糊指代轮识别」已于 2026-09-16 删除（用户裁定：T_now 不为弱模型做特化）。
# 删掉的东西：``_VAGUE_ACK`` / ``_VAGUE_MARKERS`` / ``_VAGUE_MAX_CHARS`` /
# ``_VAGUE_CODE_MARKERS`` / ``_is_vague_referent_turn`` 及装配口那一道
# 「命中即静默全部参考块」的闸。理由不是"判断不准"，而是这条闸的准入标准
# 本身在导演注意力：它猜「用户这句话是不是没说完」，然后替模型减少信息。
# 按铁律 1/5：注意力里只出现信息；模型强弱不改变口径，护栏只在执行层。

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


def _trim_tagged_blocks(
	tagged: list[tuple[str, str]],
	*,
	total: int = T_NOW_TOTAL_BUDGET,
	quota_max: int = T_NOW_QUOTA_MAX,
) -> list[tuple[str, str]]:
	"""F1：管道感知预算。非 quota 类全保（构造处各自有界）；quota 类按装配序
	填充 min(quota_max, total - 已用) 的配额，末块超限截断（带 …）。

	与旧 ``_trim_blocks_to_budget`` 的差异：覆盖原 bypass 组（compact / mcp /
	reconcile / peer / conflict / preview / settlements / goal），使 T_now
	总量真正有闸。quota 与否不再由类目猜，而是登记表逐块声明（``quota``）。
	"""
	kept: list[tuple[str, str]] = []
	inv: list[tuple[str, str]] = []
	used = 0
	ev_blocks = 0
	ev_chars = 0
	for name, raw in tagged:
		b = (raw or "").strip()
		if not b:
			continue
		meta = _block_meta(name)
		if meta.get("quota"):
			inv.append((name, b))
		else:
			kept.append((name, b))
			used += len(b)
		if meta.get("pipe") == PIPE_EVENT:
			ev_blocks += 1
			ev_chars += len(b)
	# 事件类不裁剪（drain 语义，裁＝静默丢）⇒ 体积异常必须在上游收敛。
	# 这里只做可观测：超阈值 WARN，不改变送达。
	if ev_blocks > T_NOW_EVENT_WARN_BLOCKS or ev_chars > T_NOW_EVENT_WARN_CHARS:
		_log.warning(
			"T_now 事件块体积异常：blocks=%d chars=%d（事件永不裁剪，请上游收敛）",
			ev_blocks,
			ev_chars,
		)
	room = max(0, min(quota_max, total - used))
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
	strategy = (ctx.strategy or "").strip() or t_now_strategy()
	if strategy == STRATEGY_PREFILL:
		# 预留档：prefill 厂商容忍度实测通过前回落环境声道。
		strategy = STRATEGY_ENV_CHANNEL
	prepared_events = (
		_prepared_events_for(ctx.session_id)
		if strategy != STRATEGY_SKIP
		else []
	)
	# T_now v2：所有块以 ``(登记名, 正文)`` 装配；归哪条管道、受不受配额、
	# 要不要去重，全部由登记表逐条声明（装配点不自带类目）。未登记名按最
	# 保守处理（state + 受配额 + 不去重）。
	tagged: list[tuple[str, str]] = []
	after_tools = ends_with_tool_result(out)

	if after_tools:
		_tag_block(tagged, "continue", CONTINUE_AFTER_TOOLS)

	for blk in build_mode_context_blocks(
		mode=current_agent_mode(),
		approved_plan=ctx.approved_plan,
		ask_instructions=ASK_MODE_INSTRUCTIONS,
		plan_instructions=PLAN_MODE_INSTRUCTIONS,
		plan_pointer=ctx.plan_pointer,
	):
		_tag_block(tagged, "mode_instructions", blk)
	# ── 已撤块（2026-09-15，用户裁定）─────────────────────────────────
	# ``wrap_up``（``# Wrap-up(预算已尽)``）与 ``runtime_budget``
	# （``# Runtime budget notice``）**不再装配进模型可见文本**。
	#
	# 结构性理由（不是"话说得不好"）：这两块是 directive 类、预算内绝不裁剪，
	# 必然进注意力；而它们只说「预算已尽 / 预算」**不说是哪一种预算**。同一个
	# TurnBudget 里混装了三种作用域的预算（回合级 max_turns / 任务级墙钟 /
	# 会话级 USD），模型收到不标作用域的"预算已尽"只能自己猜——第五轮猜成
	# 「上下文窗口」，第六轮再次猜成「上下文窗口」（本会话实测 100+ 次幻觉调用）。
	#
	# 按引擎铁律第 3/4 条（限制只在执行层 / 能静默就不说话）：收尾窗、工具配额、
	# 硬停本来就是执行层事实（query_loop 的 prepare_next_turn / wrap_quota_left），
	# 不需要讲给模型听。执行层一律保留：forced_wrap_up 状态、收尾配额、
	# StoppedEvent 语义、成本闸全部照旧（删的只是文本，不是机制）。
	if ctx.multi_agent:
		try:
			from tools.agent_tool.prompt import MULTI_AGENT_HINT

			_tag_block(tagged, "multi_agent_hint", MULTI_AGENT_HINT.strip())
		except Exception:
			_log.debug("MULTI_AGENT_HINT load failed", exc_info=True)

	# T6：重复调用递进提醒（background only）——query_loop 轮内状态，
	# 不进历史、不改写 ToolResult；每次 submit 由引擎 clear_advice 重置。
	# T14 净化清单：子代理上下文不继承主循环的 repeat guard。
	# 停滞监测（todo 契约执行侧）同块消费：同为 advice-only、逐 submit
	# 重置、子代理豁免——不新增注册条目、不动 T_NOW_BLOCK_HARD_CAP。
	try:
		from engine.repeat_guard import current_advice

		# C3 裁决（2026-09-08）：stagnation_watch 已删——引擎检测到停滞不再
		# 生成劝导文本，行为纠偏交给执行层失败信号；本块只消费 repeat 的
		# 事实性信息（同签名重复计数）。
		rep = current_advice()
		# 行为账本（loop_ledger 方案）：s1/s2/s3 任一达阈值时渲染 ≤5 行
		# 纯数据（计数与事实，无导演词——措辞由 test_loop_ledger 执法）；
		# 与 advice 同块消费，不新增注册条目、不动 T_NOW_BLOCK_HARD_CAP。
		ledger_text = ""
		if ctx.loop_ledger is not None:
			try:
				ledger_text = ctx.loop_ledger.render()
			except Exception:
				_log.debug("loop ledger render failed", exc_info=True)
		combined = "\n".join(x for x in (rep, ledger_text) if x)
		if combined and not ctx.subagent:
			# #2 完成度提示（思想蒸馏自 Todo DAG「失败要局部化」）并入同块：
			# advice 非空 = 引擎已检出重复证据，此刻补渲染"已完成 X/Y +
			# 剩余项"纯事实。常态零注入——不新增注册条目、不动
			# T_NOW_BLOCK_HARD_CAP（消融随 repeat_guard）。
			block_text = f"# Repeat guard（background only）\n{combined}"
			if ctx.working is not None:
				try:
					from engine.todo_hint import build_todo_hint

					hint = build_todo_hint(
						getattr(ctx.working, "todos", None) or []
					)
					if hint:
						block_text += "\n\n" + hint
				except Exception:
					_log.debug("todo progress inject failed", exc_info=True)
			_tag_block(tagged, "repeat_guard", block_text)
	except Exception:
		_log.debug("repeat advice inject failed", exc_info=True)

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
			_tag_block(tagged, "nested_instructions", nested_block)

		# 裁决 5（2026-09-08）：stale XEYO.md 提醒与嵌套变更通知块已删——
		# 规则文件的内容变化由 Nested 块实时读取自然生效；引擎只静默维护
		# 嵌套登记状态（reconcile_nested_state），不给模型任何"请检查/停止参照"。
		try:
			from memory.instruction_maintain import reconcile_nested_state

			reconcile_nested_state(ctx.working)
		except Exception:
			_log.debug("reconcile nested state failed", exc_info=True)
		# 批次1：Proposals digest 不再推送 T_now——模型对候选晋升无可执行
		# 动作（NightShift / 人工确认），纯 ambient 噪音。拉取通道：
		# /proposals slash 命令；Memory(action=search) 结果附带候选计数行
		# （memory_tool._proposals_notice_line，批次1 同步落地）。

	# 批次3：Memory index 不再推送 T_now——事故源头块退役。能力宣告住
	# Memory 工具 description（含「依赖历史上下文/偏好先 search」指引），
	# 检索走 Memory(action=search) 拉取。include_memory_index 字段保留
	# 兼容（决定 inject_instructions 默认值）；runtime._append_memory_index
	# 仍供脚本/评测使用。生产投影层恒不推送，不经 T_now；受控重开须同时
	# 修改 engine/query_loop._memory_index_live_enabled 与对应准入测试。

	# ---- P1/F1：原 bypass 组全部纳入装配（真硬顶，不再有无闸块）----
	# 压缩块（输出精简/写代码精简合并为一个 compact；相关开关全关时不挂，T_now 与历史保持干净）。
	_compact = compact_block()
	if _compact:
		_tag_block(tagged, "compact", bg_wrap(_compact))

	# F1：MCP required server 启动失败 → T_now 警告块（background only，带归属头）。
	if (ctx.cwd or "").strip() and not ctx.subagent:
		try:
			from extension.mcp_manager import mcp_required_warning_block

			mcp_warn = mcp_required_warning_block(ctx.cwd.strip())
			if mcp_warn:
				_tag_block(tagged, "mcp_required_warn", mcp_warn)
		except Exception:
			_log.debug("mcp required warning inject failed", exc_info=True)

	# F2.5：reconcile push/pull 活页块（# 工具面变更 / # 技能目录变更）。
	# consume 语义（取走即清）→ EVENT：绝不门控、绝不裁剪；子代理不继承（T14）。
	if not ctx.subagent:
		try:
			from extension.reconcile import consume_reconcile_blocks

			for blk in consume_reconcile_blocks():
				if blk and str(blk).strip():
					_tag_block(tagged, "reconcile_events", str(blk).strip())
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
		# block: peer_notices —— 跨会话事件通知（drain 语义；取走即清，静默即
		# 永久丢失）。2026-09-15 收窄：原 peer_presence 的常驻 beacon
		# （"同工作区另有 N 个会话运行中"）已删——无对象告知不改变任何动作；
		# 但 notices 是跨会话事件的唯一投递口，必须保留。原
		# XEYO_PEER_PRESENCE_OFF 逃生门随之取消（无 beacon 后块常态自静默）。
		try:
			from engine.session_presence import peer_notice_block

			peer = peer_notice_block(ctx.cwd.strip(), ctx.session_id.strip())
			if peer:
				_tag_block(tagged, "peer_notices", peer)
		except Exception:
			_log.debug("peer_notice_block failed", exc_info=True)
		# 文件冲突前景提醒：本会话触碰过的文件被其他会话树写入。
		# 只列冲突路径，静默即无冲突。
		try:
			touched = collect_session_touched_paths(out)
			conflict = file_conflict_block(
				ctx.cwd.strip(), ctx.session_id.strip(), touched
			)
			if conflict:
				_tag_block(tagged, "file_conflict", conflict)
		except Exception:
			_log.debug("file_conflict_block failed", exc_info=True)

	preview = browser_preview_block()
	if preview and not ctx.subagent:
		_tag_block(tagged, "browser_preview", preview)

	# 已撤块 runtime_mode_snapshot（2026-09-15 用户裁定）：见文件上方常量区说明。
	# T14 净化清单：子代理上下文不继承主会话 GUI 模式广播。

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
				_tag_block(tagged, "agent_settlement", settle_block)
		except Exception:
			_log.debug("agent settlement inject failed", exc_info=True)

	# T9：Goal 块（仅 blocked / pending_complete 注入，active 常态静默）；子代理上下文不注入。
	if (ctx.goal or "").strip() and not ctx.subagent:
		_tag_block(tagged, "goal", ctx.goal.strip())

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
					f"# Resume state（background only）\n{rd}",
				)
		except Exception:
			_log.debug("resume directive inject failed", exc_info=True)

	# 42 号：job 完成通知补投块（一次性待领信息，chat.py 入口已 drain）。
	jobs_block = pending_jobs_block()
	if jobs_block and not ctx.subagent:
		_tag_block(tagged, "pending_jobs", jobs_block)

	# 已撤块 budget_mirror（2026-09-15 用户裁定）：见文件上方常量区说明。
	# 注意执行层一律保留：墙钟 80%/90% 播报、100% grace→wrap、回合与成本闸
	# 全部照旧（删的只是文本，不是机制）。

	# block: skill_preinvoke —— 用户直呼技能（fresh-user 轮首行 /name 命中
	# user-invocable 技能）：宿主确定性注入渲染正文（tool-skill pre-step），
	# 替代「请用 Skill 工具…」的客户端改写赌注。命令命名空间
	# 优先（slash registry 命中即非手势）；子代理不继承；工具续写轮不重放。
	if (ctx.cwd or "").strip() and not ctx.subagent and not after_tools:
		try:
			from engine.skill_preinvoke import preinvoke_skill_block

			skill_blk = preinvoke_skill_block(ctx.cwd.strip(), _last_user_text(out))
			if skill_blk:
				_tag_block(tagged, "skill_preinvoke", skill_blk)
		except Exception:
			_log.debug("skill preinvoke inject failed", exc_info=True)

	# 回退重装：事件源已经在上一次装配时 drain，这里复用已取出的事件正文。
	# 事件仍按登记表进入，不经过去重或配额裁剪。
	for event_name, event_text in prepared_events:
		_tag_block(tagged, event_name, event_text)

	# 记录本轮最终保留的事件。事件不走 _dedup_round，且 _trim_tagged_blocks
	# 对事件无裁剪；请求没有收到响应 chunk 时，下一次声道重装复用这一批。
	if strategy != STRATEGY_SKIP:
		_remember_prepared_events(
			ctx.session_id,
			[
				(name, text)
				for name, text in tagged
				if _block_meta(name).get("pipe") == PIPE_EVENT
			],
		)

	# ---- 管道 2 纪律：值不变不重注（台账 prompt/inject_store，默认 on）----
	# 只作用于登记表 ``dedup=True`` 的块；事件类永不过此处（drain 语义下
	# "第二次发生"必须是第二次注入）。台账关档时逐字节零影响。
	token = inject_store.begin_round((ctx.session_id or "").strip())
	try:
		tagged = _dedup_round(tagged, visible=ctx.visible_notes)
	finally:
		inject_store.end_round(token)

	# ---- P1/F1：管道感知真硬顶 ----
	kept = _trim_tagged_blocks(tagged)

	# wrap_up 兜底已随该块整体撤销（见上方「已撤块」说明）：不再向模型重挂
	# 任何"预算/收尾"文本。执行层的收尾窗与配额与提示文本无关。

	# ---- P1/A1 分仓 / 方案A 环境声道 ----
	# env_channel：全部块装进一对仅存在于投影的伪造 tool 对尾插——
	# 用户消息原文不再被任何注入块夹持（fresh-user 轮不再需要参考数据
	# 前插分仓），说话人身份由消息结构保证。
	# legacy：fresh-user 轮 quota 类（nested 正文 / 浏览器预览）前插到用户
	# 文本之前（生成点紧邻用户请求，recency 为用户服务）；其余尾插贴近生成点。
	# after_tools 轮维持原尾插合同（Continue 在前）。
	if strategy == STRATEGY_SKIP:
		# L2（2026-09-09）：厂商拒绝伪造 tool 对时本轮不注入，绝不落回
		# legacy 用户尾插（引擎文本进用户角色=说话人混淆源）。执行层
		# 硬约束（预算/回合/wrap 门）不依赖提示文本。
		return out
	if strategy == STRATEGY_ENV_CHANNEL:
		env_text = format_env_notice([t for _k, t in kept])
		if env_text:
			return append_env_notice_pair(out, env_text)
		return out
	if strategy == STRATEGY_SYSTEM_CHANNEL:
		# 声道 B（治本档）：同一份正文（复用 ENV_NOTICE_HEADER / format_env_notice），
		# 但承载形态是**原生 system 消息**而非伪造 tool 对 —— 伪对在结构上与
		# "模型自己的工具调用"同形，模型因此认定自己拥有 xeyo_env_notice 并真的
		# 去调它（第六轮 70+ 次；第七轮单会话 60+ 次，且被 host 转成工具轮回灌
		# Continue 形成自催化闭环）。不可调用性必须来自形态，不靠劝阻文本。
		env_text = format_env_notice([t for _k, t in kept])
		if env_text:
			return append_system_notice(out, env_text)
		return out
	if after_tools:
		return append_text_blocks_to_last_user(out, [t for _k, t in kept])
	head = [t for n, t in kept if _block_meta(n).get("quota")]
	tail = [t for n, t in kept if not _block_meta(n).get("quota")]
	if head:
		out = prepend_text_blocks_to_last_user(out, head)
	if tail:
		out = append_text_blocks_to_last_user(out, tail)
	return out


__all__ = [
	"ASK_MODE_INSTRUCTIONS",
	"PLAN_MODE_INSTRUCTIONS",
	"OUTPUT_COMPACT_RULES",
	"OUTPUT_MODE_VARIANTS",
	"CODE_COMPACT_RULES",
	"CODE_MODE_VARIANTS",
	"T_NOW_EXTRA_BUDGET",
	"T_NOW_TOTAL_BUDGET",
	"T_NOW_QUOTA_MAX",
	"pending_jobs_block",
	"PIPE_STATE",
	"PIPE_EVENT",
	"T_NOW_BLOCK_REGISTRY",
	"NESTED_RESERVE_CHARS",
	"InjectContext",
	"run_pre_llm_inject",
	"approved_plan_decays_on",
	"output_compact_block",
	"code_compact_block",
	"compact_block",
	"browser_preview_block",
	"collect_session_touched_paths",
	"file_conflict_block",
]
