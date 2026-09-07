"""收尾窗缺口清单（R3' 消费 R4）——模块级发布 + 纯函数构建。

角色
----
- TodoItem.output（R4，c86ad50）让"completed 但磁盘缺失"成为引擎可 stat 的
  确定性事实。收尾窗（forced_wrap_up）打开时，把这份缺口清单拼进
  ``# Wrap-up required`` 引导，让模型的最后配额花在"把登记产物落盘"上，
  而不是再开新探索或空泛收尾。
- 不裁决、不拦截：只把 stat 结果作为事实呈现（fail-open——工具未注册、
  stat 异常、cwd 缺失一律产出空清单）。

与 repeat_guard 同构
--------------------
模块级 publish/current 一对接口，query_loop 在 wrap 打开时发布，
``pre_llm_inject`` 的 wrap_up 块装配时消费——不进 MessageStore、不改 JSONL。
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.todo_write_tool.types import TodoItem

#: 缺口清单最多列出项数（防收尾窗上下文被长清单挤爆）。
MAX_GAP_ITEMS = 5


# ── 模块级当前缺口文本（单进程单 loop；wrap 装配消费）───────────

_CURRENT_GAP: str = ""


def publish_gap(text: str) -> None:
	global _CURRENT_GAP
	_CURRENT_GAP = (text or "").strip()


def current_gap() -> str:
	return _CURRENT_GAP


def clear_gap() -> None:
	global _CURRENT_GAP
	_CURRENT_GAP = ""


# ── 纯函数：从清单 + cwd 构建缺口文本 ─────────────────────────

def _short(content: str, limit: int = 40) -> str:
	s = (content or "").strip().replace("\n", " ")
	return s if len(s) <= limit else s[: limit - 1] + "…"


def build_gap_lines(
	todos: list[TodoItem] | None,
	cwd: str,
	*,
	max_items: int = MAX_GAP_ITEMS,
) -> list[str]:
	"""completed 且声明 output 但磁盘不存在的项 → 缺口行。

	判据只认磁盘 stat（os.path.exists）：引擎看事实，不信模型自报。
	output 空 / 未 completed / cwd 为空 → 跳过；上限 max_items 截断。
	"""
	if not todos or not (cwd or "").strip():
		return []
	root = Path(cwd)
	lines: list[str] = []
	for item in todos:
		if getattr(item, "status", "") != "completed":
			continue
		out = getattr(item, "output", "") or ""
		if not out.strip():
			continue
		rel = out.strip().replace("\\", "/").lstrip("/")
		try:
			exists = (root / rel).exists() if rel else False
		except (OSError, ValueError):
			exists = False
		if not exists:
			lines.append(f"- {_short(item.content)} → {rel}(未落盘)")
		if len(lines) >= max_items:
			break
	return lines


def compose_gap_text(lines: list[str]) -> str:
	"""缺口行 → 引导文本;空清单返回空串(wrap 装配直接跳过)。"""
	if not lines:
		return ""
	return "收尾前请优先写入以下已登记产物(引擎已核对磁盘,仍缺失):\n" + "\n".join(lines)


def compose_guide_text(quota: int, lines: list[str]) -> str:
	"""完整收尾引导后缀:配额行 + 缺口行。

	``quota <= 0`` 表示本轮已无放行额度(装配仍应带缺口提醒,让模型知道
	产物没落盘);``lines`` 为空则只带配额行。
	"""
	parts: list[str] = []
	if quota >= 0:
		parts.append(f"剩余收尾工具配额:{quota} 次——仅用于写入产物/必要验证,不得开启新探索")
	gap = compose_gap_text(lines)
	if gap:
		parts.append(gap)
	return "\n".join(parts)
