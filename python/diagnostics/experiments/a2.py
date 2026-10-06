"""A2 —— 隔离环境中的真实任务配对（设计 §7 A2 / §8）。

先证明隔离，再跑；证明不了就停在 A0/A1 并列出缺什么——不把近似环境称作同检查点实验。

隔离的具体含义（都是机器可查的条件，不是声明口号）：
  * 文件：从同一份工作区导出两份**一次性副本**，两臂只在副本里跑；原任务工作区
    绝不作为任何一臂，跑完还会复核原工作区未被改动。
  * 进程：两臂各起**独立子进程**（不在本进程改 ``os.environ``），环境变量、
    WSC 内存态、session cache、工具态全部指向各自目录。
  * 外部副作用：带外部写入的工具默认不进配对；进程类工具要求显式的进程隔离档。
  * 共享 git 操作（快照）按 ``coord.locking.FileGuard`` 串行化。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from diagnostics import store
from diagnostics.identity import _s
from diagnostics.experiments.manifest import ARMS, digest, file_inventory, inventory_digest

MODE = "a2"

#: 只有这些文件隔离档能证明"臂内写入不会逃出去"。仅临时 cwd / git worktree 不算。
PROVEN_FILE_ISOLATION = frozenset({"throwaway_copy", "container", "vm"})
#: 进程隔离档：worktree 与临时 cwd 共用宿主进程与系统状态，不满足 A2。
PROVEN_PROCESS_ISOLATION = frozenset({"subprocess_isolated", "container", "vm"})
#: 外部副作用档：必须显式声明为 none / read_only_stable 才允许。
PROVEN_EXTERNAL = frozenset({"none", "read_only_recorded"})

#: 与 ``tools/tool_registry.py::_side_effect_class`` 同语义的分类表：
#: none / write / process / external。external 一律默认排除（可能有外部写入）。
TOOL_NONE = frozenset(
	{
		"Read", "Glob", "Grep", "NotebookRead", "get_time", "journal_query",
		"diagnostics", "AskUserQuestion", "echo",
	}
)
TOOL_WRITE = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
TOOL_PROCESS = frozenset({"Bash", "job_kill", "Agent"})

DEFAULT_MAX_WALL_SEC = 600.0


class A2Error(RuntimeError):
	"""A2 层的中性错误。"""


def tool_effect_class(name: str) -> str:
	"""工具副作用归类（决定它能不能进 A2 臂）。未知一律按 external 处理。"""
	clean = _s(name)
	if clean in TOOL_NONE:
		return "none"
	if clean in TOOL_WRITE:
		return "write"
	if clean in TOOL_PROCESS:
		return "process"
	return "external"


# 准入判定


def eligibility(task_spec: Mapping[str, Any]) -> dict[str, Any]:
	"""能不能跑 A2。返回 ``{ok, missing:[机器可读码], checked:{...}}``。

	判据缺失即视为不具备条件（fail closed）：宁可停在 A0/A1，不在等价环境上跑真任务。
	"""
	spec = dict(task_spec or {})
	isolation = dict(spec.get("isolation") or {})
	workspace = dict(spec.get("workspace") or {})
	verifier = dict(spec.get("verifier") or {})
	missing: list[str] = []

	files = _s(isolation.get("files")).lower()
	processes = _s(isolation.get("processes")).lower()
	external = _s(isolation.get("external")).lower()
	if files not in PROVEN_FILE_ISOLATION:
		missing.append(f"file_isolation_not_proven:{files or 'unset'}")
	if processes not in PROVEN_PROCESS_ISOLATION:
		missing.append(f"process_isolation_not_proven:{processes or 'unset'}")
	if external not in PROVEN_EXTERNAL:
		missing.append(f"external_side_effects_not_proven:{external or 'unset'}")

	tools = [_s(t) for t in (spec.get("tools") or []) if _s(t)]
	if not tools:
		missing.append("tool_surface_undeclared")
	for name in sorted({t for t in tools if tool_effect_class(t) == "external"}):
		missing.append(f"external_effect_tool_excluded:{name}")
	if processes not in PROVEN_PROCESS_ISOLATION:
		for name in sorted({t for t in tools if tool_effect_class(t) == "process"}):
			missing.append(f"process_effect_tool_needs_isolation:{name}")

	root = _s(workspace.get("root"))
	if not root:
		missing.append("workspace_root_undeclared")
		inv: dict[str, Any] = {"entries": [], "count": 0}
	else:
		inv = file_inventory(root)
	ignored_needed = [_s(p).replace("\\", "/") for p in (spec.get("depends_on_ignored") or []) if _s(p)]
	supplied = {_s(p).replace("\\", "/") for p in (spec.get("supplied_ignored") or []) if _s(p)}
	for path in sorted(set(ignored_needed) - supplied):
		# 依赖 ignored 数据又没显式补入 ⇒ 两臂拿不到同一份输入，不构成同检查点。
		missing.append(f"ignored_dependency_not_supplied:{path}")

	arm_root = _s(workspace.get("arm_root"))
	if arm_root and root and Path(arm_root).resolve() == Path(root).resolve():
		missing.append("original_workspace_used_as_arm")

	name = _s(verifier.get("name"))
	command = _s(verifier.get("command"))
	if not name:
		missing.append("verifier_missing")
	if name and not command:
		missing.append("verifier_command_missing")
	allowed = [_s(c) for c in (verifier.get("allowed_commands") or []) if _s(c)]
	if command and command not in allowed:
		missing.append("verifier_command_not_allowed")

	profile = dict(spec.get("runtime_profile") or {})
	if profile and bool(profile.get("human_interaction", True)):
		missing.append("runtime_profile_interactive")
	if not profile:
		missing.append("runtime_profile_undeclared")

	if int(inv.get("count") or 0) <= 0 and root and Path(root).is_dir():
		missing.append("workspace_inventory_empty_or_unreadable")

	return {
		"mode": MODE,
		"ok": not missing,
		"missing": sorted(missing),
		"checked": {
			"isolation": {"files": files, "processes": processes, "external": external},
			"tools": sorted(set(tools)),
			"tool_effect_classes": {t: tool_effect_class(t) for t in sorted(set(tools))},
			"ignored_dependencies": sorted(set(ignored_needed)),
			"supplied_ignored": sorted(supplied),
			"workspace_root": root,
			"workspace_file_count": int(inv.get("count") or 0),
			"workspace_inventory_digest": inventory_digest(inv),
			"verifier_name": name,
			"verifier_version": _s(verifier.get("version")),
		},
		"statement": (
			"具备 A2 条件：文件、进程、外部副作用三项均已被机器核验为隔离。"
			if not missing
			else "不具备 A2 条件：停在 A0/A1；上述缺项未补齐前不得把近似环境标为同检查点实验。"
		),
	}


# 快照与副本


def _git_lock_path() -> Path:
	return store.diagnostics_root() / "locks" / "a2-shared-git.lock"


def snapshot_workspace(root: str | Path, *, message: str = "xeyo a2 snapshot") -> dict[str, Any]:
	"""固定工作区快照（共享 git 操作 ⇒ 跨进程串行）。

	``ShadowGit.snapshot`` 只覆盖未被忽略的 dirty/untracked 内容；快照 commit 只是
	**来源引用**，本模块不从快照恢复目录（没有那样的 API），副本导出走工作区复制，
	并用清单 hash 证明两臂起点一致。
	"""
	base = Path(root)
	from coord.locking import FileGuard

	store.ensure_dirs()
	lock = _git_lock_path()
	acquired: bool | None = None
	with FileGuard(lock, ttl=30.0, timeout=15.0) as ok:
		acquired = bool(ok)
		if not ok:
			return {"status": "lock_contended", "commit": "", "shared_lock": False}
		try:
			from engine.shadow_git import ShadowGit

			commit = _s(ShadowGit(str(base)).snapshot(message=message))
			status = "ok" if commit else "no_commit"
		except Exception as exc:  # noqa: BLE001 — 快照不可得必须可见，不得假装隔离好了
			commit = ""
			status = f"snapshot_failed:{type(exc).__name__}"
	return {
		"status": status,
		"commit": commit,
		"shared_lock": acquired,
		"root": base.name,
		"probed_at": round(time.time(), 3),
	}


def export_copies(source_root: str | Path, *, dest_parent: str | Path) -> dict[str, Any]:
	"""把同一份工作区导出成两份一次性副本，并核验两臂起始清单/hash 一致。"""
	src = Path(source_root)
	parent = Path(dest_parent)
	ignore = shutil.ignore_patterns(".git", ".xy-shadow-git", ".xeyo", "__pycache__", ".pytest_cache")
	copies: dict[str, Any] = {}
	for arm in ARMS:
		dest = parent / "arms" / arm / "ws"
		dest.mkdir(parents=True, exist_ok=True)
		shutil.copytree(src, dest, ignore=ignore, dirs_exist_ok=True)
		inv = file_inventory(dest)
		copies[arm] = {
			"path": str(dest),
			"inventory": inv,
			"inventory_digest": inventory_digest(inv),
			"file_count": int(inv.get("count") or 0),
		}
	identical = copies["A"]["inventory_digest"] == copies["B"]["inventory_digest"]
	source_inv = file_inventory(src)
	source_digest_now = inventory_digest(source_inv)
	return {
		"copies": copies,
		"identical": identical,
		"digests": {arm: copies[arm]["inventory_digest"] for arm in ARMS},
		"source_digest_before": source_digest_now,
		"source_matches_copies": source_digest_now == copies["A"]["inventory_digest"],
		"export_source": "working_tree_copy",
	}


# 子进程边界


def arm_env(*, experiment_home: str | Path, arm: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
	"""一臂的子进程环境：所有可写状态各自一份，绝不与兄弟臂或原工作区共用。"""
	root = Path(experiment_home) / arm
	env = {
		"XEYO_HOME": str(root),
		"XEYO_DATA_DIR": str(root),
		"XEYO_SESSIONS_DIR": str(root / "sessions"),
		"XEYO_USAGE_DIR": str(root / "usage"),
		"XEYO_SPILL_DIR": str(root / "spill"),
		"XEYO_SNAPSHOTS_DIR": str(root / "snapshots"),
		"XEYO_DIAGNOSTICS_DIR": str(root / "diagnostics"),
		"XEYO_AUDIT_LOG": str(root / "audit.jsonl"),
		"PYTHONDONTWRITEBYTECODE": "1",
	}
	env.update({_s(k): _s(v) for k, v in dict(extra or {}).items() if _s(k)})
	return env


def arm_argv(spec_path: str | Path, *, python: str | None = None) -> list[str]:
	"""两臂各起一个独立子进程跑 ``diagnostics.experiments.worker``。"""
	return [python or sys.executable, "-m", "diagnostics.experiments.worker", "--spec", str(spec_path)]


def default_runner(
	argv: list[str],
	*,
	env: Mapping[str, str],
	cwd: str | Path,
	timeout: float,
) -> dict[str, Any]:
	"""真正的一次子进程执行（测试用注入的 runner 替掉它）。"""
	full = {**os.environ, **dict(env)}
	try:
		proc = subprocess.run(  # noqa: S603 — argv 由本模块构造，不含用户输入拼接
			list(argv),
			cwd=str(cwd),
			env=full,
			capture_output=True,
			timeout=max(0.1, float(timeout)),
			encoding="utf-8",
			errors="replace",
		)
	except subprocess.TimeoutExpired as exc:
		return {
			"returncode": None,
			"timed_out": True,
			"stdout_tail": _tail(exc.stdout),
			"stderr_tail": _tail(exc.stderr),
		}
	except OSError as exc:
		return {"returncode": None, "timed_out": False, "error": f"{type(exc).__name__}: {exc}"}
	return {
		"returncode": proc.returncode,
		"timed_out": False,
		"stdout_tail": _tail(proc.stdout),
		"stderr_tail": _tail(proc.stderr),
	}


def _tail(value: Any) -> str:
	if value is None:
		return ""
	if isinstance(value, bytes):
		value = value.decode("utf-8", errors="replace")
	return _s(value)[-2000:]


def verifier_argv(command: str) -> list[str]:
	"""verifier 以独立子进程执行；两臂跑**同一条**命令、同一个版本。"""
	if os.name == "nt":
		return ["cmd", "/c", command]
	return ["sh", "-c", command]


def run_verifier(
	verifier: Mapping[str, Any],
	*,
	cwd: str | Path,
	timeout: float = 120.0,
	runner: Callable[..., dict[str, Any]] | None = None,
	env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
	"""跑验收器：退出码为 None 表示"没跑成"，与"跑了但失败"分开记（§6.1 最后一行）。"""
	run = runner or default_runner
	command = _s(verifier.get("command"))
	if not command:
		return {"ran": False, "exit_code": None, "reason": "verifier_command_missing"}
	result = run(verifier_argv(command), env=dict(env or {}), cwd=cwd, timeout=timeout)
	exit_code = result.get("returncode")
	out_ref = ""
	if exit_code is None:
		reason = "timed_out" if result.get("timed_out") else _s(result.get("error")) or "spawn_failed"
	elif exit_code == 0:
		reason = "passed"
	else:
		reason = "failed"
	return {
		"ran": exit_code is not None,
		"exit_code": exit_code,
		"passed": exit_code == 0,
		"reason": reason,
		"command": command,
		"verifier_version": _s(verifier.get("version")),
		"output_tail": _tail(result.get("stdout_tail")) + _tail(result.get("stderr_tail")),
		"wall_ms": int(result.get("wall_ms") or 0),
	}


# 顶层：跑一次 A2 配对


def run_pair(
	*,
	task_spec: Mapping[str, Any],
	experiment_id: str,
	variants: Mapping[str, Mapping[str, Any]],
	arm_home: str | Path | None = None,
	budget: Any = None,
	runner: Callable[..., dict[str, Any]] | None = None,
	timeout_sec: float | None = None,
	python: str | None = None,
) -> dict[str, Any]:
	"""跑 A2（先过隔离准入，再落盘两臂副本，再各起一个子进程，最后跑同一个 verifier）。"""
	spec = dict(task_spec or {})
	gate = eligibility(spec)
	if not gate.get("ok"):
		return {
			"mode": MODE,
			"started": False,
			"refused": True,
			"eligibility": gate,
			"arms": {},
			"pairing": _pairing_counts({}),
			"statement": gate["statement"],
		}
	run = runner or default_runner
	wall = float(timeout_sec or spec.get("max_wall_sec") or DEFAULT_MAX_WALL_SEC)
	home = Path(arm_home) if arm_home else store.experiments_dir() / _s(experiment_id)
	home.mkdir(parents=True, exist_ok=True)

	snapshot = snapshot_workspace(_s((spec.get("workspace") or {}).get("root")))
	if _s(snapshot.get("status")) != "ok":
		return {
			"mode": MODE,
			"started": False,
			"refused": True,
			"eligibility": gate,
			"snapshot": snapshot,
			"arms": {},
			"pairing": _pairing_counts({}),
			"statement": "快照不可得 ⇒ 无法固定两臂的共同起点，已停止。",
		}
	copies = export_copies(_s((spec.get("workspace") or {}).get("root")), dest_parent=home)
	if not copies.get("identical"):
		return {
			"mode": MODE,
			"started": False,
			"refused": True,
			"eligibility": gate,
			"snapshot": snapshot,
			"copies": {arm: copies["copies"][arm]["inventory_digest"] for arm in ARMS},
			"arms": {},
			"pairing": _pairing_counts({}),
			"statement": "两臂起始清单/hash 不一致 ⇒ 不是同一起点，已停止。",
		}

	results: dict[str, Any] = {}
	for arm in ARMS:
		results[arm] = _run_arm(
			arm=arm,
			spec=spec,
			variant=dict((variants or {}).get(arm) or {}),
			experiment_id=_s(experiment_id),
			copies=copies,
			home=home,
			budget=budget,
			run=run,
			wall=wall,
			python=python,
		)
	compare = compare_arms(results)
	original = file_inventory(_s((spec.get("workspace") or {}).get("root")))
	return {
		"mode": MODE,
		"started": True,
		"refused": False,
		"eligibility": gate,
		"snapshot": snapshot,
		"export": {
			"identical": True,
			"digests": {arm: copies["copies"][arm]["inventory_digest"] for arm in ARMS},
			"source_matches_copies": copies.get("source_matches_copies"),
			"export_source": copies.get("export_source"),
		},
		"arms": results,
		"compare": compare,
		"pairing": compare["pairing"],
		"original_workspace": {
			"inventory_digest_now": inventory_digest(original),
			"inventory_digest_before": copies.get("source_digest_before"),
			"modified": inventory_digest(original) != copies.get("source_digest_before"),
		},
		"coverage_gap": (
			"A2 的两臂副本只含工作区文件；ignored 依赖、系统级配置、外部服务状态未包含时，"
			"结果只能代表副本环境。"
		),
	}


def _run_arm(
	*,
	arm: str,
	spec: Mapping[str, Any],
	variant: Mapping[str, Any],
	experiment_id: str,
	copies: Mapping[str, Any],
	home: Path,
	budget: Any,
	run: Callable[..., dict[str, Any]],
	wall: float,
	python: str | None,
) -> dict[str, Any]:
	cwd = _s((copies["copies"][arm] or {}).get("path"))
	env = arm_env(experiment_home=home / "run", arm=arm, extra=dict(variant.get("env") or {}))
	arm_spec = {
		"experiment_id": experiment_id,
		"arm": arm,
		"task": _s(spec.get("task")),
		"workspace": cwd,
		"session_id": _s(variant.get("session_id")) or f"a2_{experiment_id[:16]}_{arm}",
		"model_backend": _s(spec.get("model_backend")) or "fake",
		"model": _s(spec.get("model")),
		"provider": _s(spec.get("provider")),
		"base_url": _s(spec.get("base_url")),
		"max_turns": spec.get("max_turns"),
		"deadline_sec": max(1.0, wall - 5.0),
		"variant_env": {_s(k): _s(v) for k, v in dict(variant.get("engine_env") or {}).items()},
		"result_path": str(home / "run" / arm / "arm-result.json"),
	}
	spec_path = home / "run" / arm / "spec.json"
	spec_path.parent.mkdir(parents=True, exist_ok=True)
	store.write_json(spec_path, arm_spec)
	key = f"{experiment_id}#{arm}#1"
	gate: dict[str, Any] = {"allowed": True, "reason": "no_budget_gate"}
	if budget is not None:
		gate = budget.reserve(
			key,
			max_input_tokens=variant.get("max_input_tokens") or spec.get("max_input_tokens"),
			max_output_tokens=variant.get("max_output_tokens") or spec.get("max_output_tokens"),
			billing_class=_s(spec.get("billing_class")) or "unknown",
			arm=arm,
		)
	if not gate.get("allowed"):
		return {
			"arm": arm,
			"sent": False,
			"invalid": True,
			"invalid_reason": f"reservation_denied:{_s(gate.get('reason'))}",
			"workspace": cwd,
			"budget": gate,
			"verifier": {"ran": False, "exit_code": None, "reason": "not_started"},
		}
	proc = run(arm_argv(spec_path, python=python), env=env, cwd=cwd, timeout=wall)
	payload = store.read_json(Path(arm_spec["result_path"])) or {}
	cost_row: dict[str, Any] = {}
	if budget is not None:
		if payload and proc.get("returncode") == 0:
			cost_row = budget.reconcile(
				key,
				payload.get("usage"),
				provider=_s(spec.get("provider")),
				model=_s(spec.get("model")),
			)
		else:
			# 子进程没回来 / 没写结果：可能仍在计费 ⇒ 保留该次最大预留。
			cost_row = budget.abandon(key, reason="timeout" if proc.get("timed_out") else "arm_crashed")
	invalid_reason = ""
	if proc.get("returncode") not in (0,) or not payload:
		invalid_reason = "arm_timeout" if proc.get("timed_out") else "arm_no_result"
	verifier = run_verifier(
		dict(spec.get("verifier") or {}),
		cwd=cwd,
		runner=run,
		env=env,
		timeout=min(wall, float(spec.get("verifier_timeout_sec") or 120.0)),
	)
	return {
		"arm": arm,
		"sent": True,
		"invalid": bool(invalid_reason),
		"invalid_reason": invalid_reason,
		"workspace": cwd,
		"process": {
			"returncode": proc.get("returncode"),
			"timed_out": bool(proc.get("timed_out")),
			"error": _s(proc.get("error")),
			"stderr_tail": _s(proc.get("stderr_tail"))[-500:],
		},
		"env_keys": sorted(env),
		"spec": arm_spec,
		"run": payload,
		"budget": cost_row or gate,
		"verifier": verifier,
		"passed": bool(verifier.get("passed")) and not invalid_reason,
	}


def compare_arms(results: Mapping[str, Any]) -> dict[str, Any]:
	"""分别报维度，不合成总分；无效运行也进计数与账。"""
	pairing = _pairing_counts(results)
	dimensions: dict[str, Any] = {
		"task": {
			arm: {
				"verifier_ran": bool((row.get("verifier") or {}).get("ran")),
				"exit_code": (row.get("verifier") or {}).get("exit_code"),
				"reason": _s((row.get("verifier") or {}).get("reason")),
				"verifier_version": _s((row.get("verifier") or {}).get("verifier_version")),
				"passed": bool(row.get("passed")),
			}
			for arm, row in results.items()
		},
		"change": {
			arm: {
				"inventory_digest_before": _s((row.get("spec") or {}).get("workspace_digest")),
				"files_touched": int((row.get("run") or {}).get("files_touched") or 0),
				"needs_review": True,
			}
			for arm, row in results.items()
		},
		"behaviour": {
			arm: {
				"turns": int((row.get("run") or {}).get("turns") or 0),
				"tool_calls": int((row.get("run") or {}).get("tool_calls") or 0),
				"retries": int((row.get("run") or {}).get("retries") or 0),
				"repeated_errors": int((row.get("run") or {}).get("repeated_errors") or 0),
			}
			for arm, row in results.items()
		},
		"context": {
			arm: {
				"model_requests": int((row.get("run") or {}).get("model_requests") or 0),
				"hit_tokens": int((row.get("run") or {}).get("hit_tokens") or 0),
				"miss_tokens": int((row.get("run") or {}).get("miss_tokens") or 0),
				"out_tokens": int((row.get("run") or {}).get("out_tokens") or 0),
			}
			for arm, row in results.items()
		},
		"performance": {
			arm: {
				"wall_ms": int((row.get("run") or {}).get("wall_ms") or 0),
				"timed_out": bool((row.get("process") or {}).get("timed_out")),
			}
			for arm, row in results.items()
		},
		"cost": {
			arm: {
				"spent_cny": (row.get("budget") or {}).get("spent_cny"),
				"usage_seen": bool((row.get("budget") or {}).get("usage_seen")),
				"basis": "按 usage 估算（非账单实付）",
			}
			for arm, row in results.items()
		},
	}
	return {"pairing": pairing, "dimensions": dimensions, "blended_score": None}


def _pairing_counts(results: Mapping[str, Any]) -> dict[str, Any]:
	"""A-only / B-only / 均通过 / 均失败 / 无效。无效不是"失败"，单列一类。"""
	out = {"a_only_pass": 0, "b_only_pass": 0, "both_pass": 0, "both_fail": 0, "invalid": 0, "pairs": 0}
	a = results.get("A") or {}
	b = results.get("B") or {}
	if not a and not b:
		return out
	if a.get("invalid") or b.get("invalid") or not a or not b:
		out["invalid"] += 1
		return out
	out["pairs"] = 1
	if a.get("passed") and b.get("passed"):
		out["both_pass"] += 1
	elif a.get("passed"):
		out["a_only_pass"] += 1
	elif b.get("passed"):
		out["b_only_pass"] += 1
	else:
		out["both_fail"] += 1
	return out


def to_markdown(result: Mapping[str, Any]) -> str:
	lines = ["# A2 隔离环境真实任务配对", ""]
	if result.get("refused"):
		lines.append("## 未启动：隔离条件不足")
		lines.append("")
		lines.append(str(_s(result.get("statement"))))
		for item in (result.get("eligibility") or {}).get("missing") or []:
			lines.append(f"- 缺项：`{item}`")
		return "\n".join(lines) + "\n"
	gate = result.get("eligibility") or {}
	lines.append(f"- 准入：{', '.join(_s(k) + '=' + _s(v) for k, v in (gate.get('checked') or {}).get('isolation', {}).items())}")
	snap = result.get("snapshot") or {}
	lines.append(f"- 工作区快照：`{_s(snap.get('commit')) or '—'}`（共享 git 锁：{snap.get('shared_lock')}）")
	export = result.get("export") or {}
	lines.append(f"- 两臂起始清单一致：{export.get('identical')}；导出来源：{_s(export.get('export_source'))}")
	original = result.get("original_workspace") or {}
	lines.append(f"- 原工作区未被用作臂、且运行后未改动：{not original.get('modified')}")
	lines += ["", "## 分维度结果（不合成总分）", ""]
	dimensions = (result.get("compare") or {}).get("dimensions") or {}
	for name in ("task", "change", "behaviour", "context", "performance", "cost"):
		part = dimensions.get(name) or {}
		if not part:
			continue
		lines.append(f"### {name}")
		lines.append("")
		for arm in sorted(part):
			values = part[arm]
			lines.append(
				f"- 臂 {arm}：" + "；".join(f"{k}={values[k]}" for k in sorted(values))
			)
		lines.append("")
	lines += ["## 配对计数", ""]
	pairing = result.get("pairing") or {}
	for key in ("pairs", "a_only_pass", "b_only_pass", "both_pass", "both_fail", "invalid"):
		lines.append(f"- {key}：{pairing.get(key, 0)}")
	lines.append("")
	lines.append("覆盖缺口：" + _s(result.get("coverage_gap")))
	return "\n".join(lines) + "\n"


__all__ = [
	"DEFAULT_MAX_WALL_SEC",
	"MODE",
	"PROVEN_EXTERNAL",
	"PROVEN_FILE_ISOLATION",
	"PROVEN_PROCESS_ISOLATION",
	"A2Error",
	"arm_argv",
	"arm_env",
	"compare_arms",
	"default_runner",
	"eligibility",
	"export_copies",
	"run_pair",
	"run_verifier",
	"snapshot_workspace",
	"to_markdown",
	"tool_effect_class",
	"verifier_argv",
]
