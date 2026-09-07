"""TodoWriteTool — 会话清单（全量替换或按 id 合并）。

热路径：TodoStore（按 session 注入、按 agent key 隔离）。
冷启动：sidecar `.working.json` → 空则 transcript 扫最后一次 TodoWrite。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.todo_write_tool.constants import TODO_WRITE_TOOL_NAME
from tools.todo_write_tool.prompt import DESCRIPTION
from tools.todo_write_tool.store import DEFAULT_TODO_KEY, TodoStore
from tools.todo_write_tool.types import TodoItem, todo_item_from_raw

# 供 UI 解析的机器可读快照（前端解析此标签）。
TODO_LIST_TAG = "todo_list"


@dataclass
class TodoWriteInput:
	todos: list[TodoItem]
	merge: bool = False


@dataclass
class TodoWriteOutput:
	old_todos: list[TodoItem] = field(default_factory=list)
	new_todos: list[TodoItem] = field(default_factory=list)
	stored_todos: list[TodoItem] = field(default_factory=list)


def prompt() -> str:
	return DESCRIPTION.strip()


def _coerce_bool(value: Any, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	if isinstance(value, str):
		s = value.strip().lower()
		if s in ("true", "on", "1", "yes"):
			return True
		if s in ("false", "off", "0", "no"):
			return False
	return default


def parse_input(raw: dict[str, Any]) -> TodoWriteInput | dict[str, Any]:
	"""返回 TodoWriteInput，或错误 dict {result: False, message}。"""
	todos_raw = raw.get("todos")
	if todos_raw is None:
		return {"result": False, "message": "todos is required", "errorCode": 0}
	if not isinstance(todos_raw, list):
		return {
			"result": False,
			"message": "todos must be an array",
			"errorCode": 1,
		}

	items: list[TodoItem] = []
	for i, entry in enumerate(todos_raw):
		item = todo_item_from_raw(entry)
		if item is None:
			return {
				"result": False,
				"message": (
					f"todos[{i}] must have non-empty content, activeForm, "
					f"and status in pending|in_progress|completed"
				),
				"errorCode": 2,
			}
		items.append(item)
	return TodoWriteInput(todos=items, merge=_coerce_bool(raw.get("merge"), False))


def validate_input(inp: TodoWriteInput) -> dict[str, Any]:
	# 允许空列表（清空清单）。结构已在 parse 中校验。
	return {"result": True, "message": "", "errorCode": 0}


def _merge_todos(old: list[TodoItem], submitted: list[TodoItem]) -> list[TodoItem]:
	"""按 id 合并：更新匹配项、追加新 id、保留未匹配的旧项。"""
	by_id = {t.id: t for t in old if t.id}
	order = [t.id for t in old if t.id]
	seen_new: set[str] = set()
	for item in submitted:
		if item.id in by_id:
			by_id[item.id] = item
		else:
			by_id[item.id] = item
			order.append(item.id)
		seen_new.add(item.id)
	# 未匹配的旧项保持相对顺序；新 id 已追加。
	return [by_id[i] for i in order if i in by_id]


class TodoWriteTool:
	name = TODO_WRITE_TOOL_NAME

	search_hint = "manage the session task checklist"

	def __init__(
		self,
		*,
		cwd: str = ".",
		store: TodoStore | None = None,
		todo_key: str = DEFAULT_TODO_KEY,
		session_id: str = "",
		agent_id: str = "main",
	) -> None:
		self._cwd = cwd  # 与 catalog 工厂签名一致
		self._store = store or TodoStore()
		self._todo_key = todo_key
		self._session_id = session_id
		self._agent_id = (agent_id or "main").strip() or "main"

	def set_todo_store(self, store: TodoStore) -> None:
		self._store = store

	def set_session_id(self, session_id: str) -> None:
		self._session_id = (session_id or "").strip()

	def set_agent_id(self, agent_id: str | None) -> None:
		aid = (agent_id or "").strip() or "main"
		self._agent_id = aid
		# 子 agent 用独立 key；主会话保持 default 以兼容 sidecar。
		if aid and aid != "main":
			self._todo_key = f"agent-{aid}"
		else:
			self._todo_key = DEFAULT_TODO_KEY

	@staticmethod
	def is_read_only() -> bool:
		return False

	def current_todos(self) -> list[TodoItem]:
		"""当前 key 下的清单（供引擎 turn-end 候选派生读——不做任何写）。"""
		try:
			return self._store.get(self._todo_key)
		except Exception:  # noqa: BLE001
			return []

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def check_permissions(self, inp: TodoWriteInput, context: Any = None) -> bool:
		return True

	def call(self, inp: TodoWriteInput) -> TodoWriteOutput:
		old = self._store.get(self._todo_key)
		submitted = list(inp.todos)
		if inp.merge:
			merged = _merge_todos(old, submitted)
			all_done = bool(merged) and all(t.status == "completed" for t in merged)
			stored = [] if all_done else merged
			result_todos = merged
		else:
			all_done = bool(submitted) and all(t.status == "completed" for t in submitted)
			stored = [] if all_done else submitted
			result_todos = submitted
		self._store.set(stored, key=self._todo_key)
		return TodoWriteOutput(
			old_todos=old,
			new_todos=result_todos,
			stored_todos=stored,
		)

	@staticmethod
	def map_tool_result_to_content(out: TodoWriteOutput) -> str:
		"""供模型阅读的人类文本 + 供 UI 的 <todo_list> JSON。"""
		lines = [
			"Todos have been modified successfully. Ensure that you continue "
			"to use the todo list to track your progress. Please proceed with "
			"the current tasks if applicable",
		]
		if out.new_todos:
			lines.append("")
			lines.append("Current todos:")
			for t in out.new_todos:
				lines.append(f"- [{t.status}] {t.content}")
			if all(t.status == "completed" for t in out.new_todos):
				lines.append("")
				lines.append(
					"All todos are completed. Do not keep restating the "
					"finished list unless the user asks for new work."
				)
		else:
			lines.append("")
			lines.append("Todo list is now empty.")

		payload = [t.to_dict() for t in out.new_todos]
		blob = json.dumps(payload, ensure_ascii=False)
		lines.append("")
		lines.append(f"<{TODO_LIST_TAG}>")
		lines.append(blob)
		lines.append(f"</{TODO_LIST_TAG}>")
		return "\n".join(lines)

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": DESCRIPTION.strip(),
			"input_schema": {
				"type": "object",
				"properties": {
					"merge": {
						"type": "boolean",
						"description": (
							"If true, merge by id into the existing list "
							"(update matching, append new, keep unmatched). "
							"If false/omit, full replace."
						),
						"default": False,
					},
					"todos": {
						"type": "array",
						"description": (
							"Todo items. Full replace unless merge=true."
						),
						"items": {
							"type": "object",
							"properties": {
								"id": {
									"type": "string",
									"description": (
										"Stable item id (auto-generated if omitted)"
									),
								},
								"content": {
									"type": "string",
									"description": (
										"Imperative task description "
										'(e.g. "Run tests")'
									),
								},
								"status": {
									"type": "string",
									"enum": [
										"pending",
										"in_progress",
										"completed",
									],
								},
							"activeForm": {
								"type": "string",
								"description": (
									"Present continuous form "
									'(e.g. "Running tests")'
								),
							},
							"output": {
								"type": "string",
								"description": (
									"Optional artifact path (relative to the "
									'workspace, e.g. "reports/summary.md"). Set '
									"it when this step ends by producing a file "
									"or concrete result on disk; omit for "
									"research/transient steps. The engine keeps "
									"it as structured task state."
								),
							},
							},
							"required": ["content", "status", "activeForm", "id"],
						},
					},
				},
				"required": ["todos"],
			},
		}

	def _materialization_facts(self, todos: list[TodoItem]) -> str:
		"""产物落盘事实（R4 注册表的确定性核对，非命令、非闸门）。

		对「标 completed 且声明了产物路径」的条目 stat 磁盘，把存在/缺失
		作为事实追加给模型与 UI——引擎自己看磁盘，不依赖模型自觉，但
		不做任何拦截（是否补救仍由模型/用户裁决）。in_progress 与未声明
		产物的条目零开销；文件系统异常 fail-open（不加行）。
		"""
		if not todos:
			return ""
		rows: list[str] = []
		for t in todos:
			path = (t.output or "").strip()
			if t.status != "completed" or not path:
				continue
			try:
				from pathlib import Path

				full = Path(self._cwd or ".").joinpath(path)
				if full.exists() and full.is_file():
					try:
						size = full.stat().st_size
						rows.append(f"[task-check] 产物 {path}: 已存在（{size} B）")
					except OSError:
						rows.append(f"[task-check] 产物 {path}: 已存在")
				else:
					rows.append(
						f"[task-check] 产物 {path}: 磁盘上不存在——该步骤标了 "
						"completed，但声明的产物文件尚未落盘。"
					)
			except Exception:  # noqa: BLE001 — fail-open
				continue
		return "\n".join(rows)

	async def execute(
		self,
		input: dict[str, Any],
		abort: AbortController,
	) -> ToolResult:
		abort.raise_if_aborted()
		parsed = parse_input(input)
		if isinstance(parsed, dict) and parsed.get("result") is False:
			return ToolResult(content=str(parsed.get("message")), is_error=True)
		assert isinstance(parsed, TodoWriteInput)
		v = validate_input(parsed)
		if not v.get("result"):
			return ToolResult(content=str(v.get("message")), is_error=True)
		if not self.check_permissions(parsed):
			return ToolResult(content="permission denied", is_error=True)
		abort.raise_if_aborted()
		try:
			out = self.call(parsed)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)
		abort.raise_if_aborted()
		self._note_presence_todos(out.new_todos)
		content = self.map_tool_result_to_content(out)
		facts = self._materialization_facts(out.new_todos)
		if facts:
			content = f"{content}\n\n{facts}"
		return ToolResult(
			content=content,
			is_error=False,
			todos=[t.to_dict() for t in out.new_todos],
		)

	def _note_presence_todos(self, todos: list[TodoItem]) -> None:
		sid = (self._session_id or "").strip()
		if not sid:
			return
		briefs = [
			(t.active_form or t.content or "").strip()
			for t in todos
			if (t.status or "") == "in_progress"
		]
		if not briefs:
			briefs = [(t.content or "").strip() for t in todos if (t.content or "").strip()]
		try:
			from engine.session_presence import default_session_presence

			default_session_presence().note_todos(self._cwd, sid, briefs)
		except Exception:  # noqa: BLE001
			pass
