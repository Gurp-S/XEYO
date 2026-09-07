"""FileEditTool — 精确字符串编辑（uniqueness / replace_all）。"""

# 写权限：走 permissions.filesystem 路径狱 / 密钥 DENY / 危险 ASK；
# ASK 仅在 registry 已 preapproved 时放行。.ipynb 请用 NotebookEdit。

from __future__ import annotations

import asyncio
import difflib
import os
from dataclasses import dataclass
from typing import Any

from engine.abort import AbortController
from permissions import filesystem
from rewind.context import current_context
from tools.base_tool import ToolResult

from tools.fileio.diff_preview import append_diff_fence, format_capped_unified_diff
from tools.fileio.paths import (
	FILE_NOT_FOUND_CWD_NOTE,
	expand_path,
	find_similar_file,
	suggest_path_under_cwd,
)
from tools.fileio.read_state import ReadFileState
from tools.fileio.text import (
	apply_edit_to_file,
	find_actual_string,
	get_mtime_ms,
	preserve_quote_style,
	read_text_file,
	write_text_file,
)
from tools.fileio.conflict import build_stale_message
from tools.file_edit_tool.prompt import DESCRIPTION, FILE_EDIT_TOOL_NAME

MAX_EDIT_FILE_SIZE = 1024 * 1024 * 1024  # 1 GiB
FILE_UNEXPECTEDLY_MODIFIED_ERROR = (
	"File has been unexpectedly modified. Read it again before attempting to write it."
)


def _coerce_bool(value: Any, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	if isinstance(value, str):
		s = value.strip().lower()
		if s in ("true", "1", "yes", "on"):
			return True
		if s in ("false", "0", "no", "off", ""):
			return False
	return default


def _format_size(n: int) -> str:
	if n >= 1024 * 1024 * 1024:
		return f"{n / (1024 * 1024 * 1024):.2f} GiB"
	if n >= 1024 * 1024:
		return f"{n / (1024 * 1024):.2f} MiB"
	if n >= 1024:
		return f"{n / 1024:.2f} KiB"
	return f"{n} B"


@dataclass
class EditInput:
	file_path: str
	old_string: str
	new_string: str
	replace_all: bool = False


@dataclass
class EditOutput:
	file_path: str
	replace_all: bool
	occurrences: int = 1
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


class FileEditTool:
	name = FILE_EDIT_TOOL_NAME
	search_hint = "modify file contents in place"
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
		"""落盘：无 store -> 直通旁路（与原先完全一致）；有 store -> 经 write_store 校验后写。

		子 Agent（write_scope 已激活）必须经 WriteStore，禁止静默直写。
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
							"The absolute path to the file to modify "
							"(must be absolute, not relative)"
						),
					},
					"old_string": {
						"type": "string",
						"description": "The text to replace",
					},
					"new_string": {
						"type": "string",
						"description": (
							"The text to replace it with (must be different "
							"from old_string)"
						),
					},
					"replace_all": {
						"type": "boolean",
						"description": (
							"Replace all occurrences of old_string "
							"(default false)"
						),
					},
				},
				"required": ["file_path", "old_string", "new_string"],
			},
		}

	def get_path(self, input_data: EditInput) -> str:
		return expand_path(input_data.file_path, cwd=self._cwd)

	_LAST_VALIDATION_ATTRS = (
		"_last_actual_old",
		"_last_encoding",
		"_last_endings",
		"_last_file_content",
	)

	def _clear_validation_cache(self) -> None:
		"""清掉上次校验挂在实例上的跨调用缓存。

		这些属性是 validate→call 的隐式传参；call 失败/中止时不清理，
		残留值会污染下一次调用（例如把上一个文件的内容写进新建文件）。
		"""
		for attr in self._LAST_VALIDATION_ATTRS:
			if hasattr(self, attr):
				delattr(self, attr)

	def validate_input(self, input_data: EditInput) -> dict[str, Any]:
		# 每次校验先重置：保证 call 读到的缓存一定来自本次校验。
		self._clear_validation_cache()
		if not input_data.file_path or not str(input_data.file_path).strip():
			return {
				"result": False,
				"message": "file_path is required",
				"errorCode": 0,
			}

		if input_data.old_string == input_data.new_string:
			return {
				"result": False,
				"message": (
					"No changes to make: old_string and new_string are "
					"exactly the same."
				),
				"errorCode": 1,
			}

		full = self.get_path(input_data)
		if full.lower().endswith(".ipynb"):
			from tools.notebook_edit_tool.prompt import IPYNB_REJECT

			return {
				"result": False,
				"message": IPYNB_REJECT,
				"errorCode": 5,
			}
		if full.startswith("\\\\") or full.startswith("//"):
			return {"result": True}

		file_content: str | None
		encoding = "utf-8"
		endings = "LF"
		try:
			size = os.path.getsize(full)
			if size > MAX_EDIT_FILE_SIZE:
				return {
					"result": False,
					"message": (
						f"File is too large to edit ({_format_size(size)}). "
						f"Maximum editable file size is "
						f"{_format_size(MAX_EDIT_FILE_SIZE)}."
					),
					"errorCode": 10,
				}
			file_content, endings, encoding = read_text_file(full)
		except FileNotFoundError:
			file_content = None
		except OSError as e:
			if getattr(e, "errno", None) == 2 or not os.path.exists(full):
				file_content = None
			else:
				return {"result": False, "message": str(e), "errorCode": 11}

		# 文件不存在
		if file_content is None:
			if input_data.old_string == "":
				return {"result": True}
			suggestion = suggest_path_under_cwd(full, cwd=self._cwd)
			similar = find_similar_file(full)
			message = (
				f"File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {self._cwd}."
			)
			if suggestion:
				message += f" Did you mean {suggestion}?"
			elif similar:
				message += f" Did you mean {similar}?"
			return {"result": False, "message": message, "errorCode": 4}

		# 空 old_string：仅空文件允许（创建内容）
		if input_data.old_string == "":
			if file_content.strip() != "":
				return {
					"result": False,
					"message": "Cannot create new file - file already exists.",
					"errorCode": 3,
				}
			return {"result": True}

		entry = self._read_state.get(full)
		if not entry or entry.is_partial_view:
			return {
				"result": False,
				"message": (
					"File has not been read yet. Read it first before writing to it."
				),
				"errorCode": 6,
			}

		try:
			mtime = get_mtime_ms(full)
		except OSError as e:
			return {"result": False, "message": str(e), "errorCode": 11}

		# content_known=False：sidecar 恢复的条目没有正文快照，"内容对不上"
		# 不能证明被改过；放行，由 old_string 精确匹配兜底。
		if mtime > entry.timestamp and entry.content_known:
			is_full = entry.offset is None and entry.limit is None
			if not (is_full and file_content == entry.content):
				return {
					"result": False,
					"message": build_stale_message(
						"File has been modified since read, either by the user "
						"or by a linter. Read it again before attempting to write it.",
						self._cwd,
						full,
						self._session_id,
						entry.content,
						file_content or "",
					),
					"errorCode": 7,
				}

		actual = find_actual_string(file_content, input_data.old_string)
		if actual is None:
			return {
				"result": False,
				"message": (
					"String to replace not found in file.\n"
					f"String: {input_data.old_string}"
				),
				"errorCode": 8,
			}

		matches = file_content.count(actual)
		if matches > 1 and not input_data.replace_all:
			return {
				"result": False,
				"message": (
					f"Found {matches} matches of the string to replace, but "
					"replace_all is false. To replace all occurrences, set "
					"replace_all to true. To replace only one occurrence, please "
					"provide more context to uniquely identify the instance.\n"
					f"String: {input_data.old_string}"
				),
				"errorCode": 9,
			}

		# 把校验期发现的 actual 挂到临时属性，call 再用（避免二次不一致）
		self._last_actual_old: str | None = actual
		self._last_encoding: str = encoding
		self._last_endings = endings
		self._last_file_content: str = file_content
		return {"result": True}

	def check_permissions(self, input_data: EditInput, context: Any = None) -> bool:
		return filesystem.check_write_permission_for_tool(self, input_data, context)

	def call(self, input_data: EditInput) -> EditOutput:
		full = self.get_path(input_data)

		# 新文件创建：old_string == ""
		if not os.path.exists(full) and input_data.old_string == "":
			journal_warning = self._persist(
				full, input_data.new_string, encoding="utf-8", line_endings="LF"
			)
			self._read_state.set_written(
				full,
				input_data.new_string.replace("\r\n", "\n"),
				get_mtime_ms(full),
				self._session_id,
				offset=None,
				limit=None,
			)
			added, _removed = _line_diff_counts("", input_data.new_string)
			new_norm = input_data.new_string.replace("\r\n", "\n")
			return EditOutput(
				file_path=input_data.file_path,
				replace_all=False,
				occurrences=1,
				lines_added=added,
				lines_removed=0,
				old_content="",
				new_content=new_norm,
				notice=journal_warning,
			)

		# 优先使用 validate 缓存；否则重读
		file_content = getattr(self, "_last_file_content", None)
		encoding = getattr(self, "_last_encoding", "utf-8")
		endings = getattr(self, "_last_endings", "LF")
		if file_content is None:
			file_content, endings, encoding = read_text_file(full)

		entry = self._read_state.get(full)
		mtime = get_mtime_ms(full)
		if entry and mtime > entry.timestamp and entry.content_known:
			is_full = entry.offset is None and entry.limit is None
			if not (is_full and file_content == entry.content):
				raise RuntimeError(
					build_stale_message(
						FILE_UNEXPECTEDLY_MODIFIED_ERROR,
						self._cwd,
						full,
						self._session_id,
						entry.content,
						file_content or "",
					)
				)

		actual_old = getattr(self, "_last_actual_old", None) or find_actual_string(
			file_content, input_data.old_string
		)
		if actual_old is None and input_data.old_string != "":
			raise RuntimeError(
				f"String to replace not found in file.\nString: {input_data.old_string}"
			)
		if actual_old is None:
			actual_old = ""

		actual_new = preserve_quote_style(
			input_data.old_string, actual_old, input_data.new_string
		)

		if actual_old == "":
			updated = actual_new
			occurrences = 1
		else:
			occurrences = file_content.count(actual_old)
			updated = apply_edit_to_file(
				file_content,
				actual_old,
				actual_new,
				replace_all=input_data.replace_all,
			)

		journal_warning = self._persist(
			full, updated, encoding=encoding, line_endings=endings  # type: ignore[arg-type]
		)

		self._read_state.set_written(
			full,
			updated,
			get_mtime_ms(full),
			self._session_id,
			offset=None,
			limit=None,
		)

		# 清理校验缓存
		self._clear_validation_cache()

		added, removed = _line_diff_counts(file_content, updated)
		return EditOutput(
			file_path=input_data.file_path,
			replace_all=input_data.replace_all,
			occurrences=occurrences if input_data.replace_all else 1,
			lines_added=added,
			lines_removed=removed,
			old_content=file_content,
			new_content=updated,
			notice=journal_warning,
		)

	@staticmethod
	def map_tool_result_to_content(output: EditOutput) -> str:
		if output.replace_all:
			msg = (
				f"The file {output.file_path} has been updated. "
				"All occurrences were successfully replaced."
			)
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

	def parse_input(self, raw: dict[str, Any]) -> EditInput:
		old = raw.get("old_string")
		new = raw.get("new_string")
		return EditInput(
			file_path=str(raw.get("file_path") or ""),
			old_string="" if old is None else (old if isinstance(old, str) else str(old)),
			new_string="" if new is None else (new if isinstance(new, str) else str(new)),
			replace_all=_coerce_bool(raw.get("replace_all"), False),
		)

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		edit_input = self.parse_input(input)

		validation = self.validate_input(edit_input)
		if not validation.get("result"):
			return ToolResult(
				content=str(validation.get("message") or "invalid input"),
				is_error=True,
			)

		if not self.check_permissions(edit_input):
			return ToolResult(content="permission denied", is_error=True)

		abort.raise_if_aborted()
		existed_before = os.path.exists(self.get_path(edit_input))
		try:
			if self._write_store is not None:
				output = await asyncio.to_thread(self.call, edit_input)
			else:
				# 同步磁盘 I/O + 全文 diff——挪线程防冻结事件循环。
				output = await asyncio.to_thread(self.call, edit_input)
		except Exception as e:  # noqa: BLE001
			# call 失败也要清缓存：残留的 _last_* 属于上一次校验，
			# 可能污染下一次调用（跨文件内容写入）。
			self._clear_validation_cache()
			return ToolResult(content=str(e), is_error=True)

		rewind_context = current_context()
		operation_id: str | None = None
		if rewind_context is not None:
			try:
				record = rewind_context.record_file_mutation(
					tool_name=self.name,
					operation_type="file_edit",
					path=self.get_path(edit_input),
					old_content=output.old_content,
					new_content=output.new_content,
					existed_before=existed_before,
					metadata={
						"replace_all": output.replace_all,
						"occurrences": output.occurrences,
					},
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
