"""背景/事件/库存类 T_now 块文案的机器守卫（2026-09-09 落地 B）。

裁决（声道来源可辨识，C 的判定记录）：
- **directive 类白名单（恰五类）**：Ask / Plan / Approved plan / Continue /
  Wrap-up —— 产品语义即指令，允许第二人称与祈使，白名单之外不得新增
  （本文件钉死集合，新增需同时改这里并过评审）。
  （原第六类 reasoning_tail 已于 2026-09-10 整体删除：其「把上一轮推理结尾
  重新注入」与引擎铁律「注意力里只出现信息，不出现导演」冲突，且该信息已被
  历史回放的 reasoning block 原样承载，属冗余；dsh 亦无此机制。）
- **background / event / inventory 类块**：只承载无主语事实/数据体。禁止
  第二人称、祈使、预防性否定、动作提议、自我否认式导演（"决策归你"）。
  模型可见文本 ≠ 用户内容——来源由块头（background only）承担，不靠正文喊话。

执法方式：AST 提取清单内渲染函数体的字符串字面量（跳过注释与 docstring），
命中禁词即红。比"运行时输出抽查"更稳：不依赖样本输入、覆盖全部代码路径、
新增块自动纳入（只要列入清单）。清单之外新增的 *渲染函数无法自动被覆盖——
故本文件同时把「白名单五类」钉死，防静默扩权；渲染函数清单由评审维护。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parents[1]

# ── 白名单：允许承载指令语义的块类别（2026-09-15 起恰四类）──
# 原第五类 ``wrap_up`` 已于 2026-09-15 随块撤销移出（用户裁定：该块只说
# 「预算已尽」却不标作用域，模型必然误标；限制只在执行层表达）。
DIRECTIVE_WHITELIST: frozenset[str] = frozenset(
    {"ask", "plan", "approved_plan", "continue"}
)

# ── 禁词（已裁决违规句式；background 类渲染函数命中即红）──
BANNED_ADVISORY = (
    "决策归你",
    "不是新任务",
    "不是用户请求",
    "不是用户提问",
    "可以读页面正文",
    "在你看不到的时机",
    "禁止就本块内容",
    "否则完全忽略",
    "仅当用户消息本身明确提到",
    "已完成部分不随下一步动作作废",
    "请",
    "务必",
    "别忘了",
    "建议你",
    "你应该",
)

# 第二人称代词标记（background 块不应向模型喊话）
_BANNED_SECOND_PERSON = ("你", "您")

# ── 背景/事件/库存类渲染函数清单：(repo 相对路径, 函数名) ──
# 新增 background 类块渲染函数时必须登记到这里；登记即受扫描。
BACKGROUND_RENDERERS: tuple[tuple[str, str], ...] = (
    ("prompt/pre_llm_inject.py", "browser_preview_block"),
    ("prompt/pre_llm_inject.py", "pending_jobs_block"),
    ("prompt/pre_llm_inject.py", "budget_mirror_block"),
    ("prompt/pre_llm_inject.py", "file_conflict_block"),
    ("engine/todo_hint.py", "build_todo_hint"),
    ("engine/wrap_gap.py", "compose_gap_text"),
    ("engine/wrap_gap.py", "compose_guide_text"),
    ("memory/runtime.py", "_memory_index_block"),
)

# ── 白名单对应物（存在性探针：映射改了/实现删了 → 红）──
_DIRECTIVE_ANCHORS: dict[str, tuple[str, str]] = {
    "ask": ("prompt/pre_llm_inject.py", "ASK_MODE_INSTRUCTIONS"),
    "plan": ("prompt/pre_llm_inject.py", "PLAN_MODE_INSTRUCTIONS"),
    "approved_plan": ("prompt/turn_context.py", "PLAN_POINTER_BLOCK"),
    "continue": ("prompt/turn_context.py", "CONTINUE_AFTER_TOOLS"),
}

# 自动注入（非用户可选）directive 模板的注意力上限（字符；动态内容另计）。
# 用户裁决：Continue / Wrap-up 虽属白名单，也不能长。
_AUTO_DIRECTIVE_CAP_CHARS: dict[str, tuple[str, str, int]] = {
    # 类别: (文件, 锚点, 上限)
    "continue": ("prompt/turn_context.py", "CONTINUE_AFTER_TOOLS", 200),
}


# ── AST 工具 ──

def _string_literals(node: ast.AST) -> list[tuple[int, str]]:
	"""收集节点内全部字符串字面量（含 f-string 常量段）→ [(行号, 文本)]。"""
	out: list[tuple[int, str]] = []

	def walk(n: ast.AST) -> None:
		if isinstance(n, ast.Constant) and isinstance(n.value, str):
			out.append((getattr(n, "lineno", 0), n.value))
		elif isinstance(n, ast.JoinedStr):
			for v in n.values:
				if isinstance(v, ast.Constant) and isinstance(v.value, str):
					out.append((getattr(v, "lineno", 0), v.value))
		for child in ast.iter_child_nodes(n):
			walk(child)

	walk(node)
	return out


def _iter_target_literals(module_path: Path, func_name: str) -> list[tuple[int, str]]:
	"""取某渲染函数体的字面量（剔除函数 docstring）。"""
	source = module_path.read_text(encoding="utf-8")
	tree = ast.parse(source, filename=str(module_path))
	for node in tree.body:
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
			body_nodes = list(node.body)
			if body_nodes and isinstance(body_nodes[0], ast.Expr) and isinstance(
				body_nodes[0].value, ast.Constant
			) and isinstance(body_nodes[0].value.value, str):
				body_nodes = body_nodes[1:]
			lits: list[tuple[int, str]] = []
			for stmt in body_nodes:
				lits.extend(_string_literals(stmt))
			return lits
	return []


def _module_literal_anchor(rel_path: str, anchor: str) -> list[tuple[int, str]]:
	"""模块级常量锚点的字面量（跨行拼接取整体, 行号=首字面量）。"""
	module_path = _PY_ROOT / rel_path
	source = module_path.read_text(encoding="utf-8")
	tree = ast.parse(source, filename=str(module_path))
	for node in tree.body:
		if isinstance(node, ast.Assign):
			for tgt in node.targets:
				if isinstance(tgt, ast.Name) and tgt.id == anchor:
					lits = _string_literals(node.value)
					if lits:
						# 拼接串按序拼回（join 无分隔）用于长度/内容检查
						first = min(line for line, _ in lits)
						joined = "".join(text for _, text in lits)
						return [(first, joined)]
	return []


# ── 测试 ──

def test_whitelist_exactly_four_and_anchored() -> None:
	"""白名单恰为裁决的四类（wrap_up 已于 2026-09-15 撤销）；每类有实现锚点。"""
	assert DIRECTIVE_WHITELIST == frozenset(
		{"ask", "plan", "approved_plan", "continue"}
	)
	for cat in DIRECTIVE_WHITELIST:
		assert cat in _DIRECTIVE_ANCHORS


def test_auto_directive_template_within_attention_caps() -> None:
	"""自动注入（非用户可选）的 directive 模板受注意力上限约束。"""
	for cat, (rel, anchor, cap) in _AUTO_DIRECTIVE_CAP_CHARS.items():
		lits = _module_literal_anchor(rel, anchor)
		assert lits, f"{rel}::{anchor} 未找到常量锚点"
		_, text = lits[0]
		assert len(text) <= cap, f"{cat} 模板超上限: {len(text)} > {cap} chars"


def test_background_renderers_have_no_directive_phrasing() -> None:
	"""background 类渲染函数体字面量不含禁词与第二人称。"""
	violations: list[str] = []
	for rel, func in BACKGROUND_RENDERERS:
		module_path = _PY_ROOT / rel
		if not module_path.exists():
			violations.append(f"{rel} 不存在（清单过期）")
			continue
		lits = _iter_target_literals(module_path, func)
		if not lits:
			violations.append(f"{rel}::{func} 未找到函数（清单过期）")
			continue
		for line, text in lits:
			low = text
			for marker in BANNED_ADVISORY:
				if marker in text:
					violations.append(f"{rel}::{func}:{line} 命中禁词 {marker!r}")
			if text.isascii():
				continue  # 英文串（工具描述/围栏标签）不扫第二人称
			for ch in _BANNED_SECOND_PERSON:
				if ch in text:
					violations.append(
						f"{rel}::{func}:{line} 含第二人称 {ch!r}: {text[:40]!r}"
					)
	assert not violations, "background 类块文案违规：\n" + "\n".join(violations)


def _data_dialect_issue(text: str) -> str | None:
	"""背景块正文须为数据方言：header/fence/列表行放行，其余行须含数据标点
	或数字、且不以句末标点结尾——杜绝"像用户说的话"的自由散文。"""
	if not text:
		return None
	lines = [l.strip() for l in text.splitlines() if l.strip()]
	if not lines:
		return "空输出"
	for s in lines:
		if s.startswith(("#", "<", ">", "[system-", "---")):
			continue
		if s.startswith(("-", "*", "•", "…")):
			continue
		if s.endswith(("。", "！", "？")):
			return f"行以句末标点结尾(像人话): {s[:50]}"
		tokens = "：:｜|/%~→`[]()（）=·、"
		if not (any(ch in s for ch in tokens) or any(ch.isdigit() for ch in s)):
			return f"非数据行(无数据标点/数字): {s[:60]}"
	return None


def _assert_pure_text(block: str, label: str) -> None:
	issue = _data_dialect_issue(block)
	assert issue is None, f"{label} 违反数据方言: {issue}"
	for marker in BANNED_ADVISORY:
		assert marker not in block, f"{label} 命中禁词 {marker!r}"
	for ch in _BANNED_SECOND_PERSON:
		if ch in block:
			# 数据行内容可能含合法字符（如文件内容里带"你"）——只拦非 ASCII 的
			# 自由文本；header 与数据行已由形态断言把关。
			assert False, f"{label} 含第二人称 {ch!r}: {block[:80]!r}"


class TestBackgroundDataDialect:
	"""L1（2026-09-09）：背景块运行时输出采样须为数据方言。

	配合 AST 字面量守卫（测试上方）形成双保险：静态防新引入句式，
	运行时防"拼接/来自数据源"的文本逃逸形态断言。逐条 fixture 采样。
	"""

	def _todo_working(self):
		from types import SimpleNamespace

		return SimpleNamespace(
			todos=[
				{"status": "completed", "content": "读完链路"},
				{"status": "pending", "content": "写契约测试"},
				{"status": "in_progress", "content": "抽 usageSegments"},
			]
		)

	def _budget(self):
		from types import SimpleNamespace
		import time

		return SimpleNamespace(
			turn_count=3,
			max_turns=12,
			wall_deadline_ts=time.time() + 300,
			wall_started_ts=time.time() - 60,
			usd_limit=1.0,
			used_usd=0.42,
		)

	def test_todo_hint_data_dialect(self):
		from engine.todo_hint import build_todo_hint

		block = build_todo_hint(self._todo_working().todos)
		assert block.startswith("# Todo progress")
		_assert_pure_text(block, "todo_hint")

	def test_budget_mirror_data_dialect(self):
		from prompt.pre_llm_inject import budget_mirror_block

		block = budget_mirror_block(self._budget(), self._todo_working())
		assert block.startswith("# Budget mirror")
		_assert_pure_text(block, "budget_mirror")

	def test_browser_preview_data_dialect(self, monkeypatch):
		import prompt.pre_llm_inject as pli

		monkeypatch.setattr(pli, "side_mode", lambda: False)
		monkeypatch.setattr(pli, "browser_preview_url", lambda: "http://localhost:5173")
		block = pli.browser_preview_block()
		assert block.startswith("# 浏览器预览")
		_assert_pure_text(block, "browser_preview")

	def test_pending_jobs_data_dialect(self, monkeypatch):
		import permissions.policy as pol
		import prompt.pre_llm_inject as pli

		monkeypatch.setattr(
			pol,
			"pending_jobs_digest",
			lambda: "- bash-1（exit_code=0）：npx vitest run x.test.ts",
		)
		block = pli.pending_jobs_block()
		assert block.startswith("# Background jobs")
		_assert_pure_text(block, "pending_jobs")

	def test_file_conflict_data_dialect(self, monkeypatch):
		import engine.session_presence as sp
		import prompt.pre_llm_inject as pli

		class FakePresence:
			def peer_conflict_files(self, cwd, sid, paths):
				return {"gui/App.tsx": ("重构导航", 1_750_000_000.0)}

		monkeypatch.setattr(sp, "default_session_presence", lambda: FakePresence())
		block = pli.file_conflict_block("cwd", "sid", ["gui/App.tsx"])
		assert block.startswith("# 文件冲突")
		_assert_pure_text(block, "file_conflict")

	def test_memory_index_and_wrap_data_dialect(self):
		from engine.wrap_gap import compose_gap_text, compose_guide_text
		from memory.runtime import _memory_index_block

		idx = "# Memory index\n" + "".join(
			f"[feedback] 第{i}条 -> topics/f-{i}.md\n" for i in range(12)
		)
		blk = _memory_index_block(idx)
		assert blk and _data_dialect_issue(blk) is None
		assert compose_guide_text(5, ["x -> a.md(未落盘)"]) and _data_dialect_issue(
			compose_guide_text(5, ["x -> a.md(未落盘)"])
		) is None
		assert compose_gap_text([]) == ""
		assert _data_dialect_issue(compose_gap_text(["x -> a.md(未落盘)"])) is None


if __name__ == "__main__":
	sys.exit(0)
