"""L5 摘要记忆：送模型投影（不改 MessageStore / JSONL）。

设计见 docs/10-完整记忆体系.md §3.5 与 §4（C0/C1）。
C0 截断始终做；C1 占位按 frozen_until 应用（runtime 按公式推进冻结边界），
本函数不自行决定窗口，保证两次 C1/C2 之间投影字节稳定。C2 由 runtime 处理。
"""

from __future__ import annotations

import os
from typing import Any

from engine.aging import (
    FOLD_AFTER,
    aging_enabled,
    build_stub,
    record_stub,
    should_exempt,
)

# ====== 配置常量 ======
# tool_result 内容的最大字符数，超过则截断。从 16k 收紧到 8k
# （thresholdChars=8192，头/尾各保留 4k/1k 量级），短会话单条工具结果成本减半。
MAX_TOOL_RESULT_CHARS = 8_192
KEEP_TAIL_MESSAGES = 6              # 兼容旧名：等价于保留约 N 条消息的尾部保护区
KEEP_TAIL_TOOL_ROUNDS = 3           # 按「assistant(tool_calls)+连续 tool」成对区间保留的轮数
TRUNCATE_SUFFIX = "\n…[truncated]"  # 截断时追加的后缀


def _assistant_tool_ids(msg: dict[str, Any]) -> list[str]:
	ids: list[str] = []
	content = msg.get("content")
	if isinstance(content, list):
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_use":
				continue
			uid = str(block.get("id") or "")
			if uid:
				ids.append(uid)
	calls = msg.get("tool_calls")
	if isinstance(calls, list):
		for call in calls:
			if not isinstance(call, dict):
				continue
			uid = str(call.get("id") or "")
			if uid:
				ids.append(uid)
	return ids


def _tool_result_ids(msg: dict[str, Any]) -> list[str]:
	ids: list[str] = []
	role = msg.get("role")
	if role == "tool":
		tid = str(msg.get("tool_call_id") or "")
		if tid:
			ids.append(tid)
	content = msg.get("content")
	if isinstance(content, list):
		for block in content:
			if not isinstance(block, dict) or block.get("type") != "tool_result":
				continue
			uid = str(block.get("tool_use_id") or "")
			if uid:
				ids.append(uid)
	return ids


def tool_pair_ranges(messages: list[dict[str, Any]]) -> list[tuple[int, int]]:
	"""assistant(tool_calls) → 连续 tool 结果的半开区间列表。"""
	ranges: list[tuple[int, int]] = []
	i = 0
	n = len(messages)
	while i < n:
		ids = _assistant_tool_ids(messages[i])
		if not ids:
			i += 1
			continue
		j = i + 1
		while j < n and _tool_result_ids(messages[j]):
			j += 1
		ranges.append((i, j))
		i = j
	return ranges


def _keep_tail_rounds() -> int:
	"""保尾 K（会话期固定：env 读一次即冻结，字节稳定不因工具轮变化跳变）。"""
	try:
		return max(1, int(os.environ.get("XEYO_KEEP_TAIL_ROUNDS", "") or KEEP_TAIL_TOOL_ROUNDS))
	except (TypeError, ValueError):
		return KEEP_TAIL_TOOL_ROUNDS


def keep_tail_cut(
	messages: list[dict[str, Any]],
	*,
	tool_rounds: int | None = None,
	fallback_messages: int | None = None,
) -> int:
	"""计算尾部保护区起点：优先按最近 ``tool_rounds`` 个成对工具轮。

	无工具轮时退回 ``len - fallback_messages``（旧 KEEP_TAIL_MESSAGES 行为）。
	返回的下标是「保护区起点」= 可冻结边界候选（不含尾部）。
	Link②②：K 默认 3，可用 ``XEYO_KEEP_TAIL_ROUNDS`` 覆盖（会话期固定）。
	"""
	n = len(messages)
	rounds = max(1, int(tool_rounds if tool_rounds is not None else _keep_tail_rounds()))
	fallback = max(1, int(fallback_messages if fallback_messages is not None else KEEP_TAIL_MESSAGES))
	pairs = tool_pair_ranges(messages)
	if pairs:
		start = pairs[-rounds][0] if len(pairs) >= rounds else pairs[0][0]
		return max(0, min(start, n))
	return max(0, n - fallback)

def split_at_cursor(
	history: list[dict[str, Any]], cursor: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
	"""按 compact_cursor 把历史切成左段/右段；不在本函数里调用 decide"""
	c = max(0, min(int(cursor), len(history)))
	return history[:c], history[c:]


# ====== 主函数 ======
def project(
    history: list[dict[str, Any]],
    *,
    frozen_until: int = 0,
    cwd: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """投影 history：C0 截断 + C1 占位（frozen_until 之前的 tool_result 一律占位）。

    不修改入参。未改动的消息与入参共享引用（copy-on-write）；仅 C0/C1
    实际改写的消息分配新对象。frozen_until 由 runtime 按公式决策推进，
    本函数只做 Apply，因此两次 C1/C2 之间旧消息的投影字节保持不变。
    """
    id_to_name = build_tool_use_names(history)
    boundary = max(0, min(int(frozen_until), len(history)))
    aging = aging_enabled()
    return [
        _process_message(msg, idx, boundary, id_to_name, aging=aging, cwd=cwd)
        for idx, msg in enumerate(history)
    ]


def build_tool_use_names(history: list[dict[str, Any]]) -> dict[str, str]:
    """从历史记录中提取所有 assistant 消息中的 tool_use 块，建立 tool_use_id -> 工具名映射。"""
    return _collect_tool_use_names(history, {})


def _collect_tool_use_names(
    history: list[dict[str, Any]], into: dict[str, str]
) -> dict[str, str]:
    """把消息里的 tool_use id → name 增量并入映射（供增量投影复用前缀映射）。"""
    for msg in history:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            uid = block.get("id")
            if uid:
                into[str(uid)] = str(block.get("name") or "tool")
    return into


def _project_tool_result_content(
    raw: str,
    *,
    uid: str,
    name: str,
    frozen: bool,
    frozen_until: int,
    idx: int,
    aging: bool,
    is_error: bool,
    cwd: str | os.PathLike[str] | None,
) -> tuple[str, bool]:
    """对单个 tool_result 内容做 C0/C1，返回 (投影文本, 是否写入老化存根)。"""
    n_lines = raw.count("\n") + (1 if raw else 0)
    from prompt.fence import (
        truncate_tool_content_preserving_fence,
        unwrap_tool_output,
    )

    inner, _fname = unwrap_tool_output(raw)
    # Link②① 统一 C0/L3：非冻结且超 L3 阈值(默认128) → 直接 offload（固定预览引用），不再 C0 截断。
    from memory.offload import OFFLOAD_THRESHOLD, maybe_offload, offload_enabled

    if not frozen and offload_enabled() and len(inner) > OFFLOAD_THRESHOLD:
        raw, _offloaded = maybe_offload(raw, msg_idx=idx, uid=uid, cwd=cwd)
    elif len(inner) > MAX_TOOL_RESULT_CHARS:
        # 保底：offload 未开启 / 未超阈值但超 8192 的极少数 → C0 截断。
        raw = truncate_tool_content_preserving_fence(
            raw,
            max_chars=MAX_TOOL_RESULT_CHARS,
            marker="\n…[truncated]…\n",
            fallback_suffix=TRUNCATE_SUFFIX,
        )

    aged = False
    if frozen:
        if aging:
            if not should_exempt(is_error, name):
                before = len(raw)
                raw = build_stub(
                    name,
                    uid,
                    raw.split("\n", 1)[0],
                    folded=(frozen_until - idx) > FOLD_AFTER,
                )
                record_stub(before, len(raw))
                aged = True
        else:
            raw = (
                f"[compacted] {name}: prior result ({n_lines} lines) "
                "archived; answer from remaining context"
            )
    return raw, aged


def _process_message(
    msg: dict[str, Any],
    idx: int,
    frozen_until: int,
    id_to_name: dict[str, str],
    *,
    aging: bool | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """处理单条消息：C0 截断 + C1 冻结区占位。不改入参；无改动时返回原对象。

    aging=True 时占位升级为规格存根（engine.aging）：豁免 is_error/结构化结果、
    移除同消息 image 块、近档富存根/远档折叠。None 表示按开关自检。
    """
    content = msg.get("content")
    if not isinstance(content, list):
        return msg

    frozen = idx < frozen_until
    if aging is None:
        aging = aging_enabled() and frozen

    new_blocks: list[Any] | None = None
    aged_any = False
    for i, block in enumerate(content):
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        raw = str(block.get("content") or "")
        uid = str(block.get("tool_use_id") or "")
        name = id_to_name.get(uid, "tool")
        projected, aged = _project_tool_result_content(
            raw,
            uid=uid,
            name=name,
            frozen=frozen,
            frozen_until=frozen_until,
            idx=idx,
            aging=bool(aging),
            is_error=bool(block.get("is_error")),
            cwd=cwd,
        )
        if aged:
            aged_any = True
        if projected == raw and not aged:
            continue
        if new_blocks is None:
            new_blocks = list(content)
        nb = dict(block)
        nb["content"] = projected
        new_blocks[i] = nb

    if new_blocks is None and not aged_any:
        return msg

    out = dict(msg)
    blocks = new_blocks if new_blocks is not None else list(content)
    if aged_any:
        out["content"] = [
            b
            for b in blocks
            if not (isinstance(b, dict) and b.get("type") == "image_url")
        ]
    else:
        out["content"] = blocks
    return out


def project_incremental(
    new_messages: list[dict[str, Any]],
    *,
    base_len: int,
    frozen_until: int,
    id_to_name: dict[str, str],
    cwd: str | os.PathLike[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """增量投影：只处理 [base_len, base_len + len(new_messages)) 这一段。

    前置条件：历史 [0, base_len) 段的投影结果已被调用方缓存，且该段消息
    只追加不修改；frozen_until 与缓存时相同。id_to_name 是 [0, base_len)
    段的 tool_use 映射（调用方持有副本，本函数返回扩展后的新副本）。

    返回 (处理后的新段, 扩展后的映射)。拼接 ``base_projection + new_proj``
    与全量 ``project(history, frozen_until=frozen_until)`` 逐字节一致。
    """
    names = dict(id_to_name)
    _collect_tool_use_names(new_messages, names)
    boundary = max(0, int(frozen_until))
    aging = aging_enabled()
    out = [
        _process_message(m, base_len + i, boundary, names, aging=aging, cwd=cwd)
        for i, m in enumerate(new_messages)
    ]
    return out, names


# ====== 辅助函数 ======
def _iter_tool_result_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """从消息的 content 字段中提取所有 type 为 tool_result 的块。

    假设 content 为列表（否则返回空列表），返回的列表是原列表中的引用，
    因此可以原地修改这些块。
    """
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


# ====== 以下两个函数主要用于测试/验收，非投影核心逻辑 ======
def _block_text_len(block: object) -> int:
    """计算一个内容块（block）的文本长度（字符数）。"""
    if isinstance(block, str):
        return len(block)
    if not isinstance(block, dict):
        return 0
    if block.get("type") == "tool_result":
        return len(str(block.get("content") or ""))
    if block.get("type") == "text":
        return len(str(block.get("text") or ""))
    return 0


def _message_chars(history: list[dict[str, Any]]) -> int:
    """统计整个历史记录中所有消息内容的总字符数（用于验收 < 80_000 的约束）。"""
    total = 0
    for msg in history:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            total += sum(_block_text_len(block) for block in content)
    return total
