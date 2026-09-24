"""A0 —— 静态差异与确定性重算，零模型调用（设计 §7 A0）。

包装 ``evals.changedetect`` 的 L0（模型可见文本面）与 L1（注入链路确定性轨迹），
再加一个提示词文件变更探测器：短时间内的反复保存合并成一次检测，避免每次 Ctrl+S
都重扫。输出只有两类事实——**改了什么**、**哪些机械约束受影响**。

本模块不判断"变化是不是更好"：那需要 A1/A2 的配对证据。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from diagnostics import store
from diagnostics.identity import _s

MODE = "a0"
RULESET_VERSION = 1
DEFAULT_DEBOUNCE_SEC = 8.0

#: 文件消失也走去抖：pending_sha 打这个标记，避免"删掉又重建"触发两次重扫。
_GONE_MARK = "gone"

#: changedetect 根目录（A0 的 golden 与采集器都住在那儿）。
_PYTHON_ROOT = Path(__file__).resolve().parents[2]

#: artifact 前缀 → 受影响的机械约束（静态映射表，只说"哪条不变量被触碰"）。
_CONSTRAINT_BY_PREFIX: tuple[tuple[str, str], ...] = (
	("system/", "system 左段文本变化：前缀稳定性与身份/环境段的字节面受影响"),
	("tools/_", "工具清单/计数变化：模型可见工具集与 schema 预算受影响"),
	("tools/", "工具 schema 变化：模型怎么调工具、传什么参的协议受影响"),
	("tnow/registry", "T_now 块登记表变化：块准入（pipe/quota/dedup）约束受影响"),
	("tnow/hard_cap", "T_now 块硬顶变化：每轮注入块数量上限受影响"),
	("tnow/block_count", "T_now 登记块数变化：与硬顶共同决定准入"),
	("tnow/block/", "T_now 静态块正文变化：注入文本字节面受影响"),
	("slash/", "斜杠命令 manifest 变化：GUI/TUI 两份生成物一致性受影响"),
	("meta/", "侦测器自身口径变化：MDE / 样本量表受影响"),
	("inject/", "注入链路输出变化：投影 → 请求装配的约束受影响"),
	("loop/", "回路轨迹变化：轮次与工具调用顺序约束受影响"),
)

#: 提示词源文件路径 → 受影响面（同样的映射只在"文件级"表达一次，之后交给 A0 重算）。
_PATH_CONSTRAINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
	("prompt/system_prompt.py", ("system/*",)),
	("prompt/assembler.py", ("system/*",)),
	("prompt/fence.py", ("system/*", "inject/*")),
	("prompt/pre_llm_inject.py", ("tnow/*", "inject/*")),
	("prompt/t_now_strategy.py", ("tnow/*",)),
	("prompt/turn_context.py", ("inject/*",)),
	("prompt/inject_store.py", ("inject/*",)),
	("prompt/notice_channel.py", ("inject/*",)),
	("tools/", ("tools/*",)),
)

_ALLOWED_CONCLUSION = (
	"A0 只回答两件事：模型可见文本/确定性轨迹改了什么，以及哪些机械约束被触碰。"
	"模型表现是否提高不在 A0 的结论范围内——它没有跑过任何模型请求。"
)
_FORBIDDEN_CONCLUSION = "不得由 A0 得出「更好 / 更省 / 更准」，也不得把它当作可以上线的依据。"


def _constraint_for(name: str) -> str:
	for prefix, text in _CONSTRAINT_BY_PREFIX:
		if _s(name).startswith(prefix):
			return text
	return "未归类变化：需人工确认其属于哪个机械约束"


def _constraints_for_path(rel_path: str) -> list[str]:
	path = _s(rel_path).replace("\\", "/")
	groups = [g for marker, group in _PATH_CONSTRAINTS if group and marker in path for g in group]
	return sorted(set(groups))


def _changes_to_rows(changes: Iterable[Any]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for change in changes or []:
		row = change.to_dict() if hasattr(change, "to_dict") else dict(change)
		name = _s(row.get("name"))
		rows.append(
			{
				"name": name,
				"status": _s(row.get("status")),
				"group": _s(row.get("group")),
				"chars_before": int(row.get("chars_before") or 0),
				"chars_after": int(row.get("chars_after") or 0),
				"added_chars": int(row.get("added") or 0),
				"removed_chars": int(row.get("removed") or 0),
				"first_line": row.get("first_line"),
				"mechanical_constraint": _constraint_for(name),
			}
		)
	return rows


def _run_surface(groups: set[str] | None) -> dict[str, Any]:
	try:
		from evals.changedetect import surface

		arts = surface.collect(groups)
		changes = _changes_to_rows(surface.compare(arts))
		return {
			"artifacts": len(arts),
			"changes": changes,
			"summary": surface.summarize([c for c in surface.compare(arts)]),
		}
	except Exception as exc:  # noqa: BLE001 — 采集失败必须可见，不得静当"无变化"
		return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "changes": []}


def _run_trace(batteries: set[str] | None) -> dict[str, Any]:
	if not batteries:
		return {"status": "skipped", "changes": [], "batteries": []}
	try:
		from evals.changedetect import trace

		traces = trace.collect(batteries)
		changes = _changes_to_rows(trace.compare(traces))
		return {
			"status": "ok",
			"batteries": sorted(batteries),
			"scenarios": len(traces),
			"changes": changes,
		}
	except Exception as exc:  # noqa: BLE001
		return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "changes": []}


def run(
	*,
	groups: Iterable[str] | None = None,
	batteries: Iterable[str] | None = ("inject",),
	watch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	"""跑一次 A0：模型可见面 vs golden + 确定性轨迹 vs golden（零 provider 调用）。

	``batteries=None``/``()`` 只跑 L0；``("inject","loop")`` 会额外跑 FakeModelClient
	驱动的确定性回路——它仍是本地重算，不是模型请求。
	"""
	used_groups = {_s(g) for g in groups if _s(g)} or None
	used_batteries = {_s(b) for b in batteries if _s(b)} or None
	surface_part = _run_surface(used_groups)
	trace_part = _run_trace(used_batteries)
	changes = list(surface_part.get("changes") or []) + list(trace_part.get("changes") or [])
	constraints: dict[str, int] = {}
	for row in changes:
		key = row["mechanical_constraint"]
		constraints[key] = constraints.get(key, 0) + 1
	return {
		"mode": MODE,
		"ruleset_version": RULESET_VERSION,
		"generated_at": round(time.time(), 3),
		"provider_calls": 0,
		"surface": surface_part,
		"trace": trace_part,
		"prompt_watch": dict(watch or {}),
		"changed_count": len(changes),
		"changed_chars": {
			"added": sum(int(r["added_chars"]) for r in changes),
			"removed": sum(int(r["removed_chars"]) for r in changes),
		},
		"mechanical_constraints": [
			{"constraint": name, "affected_changes": count}
			for name, count in sorted(constraints.items(), key=lambda kv: (-kv[1], kv[0]))
		],
		"claims": {
			"model_behaviour_improvement": False,
			"task_success": False,
			"allowed_conclusion": _ALLOWED_CONCLUSION,
			"forbidden_conclusion": _FORBIDDEN_CONCLUSION,
		},
		"coverage_gap": (
			"A0 看不到模型实际行为，也看不到未被 changedetect 覆盖的运行时路径；"
			"golden 未登记的新 artifact 只报 added，不评价好坏。"
		),
	}


# --------------------------------------------------------------------------
# 提示词文件变更探测（合并短时间内的反复保存）
# --------------------------------------------------------------------------


def watch_path() -> Path:
	return store.diagnostics_root() / "a0" / "prompt_watch.json"


def default_roots() -> list[Path]:
	return [_PYTHON_ROOT / "prompt"]


def _scan(roots: Iterable[Path]) -> dict[str, dict[str, Any]]:
	"""扫出提示词文件的当前状态：内容 sha + mtime + 字节数。

	sha 判"内容是否真的变了"，mtime 判"是不是又一次保存"——两者缺一不可：只改
	mtime 不是变更，改回原内容也不算变更。
	"""
	out: dict[str, dict[str, Any]] = {}
	for root in roots:
		base = Path(root)
		if not base.is_dir():
			continue
		for path in sorted(base.rglob("*")):
			if not path.is_file() or path.suffix not in (".py", ".md", ".txt"):
				continue
			if any(part in {"__pycache__", ".mypy_cache"} for part in path.parts):
				continue
			try:
				st = path.stat()
				data = path.read_bytes()
			except OSError:
				continue
			key = path.resolve().as_posix()
			out[key] = {
				"rel": _relative_marker(path, base),
				"sha": hashlib.sha256(data).hexdigest()[:32],
				"mtime": round(float(st.st_mtime), 6),
				"bytes": int(st.st_size),
			}
	return out


def _relative_marker(path: Path, root: Path) -> str:
	"""映射表按 ``prompt/...`` / ``tools/...`` 相对路径写，这里还原成同一形状。

	仓库外的观察根（测试夹具、另一个 checkout）按"根目录名/文件"回退，映射规则
	保持同一套，不需要为测试另开一条判定。
	"""
	target = path.resolve()
	try:
		return target.relative_to(_PYTHON_ROOT).as_posix()
	except ValueError:
		pass
	try:
		return target.relative_to(root.resolve().parent).as_posix()
	except ValueError:
		return target.name


def _baseline_record(meta: Mapping[str, Any], ts: float) -> dict[str, Any]:
	return {
		"rel": _s(meta.get("rel")),
		"settled_sha": _s(meta.get("sha")),
		"pending_sha": _s(meta.get("sha")),
		"pending_mtime": meta.get("mtime"),
		"saves": 0,
		"first_seen": ts,
		"last_seen": ts,
		"gone": False,
	}


def prompt_file_changes(
	*,
	roots: Iterable[str | Path] | None = None,
	debounce_sec: float = DEFAULT_DEBOUNCE_SEC,
	now: float | None = None,
	persist: bool = True,
) -> dict[str, Any]:
	"""检测提示词文件变更，并把去抖窗口内的反复保存合并成一次事件。

	合并的理由是事实性的：每次保存都重扫全部会话会把 A0 变成噪声源。判据是"内容
	是否又变了 + 距上次保存是否已过窗口"；改回原内容不产生事件；窗口未过只报
	``pending``，下游据此跳过重扫。
	"""
	window = max(0.0, float(debounce_sec))
	ts = time.time() if now is None else float(now)
	used_roots = [Path(r) for r in (roots or default_roots())]
	path = watch_path()
	state = store.read_json(path) or {}
	files = state.get("files") if isinstance(state.get("files"), dict) else {}
	state["files"] = files
	seen = _scan(used_roots)
	events: list[dict[str, Any]] = []
	pending: list[dict[str, Any]] = []

	for key, meta in seen.items():
		rec = files.get(key)
		if rec is None:
			files[key] = _baseline_record(meta, ts)
			continue
		same_content = _s(rec.get("pending_sha")) == _s(meta.get("sha"))
		same_save = rec.get("pending_mtime") == meta.get("mtime") and not rec.get("gone")
		if same_content and same_save:
			continue  # 没有新保存
		if _s(meta.get("sha")) == _s(rec.get("settled_sha")):
			# 净变化为零（撤销/回滚）：关闭挂起 episode，不发事件，也不计数。
			rec.update(
				{"pending_sha": _s(meta.get("sha")), "pending_mtime": meta.get("mtime"),
				 "saves": 0, "gone": False, "last_seen": ts}
			)
			continue
		in_window = int(rec.get("saves") or 0) > 0 and (ts - float(rec.get("last_seen") or ts)) <= window
		if not in_window:
			rec["first_seen"] = ts
			rec["saves"] = 1
		else:
			rec["saves"] = int(rec.get("saves") or 0) + 1
		rec.update(
			{"pending_sha": _s(meta.get("sha")), "pending_mtime": meta.get("mtime"),
			 "gone": False, "last_seen": ts, "bytes": int(meta.get("bytes") or 0)}
		)

	for key in [k for k in files if k not in seen]:
		# 文件消失同样走去抖：删掉又立刻重建不该触发两次重扫。
		rec = files[key]
		if rec.get("gone"):
			if rec.get("pending_mtime") == _GONE_MARK and (ts - float(rec.get("last_seen") or ts)) < window:
				continue
		else:
			rec["gone"] = True
			rec["pending_sha"] = _GONE_MARK
			rec["pending_mtime"] = _GONE_MARK
			rec["last_seen"] = ts
			if int(rec.get("saves") or 0) == 0:
				rec["first_seen"] = ts
				rec["saves"] = 1
			else:
				rec["saves"] = int(rec.get("saves") or 0) + 1

	for key, rec in list(files.items()):
		before = _s(rec.get("settled_sha"))
		after = _s(rec.get("pending_sha"))
		if before == after:
			continue
		age = ts - float(rec.get("last_seen") or ts)
		label = _s(rec.get("rel"))
		if age < window:
			pending.append(
				{
					"path": label,
					"saves_so_far": int(rec.get("saves") or 0),
					"settles_in_sec": round(window - age, 3),
					"gone": bool(rec.get("gone")),
				}
			)
			continue
		events.append(
			{
				"path": label,
				"change": "removed" if rec.get("gone") else "modified",
				"before_sha": before,
				"after_sha": "" if rec.get("gone") else after,
				"merged_saves": max(1, int(rec.get("saves") or 1)),
				"first_seen": rec.get("first_seen"),
				"last_seen": rec.get("last_seen"),
				"settled": True,
				"affected_surfaces": _constraints_for_path(label),
			}
		)
		if rec.get("gone"):
			files.pop(key, None)
			continue
		rec["settled_sha"] = after
		rec["saves"] = 0

	state["updated_at"] = round(ts, 3)
	state["debounce_sec"] = window
	state["roots"] = [r.resolve().as_posix() for r in used_roots]
	if persist:
		store.ensure_dirs()
		store.write_json(path, state)
	return {
		"mode": MODE,
		"detector": "prompt_file_changes",
		"changed": bool(events),
		"events": events,
		"pending": pending,
		"debounce_sec": window,
		"watched_files": len(seen),
		"state_locator": str(path),
		"persisted": bool(persist),
		"allowed_conclusion": "只说明哪个提示词文件被改、影响到哪个可见面；不评价改动好坏。",
	}


def to_markdown(result: Mapping[str, Any]) -> str:
	"""人读版本：改动清单 + 受影响机械约束，并显式声明它不证明表现提高。"""
	lines = ["# A0 静态差异与确定性重算", ""]
	lines.append(f"- 生成时间：{result.get('generated_at')}")
	lines.append(f"- provider 调用：**{result.get('provider_calls', 0)}**（本模式不发请求）")
	surface_part = result.get("surface") or {}
	trace_part = result.get("trace") or {}
	lines.append(f"- L0 可见文本面：{surface_part.get('artifacts', 0)} 个 artifact")
	lines.append(f"- L1 确定性轨迹：{trace_part.get('status')} / {trace_part.get('scenarios', 0)} 个场景")
	lines.append(f"- 变化条目：**{result.get('changed_count', 0)}**")
	lines += ["", "## 改了什么", ""]
	changes = list(surface_part.get("changes") or []) + list(trace_part.get("changes") or [])
	if not changes:
		lines.append("未检出与 golden 的差异（不等于没有问题被修好）。")
	for row in changes[:80]:
		lines.append(
			"- `{}` {}：{} → {} 字符（+{}/-{}）".format(
				row.get("name"),
				row.get("status"),
				row.get("chars_before"),
				row.get("chars_after"),
				row.get("added_chars"),
				row.get("removed_chars"),
			)
		)
	if len(changes) > 80:
		lines.append(f"- …其余 {len(changes) - 80} 条")
	lines += ["", "## 受影响的机械约束", ""]
	items = result.get("mechanical_constraints") or []
	if not items:
		lines.append("无：没有变化触碰到登记表里的机械约束。")
	for item in items:
		lines.append(f"- {item.get('constraint')}（相关变化 {item.get('affected_changes')} 处）")
	watch = result.get("prompt_watch") or {}
	if watch:
		lines += ["", "## 提示词文件变更（已合并重复保存）", ""]
		events = watch.get("events") or []
		if not events:
			lines.append("窗口内无已稳定的提示词文件变更。")
		for event in events:
			lines.append(
				"- `{}` {}：合并 {} 次保存，影响面 {}".format(
					event.get("path"),
					event.get("change"),
					event.get("merged_saves"),
					"、".join(event.get("affected_surfaces") or []) or "未归类",
				)
			)
		for item in watch.get("pending") or []:
			lines.append(
				f"- `{item.get('path')}` 仍在去抖窗口内（再 {item.get('settles_in_sec')}s 结算），本次不重扫。"
			)
	lines += ["", "## 结论边界", ""]
	lines.append(str((result.get("claims") or {}).get("allowed_conclusion")))
	lines.append(str((result.get("claims") or {}).get("forbidden_conclusion")))
	lines.append(f"覆盖缺口：{result.get('coverage_gap')}")
	return "\n".join(lines) + "\n"


__all__ = [
	"DEFAULT_DEBOUNCE_SEC",
	"MODE",
	"RULESET_VERSION",
	"default_roots",
	"prompt_file_changes",
	"run",
	"to_markdown",
	"watch_path",
]
