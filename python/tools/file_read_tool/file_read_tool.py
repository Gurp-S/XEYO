"""FileReadTool — 读取文件（文本核心 + XEYO schema/execute）。"""

# 读权限：走 permissions.filesystem 路径狱 / 密钥 DENY / 危险 ASK；
# ASK 仅在 registry 已 preapproved 时放行。
# TODO: [token] API 级 token 计数（现用 chars/4 粗估）

from __future__ import annotations

import json
import asyncio
import os
from tools.fileio import fsprobe as _fsprobe
from tools.container_fs import display_cwd as _cfs_display_cwd
from dataclasses import dataclass
from typing import Any, Optional

from engine.abort import AbortController
from engine.aging import aging_enabled
from permissions import filesystem
from tools.base_tool import ToolResult
from codeindex.symbols import locate_all
from tools.fileio.paths import (
	FILE_NOT_FOUND_CWD_NOTE,
	expand_path,
	find_similar_file,
	suggest_path_under_cwd,
)
from tools.fileio.read_state import FileStateEntry, ReadFileState
from tools.fileio.text import add_line_numbers, get_mtime_ms, read_text_file
from tools.file_read_tool.prompt import (
	DESCRIPTION_TEXT,
	DESCRIPTION_VISION,
	FILE_READ_TOOL_NAME,
	FILE_UNCHANGED_STUB,
	MAX_LINES_TO_READ,
)

# 上限 0.25 MiB
MAX_SIZE_BYTES = int(0.25 * 1024 * 1024)
DEFAULT_MAX_TOKENS = 25_000


def _is_externalized(path: str, cwd: str | None = None) -> bool:
	"""路径是否属于外部化内容（offload / 冷层取回视图）——决定要不要记 read-state。

	**必须传自己的工作区**（不是进程 cwd）：offload 根默认 ``<cwd>/.xeyo_offload``。
	懒 import + fail-open：`memory` 不可用时按「非外部化」处理（= 旧行为，方向安全）。
	"""
	try:
		from memory.offload import is_externalized_path

		return bool(is_externalized_path(path, cwd))
	except Exception:  # noqa: BLE001
		return False

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
BINARY_EXTENSIONS = frozenset(
	{
		"exe",
		"dll",
		"so",
		"dylib",
		"bin",
		"o",
		"a",
		"class",
		"pyc",
		"pyo",
		"zip",
		"tar",
		"gz",
		"7z",
		"rar",
		"wasm",
		"pdf",
		"doc",
		"docx",
		"xls",
		"xlsx",
		"ppt",
		"pptx",
		"woff",
		"woff2",
		"ttf",
		"otf",
		"mp3",
		"mp4",
		"mov",
		"avi",
		"mkv",
		"ico",
	}
)

BLOCKED_DEVICE_PATHS = frozenset(
	{
		"/dev/zero",
		"/dev/random",
		"/dev/urandom",
		"/dev/full",
		"/dev/stdin",
		"/dev/tty",
		"/dev/console",
		"/dev/stdout",
		"/dev/stderr",
		"/dev/fd/0",
		"/dev/fd/1",
		"/dev/fd/2",
	}
)


def _is_blocked_device(path: str) -> bool:
	if path in BLOCKED_DEVICE_PATHS:
		return True
	if path.startswith("/proc/") and (
		path.endswith("/fd/0") or path.endswith("/fd/1") or path.endswith("/fd/2")
	):
		return True
	return False


def _rough_token_estimate(content: str) -> int:
	return max(1, len(content) // 4) if content else 0


def _coerce_optional_int(value: Any) -> int | None:
	if value is None or value == "":
		return None
	if isinstance(value, bool):
		return int(value)
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)
	if isinstance(value, str):
		s = value.strip()
		if not s:
			return None
		try:
			return int(float(s))
		except ValueError:
			return None
	return None


@dataclass
class ReadInput:
	file_path: str
	offset: Optional[int] = None
	limit: Optional[int] = None
	symbol: Optional[str] = None
	pack: bool = False


@dataclass
class ReadOutput:
	type: str  # text | file_unchanged
	file_path: str
	content: str = ""
	start_line: int = 1
	total_lines: int = 0
	symbol_meta: Optional[dict] = None


def prompt(*, vision: bool = False) -> str:
	return (DESCRIPTION_VISION if vision else DESCRIPTION_TEXT).strip()


class FileReadTool:
	name = FILE_READ_TOOL_NAME
	search_hint = "read file contents from disk"
	max_result_size_chars = 100_000

	def __init__(
		self,
		*,
		cwd: str = ".",
		read_state: ReadFileState | None = None,
	) -> None:
		self._cwd = os.path.abspath(cwd or ".")
		self._read_state = read_state or ReadFileState()
		# 会话构建时按厂商/模型能力注入；默认关（文本-only）
		self._vision_enabled = False

	def set_read_file_state(self, state: ReadFileState) -> None:
		self._read_state = state

	def set_vision_enabled(self, enabled: bool) -> None:
		"""按需开启图片/PDF 读；须在会话 registry 构建时设定（勿中途改 schema）。"""
		self._vision_enabled = bool(enabled)

	@property
	def vision_enabled(self) -> bool:
		return self._vision_enabled

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		desc = DESCRIPTION_VISION if self._vision_enabled else DESCRIPTION_TEXT
		props: dict[str, Any] = {
			"file_path": {
				"type": "string",
				"description": (
					"Absolute path to the file to read."
				),
			},
			"offset": {
				"type": "integer",
				"description": (
					"Text: start line (1-indexed). "
					"PDF (vision): page number (1-indexed). "
					"Optional; omitted value starts at the first page."
				)
				if self._vision_enabled
				else (
					"Line number to start reading from (1-indexed)."
				),
			},
			"limit": {
				"type": "integer",
				"description": (
					"Number of lines to read."
				),
			},
			"symbol": {
				"type": "string",
				"description": (
					'When set, returns one symbol\'s body, e.g. '
					'"MyClass.handle_request" or "query_loop". '
					"pack=true includes same-file context. "
					"Cannot be combined with offset/limit."
				),
			},
			"pack": {
				"type": "boolean",
				"description": (
					"With symbol: includes same-file docstring, used imports, "
					"callee/caller signatures (budget-capped). "
					"Ignored without symbol. Cannot combine with offset/limit."
				),
			},
		}
		return {
			"name": self.name,
			"description": desc.strip(),
			"input_schema": {
				"type": "object",
				"properties": props,
				"required": ["file_path"],
			},
		}

	def get_path(self, input_data: ReadInput) -> str:
		return expand_path(input_data.file_path, cwd=self._cwd)

	def validate_input(self, input_data: ReadInput) -> dict[str, Any]:
		if not input_data.file_path or not str(input_data.file_path).strip():
			return {
				"result": False,
				"message": "file_path is required",
				"errorCode": 0,
			}

		full = self.get_path(input_data)
		if full.startswith("\\\\") or full.startswith("//"):
			return {"result": True}

		ext = os.path.splitext(full)[1].lower().lstrip(".")
		if ext in IMAGE_EXTENSIONS:
			if not self._vision_enabled:
				return {
					"result": False,
					"message": (
						f"Read is text-only for this model: cannot read image .{ext}. "
						"Vision-capable models and Screenshot support image content."
					),
					"errorCode": 4,
				}
			return {"result": True}
		if ext == "pdf":
			if not self._vision_enabled:
				return {
					"result": False,
					"message": (
						"Read is text-only for this model: cannot read PDF. "
						"Vision-capable models and rendered PNG pages support PDF content."
					),
					"errorCode": 4,
				}
			return {"result": True}
		if ext in BINARY_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
			return {
				"result": False,
				"message": (
					f"Read is text-only: cannot read binary .{ext} files "
					"(Office/archives); external readers support these files."
				),
				"errorCode": 4,
			}

		if _is_blocked_device(full.replace("\\", "/")):
			return {
				"result": False,
				"message": (
					f"Cannot read '{input_data.file_path}': this device file "
					"would block or produce infinite output."
				),
				"errorCode": 9,
			}

		if input_data.offset is not None and input_data.offset < 0:
			return {
				"result": False,
				"message": "offset must be >= 0 (0 and 1 both mean start of file)",
				"errorCode": 5,
			}
		if input_data.limit is not None and input_data.limit <= 0:
			return {
				"result": False,
				"message": "limit must be a positive integer",
				"errorCode": 6,
			}

		if input_data.symbol:
			if input_data.offset is not None or input_data.limit is not None:
				return {
					"result": False,
					"message": (
						"symbol cannot be combined with offset/limit; "
						"symbol selects one symbol body"
					),
					"errorCode": 5,
				}
			ext = os.path.splitext(full)[1].lower().lstrip(".")
			if ext in IMAGE_EXTENSIONS or ext in BINARY_EXTENSIONS or ext == "pdf":
				return {
					"result": False,
					"message": (
						f"symbol is only supported for text source files, not .{ext}"
					),
					"errorCode": 4,
				}
		elif input_data.pack:
			return {
				"result": False,
				"message": "pack requires symbol; pass symbol with pack=true",
				"errorCode": 5,
			}

		return {"result": True}

	def check_permissions(self, input_data: ReadInput, context: Any = None) -> bool:
		return filesystem.check_read_permission_for_tool(self, input_data, context)

	def call(self, input_data: ReadInput) -> ReadOutput:
		full = self.get_path(input_data)
		# offset 默认 1；0/1 都视为文件开头
		offset = 1 if input_data.offset is None else max(1, input_data.offset)
		if input_data.offset == 0:
			offset = 1
		limit = input_data.limit

		# 去重：同路径同 range 且 mtime 未变 → stub
		# 老化开启时跳过去重（R1）：unchanged-stub 会指向可能已被老化清除的
		# 早期读取结果，模型无从参照——宁可真读，不可悬空引用。
		# symbol 读取绕过去重：目标 range 不同于任何全文件/分页记录。
		existing = self._read_state.get(full)
		if (
			existing
			and input_data.symbol is None
			and not aging_enabled()
			and not existing.is_partial_view
			and existing.offset is not None
			and existing.offset == offset
			and existing.limit == limit
		):
			try:
				if get_mtime_ms(full) == existing.timestamp:
					return ReadOutput(type="file_unchanged", file_path=input_data.file_path)
			except OSError:
				pass

		# 容器路由（2026-09-16）：工作面在容器里时，存在性/目录判定必须问容器。
		# 用宿主 os.path 判定会把 /app/x 规范化成 D:\app\x，然后报"文件不存在"——
		# 而文件明明在容器里（模型据此以为整个路径都错了）。
		_routed = ""
		try:
			from tools.container_fs import active_container as _ac

			_routed = _ac()
		except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
			_routed = ""
		if _routed:
			from tools.container_fs import exists as _cfs_exists
			from tools.container_fs import is_dir as _cfs_isdir

			if _cfs_exists(full) is False:
				raise FileNotFoundError(
					f"File does not exist in the container: {input_data.file_path}"
				)
			if _cfs_isdir(full) is True:
				raise IsADirectoryError(
					f"Path is a directory, not a file: {input_data.file_path}"
				)
		elif not _fsprobe.exists(full):
			suggestion = suggest_path_under_cwd(full, cwd=self._cwd)
			similar = find_similar_file(full)
			message = (
				f"File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {_cfs_display_cwd(self._cwd)}."
			)
			if suggestion:
				message += f" Nearest existing path: {suggestion}."
			elif similar:
				message += f" Nearest existing path: {similar}."
			raise FileNotFoundError(message)

		if not _routed and _fsprobe.isdir(full):
			raise IsADirectoryError(
				f"Path is a directory, not a file: {input_data.file_path}"
			)

		ext = os.path.splitext(full)[1].lower().lstrip(".")
		if ext in IMAGE_EXTENSIONS:
			if not self._vision_enabled:
				raise RuntimeError(
					f"Image file '.{ext}' detected. Read vision is disabled for this "
					"model; Screenshot and external readers support image content."
				)
			raise RuntimeError("__VISION_IMAGE__")  # execute 分支处理
		if ext == "pdf":
			if not self._vision_enabled:
				raise RuntimeError(
					"PDF detected. Read vision is disabled for this model; rendered "
					"PNG pages and vision-capable models support PDF content."
				)
			raise RuntimeError("__VISION_PDF__")
		if ext in BINARY_EXTENSIONS:
			raise RuntimeError(
				f"Binary/non-text file '.{ext}' is not supported by Read "
				"(text-only); external readers support Office/archives."
			)

		try:
			size = _fsprobe.getsize(full)
		except OSError as e:
			raise RuntimeError(f"Cannot stat file: {e}") from e

		# symbol 读取先定位（不受整文件大小预检限制——返回的只是符号体）
		sym = None
		if input_data.symbol:
			candidates = locate_all(full, input_data.symbol)
			if not candidates:
				raise RuntimeError(
					f"Symbol '{input_data.symbol}' not found in "
					f"{input_data.file_path}. Grep output_mode=\"symbols\" "
					"returns symbol names."
				)
			if len(candidates) > 1:
				listing = "\n".join(
					f"  - {s.kind} {s.name}"
					f"{' (in ' + s.parent + ')' if s.parent else ''}"
					f" lines {s.start}-{s.end}: {s.signature}"
					for s in candidates[:8]
				)
				raise RuntimeError(
					f"Symbol '{input_data.symbol}' is ambiguous "
					f"({len(candidates)} matches). A qualified path such as "
					f"'ClassName.method':\n{listing}"
				)
			sym = candidates[0]

		if size > MAX_SIZE_BYTES and limit is None and sym is None:
			raise RuntimeError(
				f"File content ({size} bytes) exceeds maximum allowed size "
				f"({MAX_SIZE_BYTES} bytes). offset and limit parameters select "
				"specific portions; Grep exposes content search."
			)

		content, _endings, _enc = read_text_file(full)

		# .ipynb：完整 JSON 存入 read_state；返回 cell 索引摘要。
		if ext == "ipynb":
			mtime = get_mtime_ms(full)
			self._read_state.set(
				full,
				FileStateEntry(
					content=content,
					timestamp=mtime,
					offset=None,
					limit=None,
				),
			)
			summary = _notebook_cell_summary(content, input_data.file_path)
			return ReadOutput(
				type="text",
				file_path=input_data.file_path,
				content=summary,
				start_line=1,
				total_lines=summary.count("\n") + 1,
			)

		all_lines = content.split("\n")
		total_lines = len(all_lines) if content else 0

		symbol_meta: Optional[dict] = None
		if sym is not None:
			if input_data.pack:
				from codeindex.pack import pack_symbol_context

				packed = pack_symbol_context(
					full, target=sym, source_lines=all_lines
				)
				slice_text = packed.text
				start_line_out = 1
				symbol_meta = {
					"symbol": sym.name,
					"kind": sym.kind,
					"range": [sym.start, sym.end],
					"approximate": sym.approximate,
					"truncated": packed.truncated,
					"pack_sections": list(packed.sections),
				}
			else:
				sliced = all_lines[sym.start - 1 : sym.end]
				slice_text = "\n".join(sliced)
				start_line_out = sym.start
				symbol_meta = {
					"symbol": sym.name,
					"kind": sym.kind,
					"range": [sym.start, sym.end],
					"approximate": sym.approximate,
				}
		else:
			# offset 从 1 开始计数
			start_idx = max(0, offset - 1)
			effective_limit = MAX_LINES_TO_READ if limit is None else limit
			sliced = all_lines[start_idx : start_idx + effective_limit]
			slice_text = "\n".join(sliced)
			start_line_out = offset

		tokens = _rough_token_estimate(slice_text)
		if tokens > DEFAULT_MAX_TOKENS:
			raise RuntimeError(
				f"File content ({tokens} tokens) exceeds maximum allowed tokens "
				f"({DEFAULT_MAX_TOKENS}). offset and limit parameters select "
				"specific portions; content search returns matching sections."
			)

		mtime = get_mtime_ms(full)
		# 外部化内容（offload 落地文件 / WSC 冷层取回视图）**不记 read-state**：
		# ① 它不是模型在编辑的对象，记进去只会占 `ReadFileState` 的 LRU 槽位，
		#    把正在编辑的真文件快照挤掉——而那份快照是写前新鲜度校验的依据；
		# ② 同一 path+offset+limit 重复读会返回 `FILE_UNCHANGED_STUB` 顶掉正文，
		#    而取回语义要求每次都给正文。
		# 判定走 `memory.offload.is_externalized_path`（按 offload 根前缀，见其 docstring）。
		if not _is_externalized(full, self._cwd):
			self._read_state.set(
				full,
				FileStateEntry(
					content=content,
					timestamp=mtime,
					offset=start_line_out if symbol_meta is None else None,
					limit=None if symbol_meta is not None else limit,
				),
			)

		return ReadOutput(
			type="text",
			file_path=input_data.file_path,
			content=slice_text,
			start_line=start_line_out,
			total_lines=total_lines,
			symbol_meta=symbol_meta,
		)

	@staticmethod
	def map_tool_result_to_content(output: ReadOutput) -> str:
		if output.type == "file_unchanged":
			return FILE_UNCHANGED_STUB
		if output.content:
			return add_line_numbers(output.content, start_line=output.start_line)
		if output.total_lines == 0:
			return (
				"<system-reminder>Warning: the file exists but the contents "
				"are empty.</system-reminder>"
			)
		return (
			f"<system-reminder>Warning: the file exists but is shorter than "
			f"the provided offset ({output.start_line}). The file has "
			f"{output.total_lines} lines.</system-reminder>"
		)

	def parse_input(self, raw: dict[str, Any]) -> ReadInput:
		pack_raw = raw.get("pack")
		pack = pack_raw is True or (
			isinstance(pack_raw, str) and pack_raw.strip().lower() in {"1", "true", "yes"}
		)
		return ReadInput(
			file_path=str(raw.get("file_path") or ""),
			offset=_coerce_optional_int(raw.get("offset")),
			limit=_coerce_optional_int(raw.get("limit")),
			symbol=(str(raw.get("symbol")).strip() or None) if raw.get("symbol") else None,
			pack=pack,
		)

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		abort.raise_if_aborted()
		read_input = self.parse_input(input)

		validation = self.validate_input(read_input)
		if not validation.get("result"):
			return ToolResult(
				content=str(validation.get("message") or "invalid input"),
				is_error=True,
			)

		if not self.check_permissions(read_input):
			return ToolResult(content="permission denied", is_error=True)

		abort.raise_if_aborted()
		full = self.get_path(read_input)
		ext = os.path.splitext(full)[1].lower().lstrip(".")

		# Vision 路径：图片 / PDF（会话级 set_vision_enabled）
		if self._vision_enabled and ext in IMAGE_EXTENSIONS:
			return await asyncio.to_thread(self._execute_image, full, read_input)
		if self._vision_enabled and ext == "pdf":
			return await asyncio.to_thread(self._execute_pdf, full, read_input)

		try:
			# 同步磁盘 I/O（图像/PDF 解码更重）——挪线程防冻结事件循环。
			output = await asyncio.to_thread(self.call, read_input)
		except RuntimeError as e:
			msg = str(e)
			if msg in ("__VISION_IMAGE__", "__VISION_PDF__"):
				# call 里哨兵；正常应由上面分支处理
				return ToolResult(content=msg, is_error=True)
			return ToolResult(content=msg, is_error=True)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=str(e), is_error=True)

		abort.raise_if_aborted()
		result = ToolResult(content=self.map_tool_result_to_content(output))
		if output.symbol_meta:
			meta = dict(output.symbol_meta)
			kind = "symbol_pack" if "pack_sections" in meta else "symbol"
			result.metadata = {"read_kind": kind, **meta}
		return result

	def _execute_image(self, full: str, read_input: ReadInput) -> ToolResult:
		from media_store import MediaError
		from tools.file_read_tool.vision_media import compress_image_for_llm

		try:
			# 容器路由（2026-09-16）：图片字节也必须从**容器**取——直读宿主
			# 路径在评测里必然 FileNotFoundError（图在容器里）。
			from tools.container_fs import active_container as _ac
			from tools.container_fs import read_bytes as _cfs_read_bytes

			if _ac():
				raw = _cfs_read_bytes(full)
				if raw is None:
					return ToolResult(
						content=f"Cannot read image (container): {full}", is_error=True
					)
			else:
				with open(full, "rb") as fh:
					raw = fh.read()
			data_url, meta = compress_image_for_llm(raw)
		except MediaError as e:
			return ToolResult(content=str(e), is_error=True)
		except OSError as e:
			return ToolResult(content=f"Cannot read image: {e}", is_error=True)
		return ToolResult(
			content=(
				f"Image {read_input.file_path} "
				f"({meta.get('width')}x{meta.get('height')}, "
				f"{meta.get('encoded_bytes')} bytes encoded). "
				"See attached vision image."
			),
			images=[data_url],
			metadata={"read_kind": "image", **meta},
		)

	def _execute_pdf(self, full: str, read_input: ReadInput) -> ToolResult:
		from tools.file_read_tool.vision_media import read_pdf_for_llm

		page = 1 if read_input.offset is None else max(1, int(read_input.offset))
		try:
			summary, images, meta = read_pdf_for_llm(full, page=page)
		except Exception as e:  # noqa: BLE001
			return ToolResult(content=f"PDF read failed: {e}", is_error=True)
		return ToolResult(
			content=summary,
			images=images or None,
			metadata={"read_kind": "pdf", **meta},
		)


def _notebook_cell_summary(raw: str, file_path: str) -> str:
	"""Compact cell index for the model; full JSON stays in read_state."""
	try:
		nb = json.loads(raw)
	except json.JSONDecodeError as e:
		return f"Invalid notebook JSON in {file_path}: {e}"
	cells = nb.get("cells") if isinstance(nb, dict) else None
	if not isinstance(cells, list):
		return f"Invalid notebook (no cells list): {file_path}"
	lines = [
		f"Notebook {file_path}: {len(cells)} cells "
		f"(nbformat {nb.get('nbformat', '?')}). "
		"NotebookEdit addresses cells by cell_idx.",
	]
	for i, cell in enumerate(cells):
		if not isinstance(cell, dict):
			lines.append(f"[{i}] ?")
			continue
		ctype = str(cell.get("cell_type") or "?")
		src = cell.get("source")
		if isinstance(src, list):
			text = "".join(str(x) for x in src)
		else:
			text = str(src or "")
		preview = text.strip().replace("\n", "\\n")
		if len(preview) > 80:
			preview = preview[:80] + "…"
		lines.append(f"[{i}] {ctype}: {preview or '(empty)'}")
	out = "\n".join(lines)
	if len(out) > 16_000:
		return out[:16_000] + "\n… truncated"
	return out
