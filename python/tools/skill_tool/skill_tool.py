"""Skill tool — 目录「会话快照」+ 按需加载正文（F4）。

- schema 内嵌**图书目录**（§2 决策 1）：每技能一行 ``- 名字: 一句话描述[来源]``
  （desc ≤120、总硬顶 ≤2400、``model_invocable:true`` 才列），会话建立时按当时
  启用状态渲染，**会话内永不变化**（tools 数组冻结红线）。
- ``action:"list"``（可选 ``query``）详情/检索：desc ≤500、总 ≤4k、query 子串过滤。
- ``args`` 可选：body 含 ``$ARGUMENTS`` 则替换，否则追加「## 调用参数」节。
- 结果头带 ``(path: <SKILL.md>)``；>12KB 截断尾注 ``use Read to continue``。
- ``user_invocable:false`` → ``/skills`` / ``/v1/skills`` 不展示；``model_invocable:false``
  → 目录不列 + 模型调用返回 ``not available for model invocation``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engine.abort import AbortController
from extension import mcp_scopes as _scopes
from extension.skill_loader import SkillEntry, discover_skills
from tools.base_tool import ToolResult
from tools.skill_tool.prompt import DESCRIPTION, TOOL_NAME

#: 目录硬顶（§2 决策 1：总 ≤2400 字符）。
CATALOG_MAX_CHARS = 2_400
#: 目录单行 desc ≤120。
CATALOG_LINE_DESC = 120
#: list 响应：单条 desc ≤500、总 ≤4k。
LIST_LINE_DESC = 500
LIST_MAX_CHARS = 4_000
#: 正文截断阈值。
BODY_MAX = 12_000

# 兼容旧签名：`cwd` 仍可由外部传入，但 SkillTool 始终优先用会话 cwd。
def discover_skill_dirs(cwd: str) -> list[Path]:
	"""Workspace `.xeyo/skills/*` then `~/.xeyo/skills/*` (legacy scan)."""
	return [e.path for e in discover_skills(cwd) if e.source in ("workspace", "home")]


def list_skill_names(cwd: str) -> list[str]:
	"""Extension-aware skill names (merges plugin skills when enabled)."""
	return [e.name for e in discover_skills(cwd)]


def _skill_entries_with_descriptions(cwd: str) -> list[SkillEntry]:
	"""Enriched discovery table; falls back to empty on any config error."""
	try:
		return discover_skills(cwd)
	except Exception:  # noqa: BLE001
		return []


def _entry(entries: list[SkillEntry], name: str) -> SkillEntry | None:
	want = (name or "").strip()
	if not want:
		return None
	for e in entries:
		if e.name.casefold() == want.casefold():
			return e
	return None


def load_skill_body(cwd: str, name: str) -> str | None:
	"""Load a skill body by name from any enabled source (workspace/home/plugin)."""
	entry = _entry(_skill_entries_with_descriptions(cwd), name)
	if entry is None or entry.broken:
		return None
	try:
		return (entry.path / "SKILL.md").read_text(encoding="utf-8")
	except OSError:
		return None


def _one_line(desc: str, *, limit: int) -> str:
	desc = (desc or "").strip().replace("\n", " ").replace("\r", " ")
	if len(desc) > limit:
		return desc[: limit - 1].rstrip() + "…"
	return desc


def _catalog_text(entries: list[SkillEntry]) -> str:
	"""会话快照目录（仅 model_invocable; desc ≤120; 总 ≤2400）。"""
	lines: list[str] = []
	total = 0
	for e in entries:
		if e.broken or not e.model_invocable:
			continue
		origin = e.plugin if e.plugin else e.source
		desc = _one_line(e.description, limit=CATALOG_LINE_DESC)
		line = f"- {e.name}: {desc}[{origin}]" if desc else f"- {e.name}[{origin}]"
		if total + len(line) > CATALOG_MAX_CHARS:
			lines.append("…更多用 action:'list' 查询。")
			break
		lines.append(line)
		total += len(line)
	return "\n".join(lines)


def _list_response(entries: list[SkillEntry], query: str) -> str:
	"""list/query：desc ≤500、总 ≤4k、query 子串过滤（名称/标签/描述）。"""
	q = (query or "").strip().lower()
	out: list[str] = []
	total = 0
	for e in entries:
		if e.broken or not e.model_invocable:
			continue
		hay = f"{e.name} {' '.join(e.tags)} {e.description}".lower()
		if q and q not in hay:
			continue
		origin = e.plugin if e.plugin else e.source
		desc = _one_line(e.description, limit=LIST_LINE_DESC)
		line = f"- {e.name}: {desc}[{origin}]" if desc else f"- {e.name}[{origin}]"
		if total + len(line) > LIST_MAX_CHARS:
			out.append("…（响应截断，请缩小 query。）")
			break
		out.append(line)
		total += len(line)
	return "\n".join(out) or (f"（没有匹配 query={query!r} 的可用技能。）" if q else "（没有可用技能。）")


def _apply_args(body: str, args: Any) -> str:
	"""``args`` 参数：body 含 ``$ARGUMENTS`` 则替换，否则追加「## 调用参数」节。"""
	if not args:
		return body
	if isinstance(args, str):
		serialized = args
	else:
		try:
			serialized = json.dumps(args, ensure_ascii=False, indent=2)
		except (TypeError, ValueError):
			serialized = str(args)
	if "$ARGUMENTS" in body:
		return body.replace("$ARGUMENTS", serialized)
	return f"{body}\n\n## 调用参数\n{serialized}"


def _model_invocable_ok(entries: list[SkillEntry], name: str) -> bool:
	entry = _entry(entries, name)
	if entry is None or entry.broken:
		return False
	return entry.model_invocable


def _enterprise_denied(entries: list[SkillEntry], name: str) -> bool:
	entry = _entry(entries, name)
	if entry is None:
		return False
	return _scopes.skill_denied(entry.name)


def _disabled_now(cwd: str, name: str) -> bool:
	"""F2.5：skill 存在但被启停配置关掉（区别于「未安装」的即时探针）。

	双发现对比：当前生效发现表**不可见** + 全放开（主开关开/无启停表）发现表
	**可见且非 broken** → 即为被停用；探测自身失败一律 False（宁可报 not
	found，不误报停用）。
	"""
	try:
		from extension.config import ExtensionConfig
		from extension.skill_loader import discover_skills as _disc

		if _entry(_disc(cwd), name) is not None:
			return False  # 当前可见 → 不是停用
		probe = _disc(cwd, config=ExtensionConfig(enabled_extensions=True))
		entry = _entry(probe, name)
		# broken-but-listed 不算「存在」：坏 manifest 应报 not found，不误报停用。
		return entry is not None and not entry.broken
	except Exception:  # noqa: BLE001
		return False


class SkillTool:
	name = TOOL_NAME

	def __init__(self, cwd: str = ".") -> None:
		self._cwd = cwd
		# 目录 = 会话起点快照：构造时按当时启用状态渲染一次，会话内永不变化
		# （tools 数组冻结红线）。解析正文仍走实时 discover（3s TTL）。
		self._catalog = _catalog_text(_skill_entries_with_descriptions(cwd))

	@staticmethod
	def is_read_only() -> bool:
		return True

	@staticmethod
	def is_concurrency_safe() -> bool:
		return True

	def schema(self) -> dict[str, Any]:
		# 目录 = 会话起点快照（构造时渲染，自缓存 → 会话内逐字节不变）。
		catalog = self._catalog
		# E1 裁决："必须先读全文"由引擎规则保证（invoke 直接返回 SKILL.md
		# 全文），描述里不再写纪律句。
		desc = (
			DESCRIPTION.strip()
			+ "\n当前可用（目录为会话快照，会话内不变）：\n"
			+ (catalog or "（无）")
		)
		return {
			"name": self.name,
			"description": desc,
			"input_schema": {
				"type": "object",
				"properties": {
					"action": {
						"type": "string",
						"enum": ["list"],
						"description": "action='list' 列出/检索技能详情（可选 query 子串过滤，限 4k）。",
					},
					"name": {
						"type": "string",
						"description": "Skill directory name under .xeyo/skills/",
					},
					"query": {
						"type": "string",
						"description": "list 时按名称/标签/描述子串过滤。",
					},
					"args": {
						"type": "string",
						"description": "可选：传入 SKILL.md 的调用参数（替换 $ARGUMENTS 或追加「## 调用参数」节）。",
					},
				},
			},
		}

	async def execute(self, input: dict[str, Any], abort: AbortController) -> ToolResult:
		abort.raise_if_aborted()
		raw = input if isinstance(input, dict) else {}
		action = str(raw.get("action") or "").strip().lower()
		name = str(raw.get("name") or "").strip()
		query = str(raw.get("query") or "").strip()
		args = raw.get("args")

		entries = _skill_entries_with_descriptions(self._cwd)

		if action == "list":
			return ToolResult(content=_list_response(entries, query), is_error=False)

		if not name:
			return ToolResult(content="name required (or action='list')", is_error=True)

		if _enterprise_denied(entries, name):
			return ToolResult(
				content=f"Skill {name} is denied by enterprise policy.", is_error=True
			)
		# F2.5：会话内停用（发现表按启用过滤 → 需与「未安装」区分），即时拒绝。
		disabled = _disabled_now(self._cwd, name)
		if disabled:
			return ToolResult(
				content=f"Skill {name} 已被用户停用（即时生效；下个会话目录重塑）。",
				is_error=True,
			)
		if _entry(entries, name) is None:
			avail = [e.name for e in entries if not e.broken and e.model_invocable]
			hint = f" Available: {', '.join(avail)}" if avail else " (none installed)"
			return ToolResult(content=f"Skill not found: {name}.{hint}", is_error=True)
		if not _model_invocable_ok(entries, name):
			return ToolResult(
				content=f"Skill {name} not available for model invocation "
				"(model_invocable:false).",
				is_error=True,
			)
		body = load_skill_body(self._cwd, name)
		if body is None:
			return ToolResult(content=f"Skill not found: {name} (broken?).", is_error=True)

		entry = _entry(entries, name)
		path = str(entry.path / "SKILL.md") if entry else ""
		header = f"# Skill: {name}\n(path: {path})"
		body = _apply_args(body, args)
		if len(body) > BODY_MAX:
			body = (
				body[:BODY_MAX].rstrip()
				+ f"\n\n[truncated; full file: {path} — use Read to continue]"
			)
		return ToolResult(content=f"{header}\n\n{body}", is_error=False)


def is_user_invocable(cwd: str, name: str) -> bool:
	"""``user_invocable:false`` 时供 `/skills` 菜单 / `/v1/skills` 隐藏用。"""
	entry = _entry(_skill_entries_with_descriptions(cwd), name)
	if entry is None or entry.broken:
		return False
	return entry.user_invocable
