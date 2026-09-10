"""Todo 完成度提示（#2，思想蒸馏自「Todo DAG 化：失败要局部化」）。

动机
----
线性计划登记表 + 一次 submit 内某一步失败后，弱模型常出现两类行为：
1. 就地反复重试同一步（已有 RepeatGuard / StagnationWatch 处理）；
2. **把"这一步失败"泛化成"整份计划走不通"**，推倒重来或提前放弃——
   浪费已完成的 X 步成果，重新烧探索轮次。

本模块只做一件事：在引擎已有卡住/重复证据时，把**纯事实**渲染出来——
已完成 X/Y 项 + 仍未完成的项清单。不褒贬、不评分、不给解法（守 #6 无软
信号哲学）；"已完成的部分不会白费、下一步从这里继续"由模型自行得出。

触发纪律
--------
- 常态（无卡住/重复证据）**零注入**：装配点只在 repeat_guard / stall
  advice 非空时渲染（并入 repeat_guard 单块——与停滞监测同块消费先例一致，
  不新增 T_NOW_BLOCK_REGISTRY 条目、不动硬顶；消融随 XEYO_T_NOW_SKIP=
  repeat_guard）。不做每轮心跳——长计划每轮重复注入 todo 清单是上下文噪声。
- total < 2 不注入（X/Y 无对比意义）；全部 done 不注入。
"""

from __future__ import annotations

from typing import Any, Iterable

#: 视为「已完成」的状态（对齐 budget_mirror_block 的既有语义）。
DONE_STATUSES = frozenset({"completed", "done"})
#: 视为「仍在推进」的显式状态（其余非 done 一律按待办处理，宁显勿漏）。
PROGRESS_STATUSES = frozenset({"pending", "in_progress", "active"})
_OPEN_LABEL = {"in_progress": "进行中", "active": "进行中", "pending": "待办"}
MAX_OPEN_LINES = 6
CONTENT_MAX_CHARS = 80


def _content(t: Any) -> str:
	"""取条目内容；与 budget_mirror_block 同源容错。"""
	if not isinstance(t, dict):
		return ""
	return str(t.get("content") or t.get("text") or "").strip()


def _is_open(t: Any) -> bool:
	if not isinstance(t, dict):
		return False
	st = str(t.get("status") or "").strip().lower()
	if not st:
		return True  # 无状态 = 待办（宁显勿漏）
	if st in DONE_STATUSES:
		return False
	return True


def todo_counts(todos: Iterable[Any] | None) -> tuple[int, int]:
	"""返回 (total, open)：total=有内容的条目数，open=未完成条目数。"""
	if not todos:
		return (0, 0)
	total = 0
	open_n = 0
	for t in todos:
		if not _content(t):
			continue
		total += 1
		if _is_open(t):
			open_n += 1
	return (total, open_n)


def build_todo_hint(
	todos: Iterable[Any] | None,
	*,
	max_open_lines: int = MAX_OPEN_LINES,
) -> str:
	"""渲染完成度提示块；不满足触发条件返回空串。

	触发：total >= 2 且 open >= 1（部分完成但未收口）。
	输出为纯事实（完成 X/Y + 未完成项清单），无褒贬评语。
	"""
	if todos is None:
		return ""
	total = 0
	open_items: list[str] = []
	try:
		for t in todos:
			content = _content(t)
			if not content:
				continue
			total += 1
			if _is_open(t):
				st = str(t.get("status") or "").strip().lower()
				label = _OPEN_LABEL.get(st, "待办")
				open_items.append(f"- [{label}] {content[:CONTENT_MAX_CHARS]}")
	except Exception:  # noqa: BLE001 — 渲染层永不因 todo 形状炸主路径
		return ""
	if total < 2 or not open_items:
		return ""

	done = total - len(open_items)
	head = f"计划进度：已完成 {done}/{total} 项。"
	body = "\n".join(open_items[:max_open_lines])
	extra = len(open_items) - max_open_lines
	if extra > 0:
		body += f"\n… 其余 {extra} 项省略（可用 todo 工具查全量）"
	# 标题不带「— 事实呈现，决策归你」：自我否认式导演（声明"我不是在指挥"
	# 本身就在提醒"这里有个决策要做"）。正文不带「已完成部分不随下一步动作
	# 作废」：预防性否定，且本模块 docstring 明写该结论"由模型自行得出"
	# ——把它写进注入文案等于替模型下了结论（2026-09-09）。
	return (
		"# Todo progress（background only）\n"
		f"{head}尚未完成的项：\n{body}"
	)


__all__ = ["build_todo_hint", "todo_counts"]
