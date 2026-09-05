"""字面量 trigram 内容索引——加速 ``files_with_matches`` 检索（对齐 Cursor “fast regex search” 的索引思路）。

思路（索引 → 查找 → 验证）：
- 对**纯字面量** pattern（无 regex 元字符、>=4 个字母数字/下划线）建 root 级 trigram 倒排，
  求出“可能包含该字面量”的**候选文件超集**，再由调用方用 ``rg`` 对候选**精确验证**。
  这样把 ``rg`` 的扫描面从全库缩到候选文件，命中稀疏时显著加速，且结果仍是“确切匹配”。
- 仅为 ``files_with_matches`` 且无 ``glob``/``type`` 的索引可用场景服务；其余情况不加速。

安全边界（不改正确性、只失去加速）：
- **fail-open**：建索引 / 查找任何异常、超限、读到不可读文件 → 返回 ``None``，调用方回退全量 ``rg``。
- **完整超集保证（无假阴）**：任一目标文件超出单文件上限、总字节超限、文件数超限 → 直接放弃建索引
  （返回 ``None``）。因此**要么索引覆盖全部（非排除）文件，要么完全不加速**，绝不漏掉文件。
  超大文件/巨型仓库因此自然退化为全量 ``rg``（无收益也无回归）。
- 新鲜度：TTL 内复用，过期重建（与 glob 60s 缓存的“短窗口”取舍一致）；窗口内新建的文件可能未被收录，
  属已知权衡（候选为超集，rg 仍精确验证）。
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict, defaultdict

from tools.fileio.excludes import excluded_dir_globs

_TTL_S = 30.0
# 只对“完全可建索引”的中小型根加速；任一上限触发即放弃（回退全量 rg）。
_MAX_INDEXED_FILES = 20_000
_MAX_INDEXED_BYTES = 64 * 1024 * 1024  # 64 MiB 内容
_SKIP_FILE_BYTES = 2 * 1024 * 1024  # 单文件超 2 MiB → 放弃（保证超集完整性）
_MAX_CACHE_ROOTS = 8

_LITERAL_RE = re.compile(r"^[A-Za-z0-9_]{4,}$")

_lock = threading.Lock()
# root -> (expires_monotonic, ContentIndex | None) ；None 表示“该 root 不可建索引”。
_cache: OrderedDict[str, tuple[float, "ContentIndex | None"]] = OrderedDict()


class ContentIndex:
	"""root 级 trigram 倒排索引：trigram -> set(relpath)。"""

	__slots__ = ("root", "trigrams", "files")

	def __init__(self, root: str, trigrams: dict[str, set[str]], files: list[str]):
		self.root = root
		self.trigrams = trigrams
		self.files = files


def is_literal(pattern: str) -> bool:
	"""是否可用索引进阶的“干净字面量”（仅字母数字/下划线且足够长）。"""
	return bool(pattern and _LITERAL_RE.match(pattern))


def _trigrams(text: str) -> set[str]:
	t = text.lower()
	if len(t) < 3:
		return set()
	return {t[i : i + 3] for i in range(len(t) - 2)}


def _list_roots_files(root: str) -> list[str] | None:
	"""列出 root 下被搜索的文件相对路径（尊重 --hidden + excludes）。失败/异常返回 None。"""
	from tools.fileio.rg_subprocess import run_ripgrep_lines

	cmd = ["rg", "--files", "--hidden"]
	cmd.extend(excluded_dir_globs())
	cmd.append(".")
	try:
		return run_ripgrep_lines(
			cmd,
			cwd=root,
			timeout_seconds=30.0,
			timeout_message=(
				"Content index build timed out after 30 seconds. "
				"Falling back to a direct ripgrep search."
			),
		)
	except Exception:  # noqa: BLE001 — 任何失败都回退全量 rg，不改正确性
		return None


def _build_index(root: str) -> ContentIndex | None:
	all_files = _list_roots_files(root)
	if all_files is None or len(all_files) > _MAX_INDEXED_FILES:
		return None

	trigrams: dict[str, set[str]] = defaultdict(set)
	files: list[str] = []
	total_bytes = 0
	for rel in all_files:
		norm = rel.replace("\\", "/")
		files.append(norm)
		full = os.path.join(root, rel)
		try:
			size = os.path.getsize(full)
		except OSError:
			# 文件消失/不可访问：放弃建索引（避免漏掉），回退全量 rg。
			return None
		if size > _SKIP_FILE_BYTES:
			return None
		total_bytes += size
		if total_bytes > _MAX_INDEXED_BYTES:
			return None
		try:
			with open(full, "r", encoding="utf-8", errors="replace") as f:
				text = f.read()
		except OSError:
			return None  # 读不了 → 放弃（同样为保超集完整性）
		for tg in _trigrams(text):
			trigrams[tg].add(norm)
	return ContentIndex(root, dict(trigrams), files)


def _get_or_build(root: str) -> ContentIndex | None:
	with _lock:
		item = _cache.get(root)
		if item is not None and item[0] >= time.monotonic() and item[1] is not None:
			_cache.move_to_end(root)
			return item[1]
		# 过期或缺失 → 重建；重建结果（含 None）也写入缓存，避免每次重试。
	idx = _build_index(root)
	with _lock:
		_cache[root] = (time.monotonic() + _TTL_S, idx)
		_cache.move_to_end(root)
		while len(_cache) > _MAX_CACHE_ROOTS:
			_cache.popitem(last=False)
	return idx


def lookup(root: str, pattern: str) -> list[str] | None:
	"""返回候选（相对，可含假阳性）；无法加速时返回 ``None``（调用方走全量 rg）。

	候选是“绝对超集”：包含该字面量的文件必在其中（否则必有某个 trigram 缺失）。
	结果仍需由调用方用 ``rg`` 精确验证以获得“确切匹配”。
	"""
	idx = _get_or_build(root)
	if idx is None:
		return None
	tgs = _trigrams(pattern)
	if not tgs:
		return None
	try:
		common: set[str] | None = None
		for tg in tgs:
			s = idx.trigrams.get(tg)
			if s is None:
				return []  # 某 trigram 全库不存在 → 无任何文件可含该字面量 → 零候选
			if common is None:
				common = set(s)
			else:
				common &= s
			if not common:
				return []
		return sorted(common)
	except Exception:  # noqa: BLE001 — 查找异常回退全量 rg
		return None
