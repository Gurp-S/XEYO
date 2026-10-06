"""工具结果尺寸侧修剪（旁路候选；**尚未接入生产主链**）。

要解决的问题有数：本工作区未压缩段的 `tool_result_size` median **279,250 字符**、
98% 的枪 >10k 字符 ⇒ 一条巨型工具结果被逐字重发上百次。WSC 现在只有"整段折成头"
这一条路，尺寸侧零治理。

形态取自 DeepSeek harness 的同名机制（`D:\\lea\\dsh-src\\packages\\compaction\\
compaction-tool-result-pruner\\src\\config.ts`）：超阈值的工具结果只留
**头 4096 + 标记 + 尾 1024**，并在加载期硬校验"头 + 标记 + 尾 ≤ 阈值"⇒
**修剪必然变小，不可能反向膨胀**。

两条边界（顾问裁定，别忘）：
- 固定头/尾会**删掉中间的错误、接口、约束**。所以修剪只在"完整原文已进冷层归档、
  且入口可用"的前提下才安全——可恢复性由 `tests/wsc/_recovery_contract.py` 那套合同判，
  不由本模块判。
- 是否伤害后续执行，要由题库（`evals/wsc_context_bank.py`）与真实续做验证，
  **不能只看头变小了多少**。
"""

from __future__ import annotations

import os

#: 标记文本。刻意与 dsh 的 `PRUNE_MARKER` 同形（中性结果型措辞，不含建议/评价，
#: 符合 AGENTS.md 引擎铁律"注意力里只出现信息，不出现导演"）。
PRUNE_MARKER = "\n\n[... tool result middle pruned ...]\n\n"

#: 默认预算（字符，按 Unicode 码点计，不按 UTF-16 单元 ⇒ 不劈开代理对）。
THRESHOLD_CHARS = 8192
HEAD_CHARS = 4096
TAIL_CHARS = 1024


def _validate(threshold: int, head: int, tail: int) -> None:
	"""加载期硬校验：修剪后的发射面必须严格小于阈值，否则这道门是反向的。"""
	emitted = head + len(PRUNE_MARKER) + tail
	if threshold <= 0:
		raise ValueError(f"threshold_chars must be positive, got {threshold}")
	if head < 0 or tail < 0:
		raise ValueError("head_chars / tail_chars must be non-negative")
	if emitted > threshold:
		raise ValueError(
			f"head_chars + marker + tail_chars ({emitted}) must be at most "
			f"threshold_chars ({threshold})"
		)


def code_point_length(text: str) -> int:
	"""按 Unicode 码点数长度（`Array.from(text).length` 的 Python 等价）。"""
	return len(text)


def prune_tool_result(text: str, *, threshold_chars: int = THRESHOLD_CHARS,
                      head_chars: int = HEAD_CHARS, tail_chars: int = TAIL_CHARS) -> str:
	"""超阈值的工具结果 ⇒ 头 + 标记 + 尾；不超阈值原样返回。

	返回值长度**恒 ≤ 原长度**（由 `_validate` 保证），所以调用方不需要再判"越修越大"。
	"""
	_validate(threshold_chars, head_chars, tail_chars)
	total = code_point_length(text)
	if total <= threshold_chars:
		return text
	removed_end = total - tail_chars
	keep = text[:head_chars] + PRUNE_MARKER + (text[removed_end:] if removed_end > head_chars else "")
	return keep


def prune_stats(text: str, *, threshold_chars: int = THRESHOLD_CHARS,
                head_chars: int = HEAD_CHARS, tail_chars: int = TAIL_CHARS) -> dict[str, int]:
	"""一次修剪的账（旁路观测用，不参与决策）。"""
	pruned = prune_tool_result(text, threshold_chars=threshold_chars,
	                           head_chars=head_chars, tail_chars=tail_chars)
	return {"before_chars": code_point_length(text), "after_chars": code_point_length(pruned),
	        "removed_chars": code_point_length(text) - code_point_length(pruned),
	        "applied": int(pruned != text)}


#: 旗标（env 权威，默认关⇒生产逐字节不变）。开=替换 C0 截断，见 `maybe_prune_with_archive`。
ENV = "XEYO_WSC_SIZE_PRUNE"


def enabled() -> bool:
	"""旗标唯一判据（与注册表同一份 `env_flag`，不留两套读法）。"""
	try:
		from memory.memory_switches import env_flag

		return bool(env_flag(ENV))
	except Exception:  # noqa: BLE001 — 读不到就当关（改动前行为）
		return False


def maybe_prune_with_archive(
	raw: str,
	*,
	msg_idx: int,
	uid: str,
	cwd: str | os.PathLike[str] | None = None,
	threshold_chars: int = THRESHOLD_CHARS,
	head_chars: int = HEAD_CHARS,
	tail_chars: int = TAIL_CHARS,
) -> tuple[str, str | None]:
	"""把超阈工具结果换成「头 + 标记 + 尾 + Read 取回句柄」，并归档原文。

	⚠️ 实测更正（10-04）：本档**不是"C0 的更小版本"**——C0 的 `8192/4096/1024` 与这里的
	默认档同形（实测单条 30k 结果：C0 出 5,135 字符，本档 5,231 = 5,145 + 句柄）。
	唯一的增量价值是**可恢复**：C0 截掉的中间段没有任何取回入口。要让尺寸真的变小，
	必须调小 `head_chars`/`tail_chars`（头 4096+尾 1024 是 DSH 的取值，不是我们的最优点）——
	而"敢调小"的前提正是这条句柄先存在。

	三条边界（顺序即优先级）：
	1. **落盘失败 ⇒ 原样返回**：拿不回的修剪比不修剪糟得多（fail-open 到改动前行为）。
	2. 返回值长度恒 ≤ 原长：`_validate` 的加载期约束 + 这里再断言一次，绝不反向膨胀。
	3. 引用形态复用 `memory.offload.ref_path_for`（工作区相对优先，分隔符恒 `/`），
	   与冷层视图、L3 offload 同一套引用规则，不新造第三种。

	返回 ``(投影文本, 归档路径或 None)``。
	"""
	text = str(raw or "")
	if code_point_length(text) <= int(threshold_chars):
		return text, None
	import re

	from memory.offload import RETRIEVE_PAGE_LINES, _offload_root, ref_path_for

	try:
		safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(uid or "x"))[:40]
		path = _offload_root(cwd) / "prune" / f"{int(msg_idx)}_{safe}.tool.txt"
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(text, encoding="utf-8")
	except Exception:  # noqa: BLE001 — 归档失败 ⇒ 不修剪（见边界 1）
		return text, None
	lines = text.count("\n") + (1 if text else 0)
	# 回读指针必须指向**被剪掉的中段**：原先给 `offset=1` 等于把模型送回它已经看过的
	# 头部（实测照做一次才发现那儿没有缺的内容，还得再猜一次偏移）。按发射面反推
	# 被剪区间的行号区间——指针与"缺了什么"对齐，一次到位。
	start_line = text[:head_chars].count("\n") + 1
	end_line = max(start_line, text[: max(0, len(text) - tail_chars)].count("\n"))
	page = min(RETRIEVE_PAGE_LINES, max(1, end_line - start_line + 1))
	entry = (
		f" | 全文: Read(file_path='{ref_path_for(path, cwd)}', "
		f"offset={start_line}, limit={page})"
		f" | 被剪区间: 第 {start_line}-{end_line} 行 / 全文 {lines} 行"
	)
	pruned = prune_tool_result(
		text, threshold_chars=threshold_chars, head_chars=head_chars, tail_chars=tail_chars
	) + entry
	if code_point_length(pruned) > code_point_length(text):
		return text, str(path)
	return pruned, str(path)
