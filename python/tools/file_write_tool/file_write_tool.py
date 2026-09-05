"""FileWriteTool — 写入文件（创建/覆盖 + XEYO schema/execute）。"""

# 写权限：走 permissions.filesystem 路径狱 / 密钥 DENY / 危险 ASK；
# ASK 仅在 registry 已 preapproved 时放行。.ipynb 请用 NotebookEdit。
# TODO: [历史] fileHistory 备份 / 结构化 patch 展示
# TODO: [集成] VSCode diff 通知
# TODO: [密钥] team-memory secret 扫描
# TODO: [UI] 专用终端渲染 / Hooks / 遥测

from __future__ import annotations

import asyncio
import difflib
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

from engine.abort import AbortController
from permissions import filesystem
from rewind.context import current_context
from tools.base_tool import ToolResult

from tools.fileio.diff_preview import append_diff_fence, format_capped_unified_diff
from tools.fileio.paths import expand_path
from tools.fileio.read_state import FileStateEntry, ReadFileState
from tools.fileio.text import get_mtime_ms, normalize_newlines, read_text_file, write_text_file
from tools.fileio.conflict import build_stale_message
from tools.file_write_tool.prompt import DESCRIPTION, FILE_WRITE_TOOL_NAME

WriteType = Literal["create", "update"]

FILE_UNEXPECTEDLY_MODIFIED_ERROR = (
	"File has been unexpectedly modified. Read it again before attempting to write it."
)


@dataclass
class WriteInput:
	file_path: str
	content: str


@dataclass
class WriteOutput:
	type: WriteType
	file_path: str
	lines_added: int = 0
	lines_removed: int = 0
	old_content: str = ""
	new_content: str = ""
	# T28：WriteStore journal 记录失败警示（文件已落盘但证据链缺口）。
	notice: str = ""


def _line_diff_counts(old: str, new: str) -> tuple[int, int]:
	"""统计 UI 展示用的增删行数（+N -M）。"""
	a = old.splitlines(keepends=True)
	b = new.splitlines(keepends=True)
	added = removed = 0
	for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
		if tag == "replace":
			removed += i2 - i1
			added += j2 - j1
		elif tag == "delete":
			removed += i2 - i1
		elif tag == "insert":
			added += j2 - j1
	return added, removed


def prompt() -> str:
	return DESCRIPTION.strip()


class FileWriteTool:
	name = FILE_WRITE_TOOL_NAME
	search_hint = "create or overwrite files"
	max_result_size_chars = 100_000

	def __init__(
		self,
		*,
		cwd: str = ".",
		read_state: ReadFileState | None = None,
	) -> None:
		self._cwd = os.path.abspath(cwd or ".")
		self._read_state = read_state or ReadFileState()
		self._write_store: Any | None = None   # 多agent 单写者队列（None=直通旁路，零回归）
		self._agent_id: str = "main"
		self._session_id: str = ""

	def set_read_file_state(self, state: ReadFileState) -> None:
		self._read_state = state

	def set_session_id(self, session_id: str | None) -> None:
		"""注入当前会话 id（session_pool._inject_session_ids）；用于跨会话外部归因。"""
		self._session_id = (session_id or "").strip()

	def set_write_store(self, store: Any) -> None:
		"""注入 write-store；None 表示单 agent 直通旁路（行为与原先一致）。"""
		self._write_store = store

	def set_agent_id(self, agent_id: str | None) -> None:
		self._agent_id = agent_id or "main"

	def _persist(self, full: str, content: str, *, encoding: str, line_endings: str) -> str:
		"""落盘：无 store -> 直通旁路（与原先完全一致，零回归）；有 store -> 经 write_store。

		单 agent 默认无 store，行为不变；子 Agent（write_scope 已激活）必须经 WriteStore。
		返回 T28 journal 警示（正常为空串）。
		"""
		if self._write_store is None:
			from permissions.write_scope import get_write_scope

			if get_write_scope() is not None:
				raise RuntimeError(
					"write_store required for sub-agent writes "
					"(refusing direct disk bypass)"
				)
			write_text_file(full, content, encoding=encoding, line_endings=line_endings)
			return ""
		from engine.write_store import ChangeIntent, EditOp, _content_hash_text

		entry = self._read_state.get(full)
		base_hash = ""
		if entry is not None and entry.content:
			base_hash = _content_hash_text(entry.content)
		elif entry is not None:
			# sidecar 恢复的条目只有 mtime 没有正文（content_known=False）。
			# 交空 base 会被 store 以 missing_read 拒绝（恢复后首写必败）；
			# 现读现比对：本调用已在 to_thread 中，store 锁仍串行写者。
			from tools.fileio.text import read_text_file as _rtf

			try:
				base_hash = _content_hash_text(_rtf(full)[0])
			except OSError:
				base_hash = ""
		# 与直通路径 write_text_file 等价：按 line_endings 还原换行、保留
		# encoding。store 的原子写用 newline=''，不再做平台翻译。
		content_out = (
			content
			if line_endings != "CRLF"
			else "\r\n".join(content.replace("\r\n", "\n").split("\n"))
		)
		result = self._write_store.submit_sync(
			ChangeIntent(
				agent_id=self._agent_id,
				base_hashes={full: base_hash},
				ops=[EditOp(path=full, new_content=content_out)],
				encoding=encoding,
			)
		)
		if not result.ok:
			reason = str(result.reason or "")
			if result.base_stale or reason in ("stale", "missing_read"):
				snapshot = entry.content if entry is not None else ""
				try:
					disk_content, _, _ = read_text_file(full)
				except OSError:
					disk_content = ""
				extra = str(getattr(result, "detail", "") or "").strip()
				detail = build_stale_message(
					f"write conflict ({reason or 'stale'}): "
					f"{FILE_UNEXPECTEDLY_MODIFIED_ERROR}",
					self._cwd,
					full,
					self._session_id,
					snapshot,
					disk_content,
				)
				if extra and "session" not in detail:
					detail += "\n" + extra
				raise RuntimeError(detail + " Re-Read then retry.")
			raise RuntimeError(f"write failed: {reason}")
		return str(getattr(result, "journal_warning", "") or "")

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		return {
			"name": self.name,
			"description": prompt(),
			"input_schema": {
				"type": "object",
				"properties": {
					"file_path": {
						"type": "string",
						"description": (
							"The absolute path to the file to write "
							"(must be absolute, not relative)"
						),
					},
					"content": {
						"type": "string",
						"description": "The content to write to the file",
					},
				},
				"required": ["file_path", "content"],
			},
		}

	def get_path(self, input_data: WriteInput) -> str:
		return expand_path(input_data.file_path, cwd=self._cwd)

	def validate_input(self, input_data: WriteInput) -> dict[str, Any]:
		if not input_data.file_path or not str(input_data.file_path).strip():
			return {
				"result": False,
				"message": "file_path is required",
				"errorCode": 0,
			}
		if input_data.content is None:
			return {
				"result": False,
				"message": "content is required",
				"errorCode": 0,
			}

		full = self.get_path(input_data)
		if full.startswith("\\\\") or full.startswith("//"):
			return {"result": True}

		if full.lower().endswith(".ipynb"):
			from tools.notebook_edit_tool.prompt import IPYNB_REJECT

			return {
				"result": False,
				"message": IPYNB_REJECT,
				"errorCode": 6,
			}

		if not os.path.exists(full):
			# 新文件：无需先读
			return {"result": True}

		if os.path.isdir(full):
			return {
				"result": False,
				"message": f"Path is a directory, not a file: {input_data.file_path}",
				"errorCode": 4,
			}

		entry = self._read_state.get(full)
		if not entry or entry.is_partial_view:
			return {
				"result": False,
				"message": (
					"File has not been read yet. Read it first before writing to it."
				),
				"errorCode": 2,
			}

		try:
			mtime = get_mtime_ms(full)
		except OSError as e:
			return {
				"result": False,
				"message": str(e),
				"errorCode": 5,
			}

		# content_known=False：sidecar 恢复的条目没有正文快照，放行由整文
		# 写入语义兜底（同 file_edit_tool 的误报修复）。
		if mtime > entry.timestamp and entry.content_known:
			is_full = entry.offset is None and entry.limit is None
			try:
				disk_content, _, _ = read_text_file(full)
			except OSError:
				disk_content = None
			if not (is_full and disk_content == entry.content):
				return {
					"result": False,
					"message": build_stale_message(
						"File has been modified since read, either by the user or "
						"by a linter. Read it again before attempting to write it.",
						self._cwd,
						full,
						self._session_id,
						entry.content,
						disk_content or "",
					),
					"errorCode": 3,
				}

		return {"result": True}

	def check_permissions(self, input_data: WriteInput, context: Any = None) -> bool:
		return filesystem.check_write_permission_for_tool(self, input_data, context)

	def call(self, input_data: WriteInput) -> WriteOutput:
		full = self.get_path(input_data)
		existed = os.path.exists(full)

		old_content: Optional[str] = None
		encoding = "utf-8"
		if existed:
			try:
				old_content, _endings, encoding = read_text_file(full)
			except OSError:
				old_content = None

			entry = self._read_state.get(full)
			mtime = get_mtime_ms(full)
			if (
				entry is not None
				and mtime > entry.timestamp
				and entry.content_known
			):
				is_full = (
					entry is not None
					and entry.offset is None
					and entry.limit is None
				)
				if not (is_full and old_content == entry.content):
					raise RuntimeError(
						build_stale_message(
							FILE_UNEXPECTEDLY_MODIFIED_ERROR,
							self._cwd,
							full,
							self._session_id,
							entry.content,
							old_content or "",
						)
					)

		# Write 是整文件替换：按模型给出的换行写入（用 LF 规范化）
		content = str(input_data.content)
		journal_warning = self._persist(full, content, encoding=encoding, line_endings="LF")

		normalized = normalize_newlines(content)
		self._read_state.set_written(
			full,
			normalized,
			get_mtime_ms(full),
			self._session_id,
			offset=None,
			limit=None,
		)

		prev = old_content if old_content is not None else ""
		added, removed = _line_diff_counts(prev, normalized)
		return WriteOutput(
			type="update" if (existed and old_content is not None) else "create",
			file_path=input_data.file_path,
			lines_added=added,
			lines_removed=removed,
			old_content=prev,
			new_content=normalized,
			notice=journal_warning,
		)

	@staticmethod
	def map_tool_result_to_content(output: WriteOutput) -> str:
		if output.type == "create":
			msg = f"File created successfully at: {output.file_path}"
		else:
			msg = f"The file {output.file_path} has been updated successfully."
		if output.lines_added or output.lines_removed:
			msg = f"{msg} +{output.lines_added} -{output.lines_removed}"
		diff = format_capped_unified_diff(
			output.old_content,
			output.new_content,
			file_path=output.file_path,
		)
		body = append_diff_fence(msg, diff)
		hint = _diagnostics_hint(output.file_path)
		out = body + hint if hint else body
		if getattr(output, "notice", ""):
			out = f"{out}\n{output.notice}"
		return out

	def parse_input(self, raw: dict[str, Any]) -> WriteInput:
		content = raw.get("content")
		if content is None:
			content_str = ""
		else:
			content_str = content if isinstance(content, str) else str(content)
		return WriteInput(
			file_path=str(raw.get("file_path") or ""),
			content=content_str,
		)

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		write_input = self.parse_input(input)

		validation = self.validate_input(write_input)
		if not validation.get("result"):
			return ToolResult(
				content=str(validation.get("message") or "invalid input"),
				is_error=True,
			)

		if not self.check_permissions(write_input):
			return ToolResult(content="permission denied", is_error=True)

		abort.raise_if_aborted()
		try:
			if self._write_store is not None:
				output = await asyncio.to_thread(self.call, write_input)
			else:
				# 同步磁盘 I/O + 全文 diff——挪线程防冻结事件循环。
				output = await asyncio.to_thread(self.call, write_input)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)

		rewind_context = current_context()
		operation_id: str | None = None
		if rewind_context is not None:
			try:
				record = rewind_context.record_file_mutation(
					tool_name=self.name,
					operation_type="file_write",
					path=self.get_path(write_input),
					old_content=output.old_content,
					new_content=output.new_content,
					existed_before=output.type == "update",
					metadata={"write_type": output.type},
				)
				operation_id = record.operation_id if record is not None else None
			except Exception as e:  # noqa: BLE001
				return ToolResult(
					content=f"file changed but rewind journal failed: {e}",
					is_error=True,
				)

		abort.raise_if_aborted()
		return ToolResult(
			content=self.map_tool_result_to_content(output),
			metadata={"operation_id": operation_id} if operation_id else None,
		)


_DIAG_EXTS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"})


def _diagnostics_hint(file_path: str) -> str:
	ext = os.path.splitext(file_path or "")[1].lower()
	if ext not in _DIAG_EXTS:
		return ""
	return f"\nHint: Diagnostics path={file_path}"
