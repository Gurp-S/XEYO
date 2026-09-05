"""XEYO.md 维护：省钱导向的模板 / doctor / 提案 / 过期探测 / 一行补丁 / 嵌套懒加载。

设计约束：
- **禁止** agent 静默改写 XEYO.md；提案与 /rule（用户发起）才写盘。
- 常驻左段用软预算；长流程进 Skill，不进 md。
- 结构/依赖不写进 md，工具现查。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# 纠正重复达到该次数 → 仅生成「写入 XEYO.md」提案，不自动写入
REPEAT_PROMOTE_N = 3

# 依赖/目录树等「可推导」噪声（doctor 报警）
_DERIVABLE_PATTERNS = (
	re.compile(r"(?i)\bdependencies?\b\s*[:=]"),
	re.compile(r"(?i)\bnode_modules\b"),
	re.compile(r"(?i)package\.json\s*deps"),
	re.compile(r"(?i)^#+\s*(目录|directory|deps?|dependencies)\b", re.M),
	re.compile(r"(?i)\btop[- ]?level dirs?\b"),
)

_STALE_PROBES = (
	"package.json",
	"gui/package.json",
	"pyproject.toml",
	"requirements.txt",
	".github/workflows",
)

MINIMAL_TEMPLATE = """# XEYO 项目说明（指针式，保持简短）

## 常用命令
- 测试：
- 构建：

## 禁区 / 硬约定
-

## 指针（细则不内联；需要时用 Read / Skill）
- 架构：
- 长流程（发版等）→ `.xeyo/skills/<name>/SKILL.md`，用 Skill 工具按需加载
"""


@dataclass(frozen=True)
class DoctorIssue:
	path: str
	code: str
	message: str
	severity: str = "warn"  # info | warn | error


def soft_instruction_budget() -> int:
	"""常驻左段软上限（省钱）；可用 XEYO_INSTRUCTION_BUDGET 覆盖。"""
	from memory.instruction import instruction_char_budget

	return instruction_char_budget()


def ensure_minimal_xeyo_md(workspace_root: str | Path) -> Path | None:
	"""若工作区尚无 XEYO.md，写入最小指针式模板。已存在则不动。"""
	try:
		root = Path(workspace_root).expanduser().resolve()
	except OSError:
		return None
	if not root.is_dir():
		return None
	target = root / "XEYO.md"
	alt = root / ".xeyo" / "XEYO.md"
	if target.is_file() or alt.is_file():
		return None
	try:
		target.write_text(MINIMAL_TEMPLATE, encoding="utf-8")
	except OSError:
		return None
	try:
		from memory.instruction import clear_instruction_cache

		clear_instruction_cache()
	except Exception:
		pass
	return target


def append_rule_line(
	workspace_root: str | Path,
	line: str,
	*,
	home: bool = False,
) -> str:
	"""用户发起：向项目或 ~/.xeyo/XEYO.md 追加一行规则。"""
	text = (line or "").strip()
	if not text:
		return "规则为空"
	if text.startswith("#"):
		text = text.lstrip("#").strip()
	if not text:
		return "规则为空"
	# 单行，去掉换行
	text = re.sub(r"\s+", " ", text)
	if home:
		from memory.instruction import xeyo_home

		path = xeyo_home() / "XEYO.md"
		path.parent.mkdir(parents=True, exist_ok=True)
	else:
		root = Path(workspace_root).expanduser().resolve()
		path = root / "XEYO.md"
		if not path.is_file() and (root / ".xeyo" / "XEYO.md").is_file():
			path = root / ".xeyo" / "XEYO.md"
		elif not path.is_file():
			ensure_minimal_xeyo_md(root)
			path = root / "XEYO.md"
	prev = ""
	if path.is_file():
		prev = path.read_text(encoding="utf-8")
	stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
	block = f"\n- {text}  <!-- /rule {stamp} -->\n"
	path.write_text(prev.rstrip() + "\n" + block, encoding="utf-8")
	try:
		from memory.instruction import clear_instruction_cache

		clear_instruction_cache()
	except Exception:
		pass
	return f"已写入 {path}：{text}"


def doctor_xeyo_md(workspace_root: str | Path) -> list[DoctorIssue]:
	"""静态检查 XEYO.md 族：过长、可推导内容、坏 include、与 MEMORY 重复粗检。"""
	from memory.instruction import (
		INCLUDE_RE,
		MAX_CHARS,
		_discover_paths,
		xeyo_home,
	)

	issues: list[DoctorIssue] = []
	try:
		root = str(Path(workspace_root).expanduser().resolve())
	except OSError:
		return [DoctorIssue(".", "bad_root", "无法解析工作区", "error")]

	soft = soft_instruction_budget()
	paths = list(_discover_paths(root, root))
	home = xeyo_home()
	# 也检查实际存在的主文件
	for rel in ("XEYO.md", ".xeyo/XEYO.md"):
		p = Path(root) / rel
		if p.is_file() and p not in paths:
			paths.append(p)

	total = 0
	bodies: list[tuple[str, str]] = []
	for path in paths:
		try:
			if not path.is_file():
				continue
			raw = path.read_text(encoding="utf-8")
		except OSError:
			continue
		total += len(raw)
		sp = str(path)
		bodies.append((sp, raw))
		if len(raw) > soft:
			issues.append(
				DoctorIssue(
					sp,
					"over_soft",
					f"超过软预算 {soft} 字（当前 {len(raw)}），请改指针式或拆到 Skill",
					"warn",
				)
			)
		if len(raw) > MAX_CHARS:
			issues.append(
				DoctorIssue(sp, "over_hard", f"超过硬顶 {MAX_CHARS} 字", "error")
			)
		for pat in _DERIVABLE_PATTERNS:
			if pat.search(raw):
				issues.append(
					DoctorIssue(
						sp,
						"derivable",
						"疑似依赖/目录清单——应工具现查，勿常驻 md",
						"warn",
					)
				)
				break
		for m in INCLUDE_RE.finditer(raw):
			inc = (path.parent / m.group(1)).resolve()
			if not inc.is_file():
				issues.append(
					DoctorIssue(sp, "bad_include", f"@include 缺失: {m.group(1)}", "error")
				)

	if total > soft:
		issues.append(
			DoctorIssue(
				"(all)",
				"total_over_soft",
				f"指令族合计 {total} 字 > 软预算 {soft}",
				"warn",
			)
		)

	# 与 MEMORY.md 粗重复（标题行）
	try:
		from memory.memdir import memdir_root, workspace_id

		mem = memdir_root(workspace_id(root)) / "MEMORY.md"
		if mem.is_file():
			mem_text = mem.read_text(encoding="utf-8")
			mem_lines = {
				ln.strip().casefold()
				for ln in mem_text.splitlines()
				if len(ln.strip()) > 12
			}
			for sp, raw in bodies:
				for ln in raw.splitlines():
					s = ln.strip()
					if len(s) > 12 and s.casefold() in mem_lines:
						issues.append(
							DoctorIssue(
								sp,
								"dup_memory",
								f"与 MEMORY.md 重复倾向: {s[:48]}…",
								"info",
							)
						)
						break
	except Exception:
		pass

	return issues


def format_doctor_report(issues: list[DoctorIssue]) -> str:
	if not issues:
		return "XEYO.md doctor：未发现问题。"
	lines = ["XEYO.md doctor："]
	for it in issues[:40]:
		lines.append(f"- [{it.severity}/{it.code}] {it.path}: {it.message}")
	if len(issues) > 40:
		lines.append(f"…另有 {len(issues) - 40} 条")
	return "\n".join(lines)


def _proposals_path(wsid: str) -> Path:
	from memory.memdir import memdir_root

	return memdir_root(wsid) / "instruction_proposals.jsonl"


def _norm_rule(text: str) -> str:
	return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _looks_like_rule(content: str) -> bool:
	s = (content or "").strip()
	if not s or len(s) > 240:
		return False
	if "\n" in s.strip():
		# 允许多行但很短
		if len(s) > 160:
			return False
	# 排除大段代码/路径堆
	if s.count("/") > 8 or s.count("{") > 2:
		return False
	return True


def refresh_instruction_proposals(
	wsid: str,
	*,
	repeat_n: int | None = None,
) -> list[dict[str, Any]]:
	"""从 candidates 的 hit_count / 重复证据生成 XEYO.md 写入提案（不自动写入）。"""
	from memory.memdir import ensure_layout
	from memory.nightshift import load_candidates

	n = repeat_n if repeat_n is not None else REPEAT_PROMOTE_N
	ensure_layout(wsid)
	proposals: list[dict[str, Any]] = []
	seen: set[str] = set()
	for cand in load_candidates(wsid):
		content = (cand.content or "").strip()
		if not _looks_like_rule(content):
			continue
		key = _norm_rule(content)
		if not key or key in seen:
			continue
		src = cand.source if isinstance(cand.source, dict) else {}
		hit = int(src.get("hit_count") or 0)
		ev = list(cand.evidence or [])
		repeat_hits = sum(1 for e in ev if str(e).startswith("repeat"))
		score = max(hit, repeat_hits, 1)
		# last_seen 刷新次数已体现在 hit_count（append 时递增）
		if score < n:
			continue
		seen.add(key)
		proposals.append(
			{
				"content": content,
				"hit_count": score,
				"status": "pending",
				"suggested": f"- {content}",
				"created_at": datetime.now(timezone.utc).isoformat(),
				"note": "达到重复阈值；需人工确认后写入 XEYO.md（可用 /rule）",
			}
		)

	path = _proposals_path(wsid)
	if proposals:
		# 合并已有 pending，按 content 去重
		existing: list[dict] = []
		if path.is_file():
			for line in path.read_text(encoding="utf-8").splitlines():
				if not line.strip():
					continue
				try:
					row = json.loads(line)
				except json.JSONDecodeError:
					continue
				if isinstance(row, dict):
					existing.append(row)
		have = {_norm_rule(str(r.get("content") or "")) for r in existing}
		for p in proposals:
			k = _norm_rule(str(p.get("content") or ""))
			if k and k not in have:
				existing.append(p)
				have.add(k)
		path.write_text(
			"\n".join(json.dumps(r, ensure_ascii=False) for r in existing) + "\n",
			encoding="utf-8",
		)
	return proposals


def list_pending_proposals(wsid: str) -> list[dict[str, Any]]:
	path = _proposals_path(wsid)
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	for line in path.read_text(encoding="utf-8").splitlines():
		if not line.strip():
			continue
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(row, dict) and str(row.get("status") or "pending") == "pending":
			out.append(row)
	return out


def format_proposals_digest(wsid: str) -> str:
	rows = list_pending_proposals(wsid)
	if not rows:
		return ""
	lines = ["# XEYO.md 写入提案（未自动应用）"]
	for r in rows[:8]:
		lines.append(f"- (×{r.get('hit_count', '?')}) {r.get('suggested') or r.get('content')}")
	lines.append("确认后用 /rule <条文> 写入；或忽略。")
	return "\n".join(lines)


def _stamp_path(workspace_root: str) -> Path:
	return Path(workspace_root).expanduser().resolve() / ".xeyo" / "instruction_stamp.json"


def _probe_fingerprint(workspace_root: str) -> dict[str, str]:
	root = Path(workspace_root).expanduser().resolve()
	out: dict[str, str] = {}
	for rel in _STALE_PROBES:
		p = root / rel
		try:
			if p.is_file():
				h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
				out[rel] = f"file:{h}"
			elif p.is_dir():
				names = sorted(x.name for x in p.iterdir())[:32]
				blob = "|".join(names).encode()
				out[rel] = f"dir:{hashlib.sha256(blob).hexdigest()[:16]}"
		except OSError:
			continue
	return out


def refresh_instruction_stamp(workspace_root: str) -> dict[str, str]:
	fp = _probe_fingerprint(workspace_root)
	path = _stamp_path(workspace_root)
	path.parent.mkdir(parents=True, exist_ok=True)
	payload = {"probes": fp, "updated_at": datetime.now(timezone.utc).isoformat()}
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	return fp


def stale_instruction_notice(workspace_root: str, *, commit: bool = True) -> str:
	"""探测文件相对上次 stamp 有变 → 提醒检查 XEYO.md（不自动改）。

	``commit=True``（默认）：返回非空时立刻刷 stamp，避免每轮重复刷。
	``commit=False``：只计算文案，由调用方确认已注入模型后再
	``refresh_instruction_stamp``，避免「刷过 stamp 但模型没看见」。
	首次建 stamp / 坏 stamp 仍立即写盘（无 notice 可展示）。
	"""
	try:
		root = str(Path(workspace_root).expanduser().resolve())
	except OSError:
		return ""
	path = _stamp_path(root)
	current = _probe_fingerprint(root)
	if not current:
		return ""
	if not path.is_file():
		refresh_instruction_stamp(root)
		return ""
	try:
		prev = json.loads(path.read_text(encoding="utf-8"))
		old = prev.get("probes") if isinstance(prev, dict) else {}
		if not isinstance(old, dict):
			old = {}
	except (OSError, json.JSONDecodeError):
		refresh_instruction_stamp(root)
		return ""
	changed = [k for k, v in current.items() if old.get(k) != v]
	# 新出现的探测也算
	changed += [k for k in current if k not in old]
	changed = sorted(set(changed))
	if not changed:
		return ""
	notice = (
		"# XEYO.md 可能过时\n"
		f"探测文件已变：{', '.join(changed[:6])}。"
		"请检查常用命令/禁区是否仍正确；细则用工具现查，勿把依赖列表写进 md。"
	)
	if commit:
		refresh_instruction_stamp(root)
	return notice


def discover_nested_instruction_files(
	file_path: str,
	workspace_root: str,
	*,
	already: Iterable[str] | None = None,
) -> list[str]:
	"""读某文件时：收集其所在目录向上到（不含）工作区根的嵌套 XEYO.md。"""
	have = {os.path.normcase(os.path.abspath(p)) for p in (already or [])}
	try:
		root = Path(workspace_root).expanduser().resolve()
		start = Path(file_path).expanduser().resolve()
		if start.is_file():
			start = start.parent
	except OSError:
		return []
	found: list[str] = []
	cur = start
	try:
		cur.relative_to(root)
	except ValueError:
		return []
	while cur != root:
		for cand in (cur / "XEYO.md", cur / ".xeyo" / "XEYO.md"):
			try:
				if not cand.is_file():
					continue
				key = os.path.normcase(str(cand.resolve()))
				if key in have:
					continue
				have.add(key)
				found.append(str(cand.resolve()))
			except OSError:
				continue
		rules = cur / ".xeyo" / "rules"
		if rules.is_dir():
			try:
				for md in sorted(rules.glob("*.md")):
					key = os.path.normcase(str(md.resolve()))
					if key in have:
						continue
					have.add(key)
					found.append(str(md.resolve()))
			except OSError:
				pass
		if cur.parent == cur:
			break
		cur = cur.parent
	return found


def _sha1_text(raw: str) -> str:
	import hashlib

	return hashlib.sha1((raw or "").strip().encode("utf-8")).hexdigest()


def _sha1_file(path: str) -> str:
	try:
		return _sha1_text(Path(path).read_text(encoding="utf-8"))
	except OSError:
		return ""


def load_nested_instruction_text(
	paths: list[str],
	*,
	max_chars: int = 4_000,
) -> str:
	"""T17 渲染三件套：SHA-1 去重 + 整份丢宽 + 只截最具体 + 可见 notice。

	- ``paths`` 按特异性降序（发现序：离被读文件最近者优先）。
	- trim 后 SHA-1 相同的文件只渲染一次（重复内容不重复注入）。
	- 预算内装不下的文件**整份丢弃**（不拦腰截断）；丢弃后若仍有剩余
	  预算，把**最具体**的被丢文件截断填入；两者都写进可见 notice。
	"""
	entries: list[tuple[str, str, str]] = []  # (path, header, body)
	seen_sha: set[str] = set()
	dup_dropped: list[str] = []
	for p in paths:
		try:
			body = Path(p).read_text(encoding="utf-8").strip()
		except OSError:
			continue
		if not body:
			continue
		digest = _sha1_text(body)
		if digest in seen_sha:
			# 内容与已渲染文件相同：跳过并记入 notice（路径不同内容重复）
			dup_dropped.append(p)
			continue
		seen_sha.add(digest)
		entries.append((p, f"### nested:{Path(p).as_posix()}\n", body))
	if not entries:
		return ""

	# Pass 1：整份装载（装不下 → 整份丢，不截断）
	chunks: list[str] = []
	dropped: list[str] = []
	used = 0
	first_overflow_idx: int | None = None
	for idx, (path, header, body) in enumerate(entries):
		piece = header + body
		if used + len(piece) > max_chars:
			dropped.append(path)
			if first_overflow_idx is None:
				first_overflow_idx = idx
			continue
		chunks.append(piece)
		used += len(piece)

	# Pass 2：剩余预算够 64 字符时，把最具体的被丢文件截断填入
	truncated: str = ""
	if dropped and first_overflow_idx is not None:
		remain = max_chars - used
		if remain >= 64:
			path, header, body = entries[first_overflow_idx]
			piece = header + body
			truncated = path
			chunks.append(piece[:remain].rstrip() + "…")
			dropped = [p for p in dropped if p != truncated]

	notice_lines: list[str] = []
	if dropped:
		names = "、".join(Path(p).name for p in dropped[:6])
		notice_lines.append(f"整份略过（超预算）：{names}")
	if truncated:
		notice_lines.append(f"仅截断最具体文件：{Path(truncated).name}")
	if dup_dropped:
		names = "、".join(Path(p).name for p in dup_dropped[:6])
		notice_lines.append(f"内容重复跳过：{names}")
	out = "# Nested instructions（按需，读到该目录才加载）\n" + "\n\n".join(chunks)
	if notice_lines:
		out += "\n\n> " + "；".join(notice_lines)
	return out


def note_read_path_for_nested(
	working: Any,
	file_path: str,
	workspace_root: str,
) -> list[str]:
	"""把新发现的嵌套指令路径记入 WorkingSnapshot；返回本轮新路径。

	T17：同时登记内容 SHA-1（供下一轮更新/移除 diff 检测）。
	"""
	already = list(getattr(working, "loaded_nested_instruction_paths", None) or [])
	new = discover_nested_instruction_files(
		file_path, workspace_root, already=already
	)
	if not new:
		return []
	working.loaded_nested_instruction_paths = [*already, *new]
	hashes = getattr(working, "nested_hashes", None)
	if isinstance(hashes, dict):
		for p in new:
			hashes[p] = _sha1_file(p)
	return new


def nested_change_notice(
	working: Any,
	*,
	commit: bool = False,
) -> str:
	"""T17：已加载嵌套指令的更新/移除检测 → T_now diff 通知。

	- 文件被删 → 移除墓碑（commit 时从 loaded 列表摘除，停止渲染）。
	- SHA-1 与登记时不符 → 「已更新」（commit 时刷新登记哈希）。
	``commit=True`` 只在通知真正进入最终 blocks 后调用（照抄 stale stamp 范式）。
	"""
	loaded = list(getattr(working, "loaded_nested_instruction_paths", None) or [])
	hashes = getattr(working, "nested_hashes", None)
	if not isinstance(hashes, dict):
		hashes = {}
		working.nested_hashes = hashes
	updates: list[str] = []
	removed: list[str] = []
	for p in loaded:
		try:
			cur = Path(p)
		except OSError:
			continue
		if not cur.is_file():
			removed.append(p)
			continue
		digest = _sha1_file(p)
		prev = hashes.get(p, "")
		if prev and prev != digest:
			updates.append(p)
		elif not prev:
			# 从未登记哈希（旧会话迁移）：补登记，不报警
			hashes[p] = digest
	if not updates and not removed:
		return ""
	if commit:
		if removed:
			working.loaded_nested_instruction_paths = [
				p for p in loaded if p not in set(removed)
			]
			for p in removed:
				hashes.pop(p, None)
		for p in updates:
			hashes[p] = _sha1_file(p)
	lines: list[str] = ["# Nested instructions 变更（background only）"]
	if updates:
		names = "、".join(Path(p).name for p in updates[:6])
		lines.append(f"- 已更新：{names} —— 下一轮 Nested 块将是新内容，勿沿用旧印象。")
	if removed:
		names = "、".join(Path(p).name for p in removed[:6])
		lines.append(f"- 已移除：{names} —— 该嵌套指令已失效，停止参照。")
	return "\n".join(lines)


__all__ = [
	"REPEAT_PROMOTE_N",
	"MINIMAL_TEMPLATE",
	"DoctorIssue",
	"soft_instruction_budget",
	"ensure_minimal_xeyo_md",
	"append_rule_line",
	"doctor_xeyo_md",
	"format_doctor_report",
	"refresh_instruction_proposals",
	"list_pending_proposals",
	"format_proposals_digest",
	"stale_instruction_notice",
	"refresh_instruction_stamp",
	"discover_nested_instruction_files",
	"load_nested_instruction_text",
	"note_read_path_for_nested",
	"nested_change_notice",
	"_sha1_text",
	"_sha1_file",
]
