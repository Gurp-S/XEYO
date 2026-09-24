"""实验 manifest：发第一个请求之前把**全部可比面**落盘，且只允许写一次。

设计口径（§8）：两臂只允许声明的那一处不同，其余任何字段不同都不构成可比实验。
本模块只做记录与判定——不发请求、不评价好坏，也不把实验身份写进模型可见文本。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from diagnostics import store
from diagnostics.identity import _s

SCHEMA_VERSION = 1
ARMS = ("A", "B")
MODES = ("a0", "a1", "a2")

#: 每臂都必须一致的共享面（臂内可比文档由这些段落 + 该臂变体拼成）。
CONTEXT_SECTIONS = (
	"code",
	"runtime",
	"tools",
	"permissions",
	"workspace",
	"history",
	"model",
	"verifier",
	"budget",
)

#: 易变字段只属于 manifest 顶层与 results 行，绝不进臂文档，否则每次都比出"差异"。
VOLATILE_KEYS = frozenset(
	{
		"probed_at",
		"captured_at",
		"generated_at",
		"requested_at",
		"finished_at",
		"started_at",
		"ts",
		"wall_ms",
		"duration_ms",
		"locator",
	}
)

#: 不参与臂比较的上下文段落：本实验自己导出的产物位置（写盘时序必然逐臂不同）。
EXCLUDED_CONTEXT_SECTIONS = frozenset({"outputs"})

_INVENTORY_EXCLUDE_DIRS = frozenset(
	{
		".git",
		".xy-shadow-git",
		".xeyo",
		"__pycache__",
		".pytest_cache",
		".mypy_cache",
		".ruff_cache",
		"node_modules",
		".venv",
		"venv",
	}
)

_ABSENT = "\u0000__absent__"


class ManifestError(RuntimeError):
	"""manifest 层的中性错误（措辞是结果，不是建议）。"""


class ManifestImmutableError(ManifestError):
	"""manifest 已存在且内容不同：一个实验的输入定义不允许中途改写。"""


class SingleVariableViolation(ManifestError):
	"""两臂存在未声明的差异 ⇒ 拒绝启动。

	``reasons`` 是机器可读列表，调用方（runner）原样落盘，不改写成人话再判。
	"""

	def __init__(self, comparability: dict[str, Any]) -> None:
		self.comparability = dict(comparability)
		paths = [d.get("path") for d in comparability.get("undeclared") or []]
		codes = [r.get("code") for r in comparability.get("reasons") or []]
		super().__init__(f"pairing_rejected: {','.join(str(c) for c in codes)} :: {paths}")


def digest(payload: Any) -> str:
	"""稳定 hash：与 store/pins 同口径（sort_keys + ensure_ascii=False）。"""
	raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
	return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]


def flatten(payload: Any, *, prefix: str = "") -> dict[str, Any]:
	"""把嵌套文档压成 ``点号路径 → 叶子值``，用于逐字段比较。

	列表按下标展开：工具 schema 少一个字段、历史多一条消息都必须显式成为一条路径。
	"""
	out: dict[str, Any] = {}
	if isinstance(payload, Mapping):
		if not payload and prefix:
			out[prefix] = {}
		for key, value in payload.items():
			path = f"{prefix}.{_s(key)}" if prefix else _s(key)
			if isinstance(value, (Mapping, list, tuple)):
				out.update(flatten(value, prefix=path))
			else:
				out[path] = value
		return out
	if isinstance(payload, (list, tuple)):
		if not payload and prefix:
			out[prefix] = []
		for i, value in enumerate(payload):
			path = f"{prefix}.{i}"
			if isinstance(value, (Mapping, list, tuple)):
				out.update(flatten(value, prefix=path))
			else:
				out[path] = value
		return out
	out[prefix or "<root>"] = payload
	return out


def _brief(value: Any) -> dict[str, Any]:
	"""差异值的中性表示：长文本只留 hash 与长度，manifest 不复制提示词正文。"""
	if isinstance(value, str) and len(value) > 120:
		return {"kind": "text", "chars": len(value), "sha256": digest(value)}
	if isinstance(value, (list, tuple, dict)) or isinstance(value, Mapping):
		return {"kind": "structure", "digest": digest(value)}
	return {"kind": "scalar", "value": value}


def compare_arms(
	arms: Mapping[str, Mapping[str, Any]],
	*,
	allowed_differences: Iterable[str] = (),
) -> dict[str, Any]:
	"""逐字段比较两臂；返回 ok / differences / undeclared / reasons（全机器可读）。

	判定规则：
	  - ``arms_must_be_two``：臂数必须恰好是 A 与 B（三臂配对不属本实验面）。
	  - ``single_variable_violation``：出现未声明的差异即不成立。
	  - ``no_difference``：两臂逐字段相同 ⇒ 没有可比变量，实验没有意义。
	  - ``declared_difference_absent``：声明的变化项实际没变（同上，且说明声明写错）。
	"""
	allowed = [ _s(p) for p in allowed_differences if _s(p) ]
	declared = [p for p in allowed if p != "*"]
	names = sorted(arms)
	flat = {arm: flatten(arms[arm]) for arm in names}
	paths = sorted({path for values in flat.values() for path in values})
	differences: list[dict[str, Any]] = []
	for path in paths:
		values = {arm: flat[arm].get(path, _ABSENT) for arm in names}
		if len({digest(v) for v in values.values()}) <= 1:
			continue
		differences.append(
			{
				"path": path,
				"values": {arm: _brief(v) for arm, v in values.items()},
				"allowed": path in declared or "*" in declared,
			}
		)
	undeclared = [d for d in differences if not d["allowed"]]
	differing_paths = {d["path"] for d in differences}
	unmatched = sorted(p for p in declared if p not in differing_paths)

	reasons: list[dict[str, Any]] = []
	if names != list(ARMS):
		reasons.append({"code": "arms_must_be_two", "arms": names})
	if len(differences) > 1 or undeclared:
		reasons.append(
			{
				"code": "single_variable_violation",
				"undeclared": [d["path"] for d in undeclared],
				"all_differences": sorted(differing_paths),
			}
		)
	if not differences:
		reasons.append({"code": "no_difference"})
	elif unmatched:
		reasons.append({"code": "declared_difference_absent", "paths": unmatched})
	return {
		"ok": not reasons,
		"allowed_differences": allowed,
		"differences": [d["path"] for d in differences],
		"difference_detail": differences,
		"undeclared": undeclared,
		"declared_but_identical": unmatched,
		"reasons": reasons,
		"statement": (
			"两臂仅声明项不同，可比。"
			if not reasons
			else "两臂差异超出声明范围或声明项未生效：不构成可比实验，已拒绝。"
		),
	}


# --------------------------------------------------------------------------
# 采集段（每段都独立可缺项：缺项如实标注，不用默认值冒充）
# --------------------------------------------------------------------------


def code_section(*, repo_root: str | None = None) -> dict[str, Any]:
	"""实际运行版本：commit + 工作树状态（行号只是附加信息，不作主键）。"""
	return dict(store.code_version(repo_root=repo_root))


def runtime_section(*, cwd: str, profile: Any = None) -> dict[str, Any]:
	"""runtime profile 身份；解析失败时如实标 unavailable。"""
	try:
		from engine.runtime_profile import resolve_runtime_profile

		resolved = resolve_runtime_profile(profile, runtime=None)
		out = dict(resolved.to_dict())
		out["cwd_basename"] = Path(cwd or ".").name
		return out
	except Exception as exc:  # noqa: BLE001 — 采集失败必须可见，不能编一个档案
		return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}


def tool_schema_section(registry: Any = None) -> dict[str, Any]:
	"""工具 schema 身份：只取指纹与名字清单，不复制 schema 正文。"""
	if registry is None:
		return {"status": "not_provided"}
	snapshot = getattr(registry, "schema_snapshot", None)
	if callable(snapshot):
		try:
			return dict(snapshot())
		except Exception as exc:  # noqa: BLE001
			return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
	schemas = getattr(registry, "schemas", None)
	if callable(schemas):
		try:
			rows = list(schemas())
		except Exception as exc:  # noqa: BLE001
			return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
		return {
			"hash": digest(rows),
			"count": len(rows),
			"tool_names": sorted(_s(r.get("name")) for r in rows if isinstance(r, Mapping)),
		}
	return {"status": "unsupported", "error": "no_schema_surface"}


def permission_section(*, cwd: str) -> dict[str, Any]:
	"""权限配置身份：模式 + preset + 工作区策略的规范化 hash（不写策略正文）。"""
	out: dict[str, Any] = {}
	try:
		from permissions.policy import agent_mode, permission_mode, session_permission_profile

		out["agent_mode"] = agent_mode()
		out["permission_mode"] = permission_mode()
		out["permission_profile"] = session_permission_profile()
	except Exception as exc:  # noqa: BLE001
		out["status"] = "partial"
		out["error"] = f"{type(exc).__name__}: {exc}"
	try:
		from permissions.workspace_policy import load_workspace_policy

		policy = load_workspace_policy(cwd)
		out["workspace_policy"] = digest(
			{
				"allowed_roots": list(policy.allowed_roots),
				"bash": policy.bash,
				"write": policy.write,
				"deny_tools": list(policy.deny_tools),
				"deny_commands": list(policy.deny_commands),
				"remote_bash": policy.remote_bash,
				"bash_routing": policy.bash_routing,
				"exists": bool(policy.exists),
			}
		)
	except Exception as exc:  # noqa: BLE001
		out["workspace_policy"] = "unavailable"
		out.setdefault("error", f"{type(exc).__name__}: {exc}")
	return out


def file_inventory(
	root: str | Path,
	*,
	cap: int = 5000,
	exclude_dirs: Iterable[str] = (),
) -> dict[str, Any]:
	"""工作区文件清单（路径 + 字节 + 内容 hash）。

	排除目录是**声明过**的排除，不是静默丢失：两臂比的是同一套规则下的清单。
	"""
	base = Path(root)
	skip = set(_INVENTORY_EXCLUDE_DIRS) | {_s(d) for d in exclude_dirs}
	entries: list[dict[str, Any]] = []
	truncated = False
	skipped_dirs = 0
	if not base.is_dir():
		return {"entries": [], "count": 0, "truncated": False, "excluded_dirs": sorted(skip)}
	for path in sorted(base.rglob("*")):
		if any(part in skip for part in path.relative_to(base).parts[:-1]):
			continue
		if path.is_dir():
			if _s(path.name) in skip:
				skipped_dirs += 1
			continue
		if len(entries) >= cap:
			truncated = True
			break
		try:
			data = path.read_bytes()
		except OSError:
			entries.append(
				{"path": path.relative_to(base).as_posix(), "bytes": -1, "sha256": "read_failed"}
			)
			continue
		entries.append(
			{
				"path": path.relative_to(base).as_posix(),
				"bytes": len(data),
				"sha256": hashlib.sha256(data).hexdigest()[:32],
			}
		)
	return {
		"entries": entries,
		"count": len(entries),
		"truncated": truncated,
		"skipped_dirs": skipped_dirs,
		"excluded_dirs": sorted(skip),
	}


def inventory_digest(inventory: Mapping[str, Any]) -> str:
	"""清单指纹：路径与内容一起进 hash，多一个文件或少一个文件都不会撞。"""
	return digest(
		[
			[_s(e.get("path")), int(e.get("bytes") or 0), _s(e.get("sha256"))]
			for e in (inventory.get("entries") or [])
		]
	)


def _git_porcelain(root: Path, extra: list[str]) -> list[str] | None:
	"""git status 路径清单；非 git 仓库/超时返回 None（调用方如实标注不可得）。"""
	try:
		creation = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
		out = subprocess.run(  # noqa: S603 — 固定参数，无用户输入
			["git", "-C", str(root), "status", "--porcelain", *extra],
			capture_output=True,
			timeout=5.0,
			encoding="utf-8",
			errors="replace",
			creationflags=creation,
		)
	except Exception:  # noqa: BLE001
		return None
	if out.returncode != 0:
		return None
	paths: list[str] = []
	for line in out.stdout.splitlines():
		body = line[3:] if len(line) > 3 else ""
		body = body.split(" -> ")[-1].strip().strip('"')
		if body:
			paths.append(body.replace("\\", "/"))
		elif "->" in line:
			paths.append(line.split("->")[-1].strip().strip('"').replace("\\", "/"))
	return sorted(set(paths))


def workspace_section(
	root: str | Path,
	*,
	snapshot_commit: str = "",
	ignored_supplied: Iterable[str] = (),
	inventory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	"""工作区状态：快照引用 + 未跟踪清单 + **明确未纳入**的 ignored 文件。

	§8：ignored 数据未显式补入的任务不具备 A2 条件，所以这里必须把"没带上的
	ignored 文件"逐项列出来，而不是只报一个总数。
	"""
	base = Path(root)
	supplied = {_s(p).replace("\\", "/") for p in ignored_supplied if _s(p)}
	out: dict[str, Any] = {
		"root_basename": base.name,
		"snapshot_commit": _s(snapshot_commit),
		"probed_at": round(time.time(), 3),
	}
	untracked = _git_porcelain(base, ["--untracked-files=all"])
	ignored = _git_porcelain(base, ["--untracked-files=all", "--ignored=matching"])
	out["is_git_repo"] = untracked is not None
	out["untracked"] = untracked or []
	if ignored is None:
		out["ignored"] = []
		out["ignored_status"] = "unknown"
	else:
		tracked_set = {p.lstrip("./") for p in (untracked or [])}
		out["ignored"] = sorted({p for p in ignored if p not in tracked_set})
		out["ignored_not_included"] = sorted(p for p in out["ignored"] if p not in supplied)
		out["ignored_supplied"] = sorted(supplied & set(out["ignored"]))
	inv = dict(inventory) if inventory is not None else file_inventory(base)
	out["inventory_digest"] = inventory_digest(inv)
	out["file_count"] = int(inv.get("count") or 0)
	out["inventory_truncated"] = bool(inv.get("truncated"))
	out["excluded_dirs"] = list(inv.get("excluded_dirs") or [])
	return out


def history_section(
	*,
	messages: Iterable[Mapping[str, Any]] = (),
	system: str = "",
	blocks: Mapping[str, str] | None = None,
	block_order: Iterable[str] | None = None,
	checkpoint: str = "",
	captures: Iterable[str] = (),
	source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	"""原始历史与内容版本：逐条 blob hash + 提示词块内容版本 + 捕获引用。

	只有 hash 的历史不能补造正文，所以这里同时记录 ``body_captured`` 状态。
	"""
	rows = [dict(m) for m in messages]
	order = [name for name in (block_order or (blocks or {})) ]
	return {
		"message_count": len(rows),
		"blobs": [digest(m) for m in rows],
		"history_digest": digest(rows),
		"system_digest": digest(system) if system else "",
		"prompt_content_versions": {name: digest(_s((blocks or {}).get(name))) for name in order},
		"block_order": list(order),
		"checkpoint": _s(checkpoint),
		"final_request_captures": [_s(c) for c in captures if _s(c)],
		"body_captured": bool(messages and system),
		"source": dict(source or {}),
	}


def model_section(
	*,
	provider: str,
	model: str,
	params: Mapping[str, Any] | None = None,
	seed_supported: bool | None = None,
	ts: float | None = None,
) -> dict[str, Any]:
	"""模型身份：完整名称、provider、有效参数、seed 是否受支持。

	同参数同 seed 不承诺云模型逐字确定，因此这里只记事实，不记"应当可复现"。
	"""
	return {
		"provider": _s(provider),
		"model": _s(model),
		"params": dict(params or {}),
		"params_digest": digest(dict(params or {})),
		"seed_supported": seed_supported,
		"exact_replay_claimed": False,
		"captured_at": round(ts if ts is not None else time.time(), 3),
	}


def verifier_section(
	*,
	name: str,
	command: str = "",
	success_condition: str = "",
	allowed_commands: Iterable[str] = (),
	termination: str = "",
	retention: str = "",
	version: str = "",
) -> dict[str, Any]:
	"""验收器与判定口径：模型说"通过"不等于通过，成功条件必须是可执行判据。"""
	return {
		"name": _s(name),
		"command": _s(command),
		"success_condition": _s(success_condition),
		"allowed_commands": [_s(c) for c in allowed_commands if _s(c)],
		"termination_condition": _s(termination),
		"evidence_retention": _s(retention) or "run_default",
		"verifier_version": _s(version) or digest({"name": _s(name), "command": _s(command)}),
	}


def price_from_pricing(*, provider: str, model: str, ts: float | None = None) -> dict[str, Any]:
	"""从产品价目链取单价（元/百万 token）；取不到就标 unknown，绝不按 0 记。

	DeepSeek 按本地表（不联网）；其它厂商走 estimate_cny 同源估算档。
	"""
	from usage.pricing import unit_prices_cny_per_mtoken

	probed_ts = time.time() if ts is None else float(ts)
	try:
		hit, miss, out, write = unit_prices_cny_per_mtoken(
			provider=_s(provider), model=_s(model), ts=probed_ts
		)
	except Exception as exc:  # noqa: BLE001 — 价格不可得必须由账本拒绝，不能当 0
		return {
			"status": "unknown",
			"error": f"{type(exc).__name__}: {exc}",
			"currency": "CNY",
			"price_version": "",
		}
	rates = {"hit": float(hit), "miss": float(miss), "out": float(out)}
	if write:
		rates["write"] = float(write)
	return {
		"status": "ok",
		"currency": "CNY",
		"rates": rates,
		"tier": "peak" if _is_peak(provider, probed_ts, model) else "offpeak",
		"probed_at": round(probed_ts, 3),
		"source": "usage/pricing.py:unit_prices_cny_per_mtoken",
		"price_version": digest(
			{"provider": _s(provider), "model": _s(model), "rates": rates, "ts_hour": int(probed_ts // 3600)}
		),
	}


def _is_peak(provider: str, ts: float, model: str) -> bool:
	try:
		from usage.pricing import time_tier

		return time_tier(_s(provider), ts, _s(model)) == "peak"
	except Exception:  # noqa: BLE001
		return False


def budget_section(
	*,
	price: Mapping[str, Any] | None = None,
	cap_cny: float | None = None,
	max_requests: int | None = None,
	max_retries: int | None = None,
	max_output_tokens: int | None = None,
	max_turns: int | None = None,
	max_wall_sec: float | None = None,
	billing_class: str = "unknown",
) -> dict[str, Any]:
	"""保守预算：统一上限（两臂/重试/repeat 共用一个）、最坏输入上界与硬停止线。"""
	cap: float | None
	try:
		cap = None if cap_cny is None else float(cap_cny)
	except (TypeError, ValueError):
		cap = None
	return {
		"price": dict(price or {}),
		"price_status": _s((price or {}).get("status")) or "unknown",
		"price_version": _s((price or {}).get("price_version")),
		"currency": _s((price or {}).get("currency")) or "unknown",
		"cap_cny": cap,
		"cap_scope": "experiment_total",
		"max_requests": max_requests,
		"max_retries": max_retries,
		"max_output_tokens": max_output_tokens,
		"max_turns": max_turns,
		"max_wall_sec": max_wall_sec,
		"billing_class": _s(billing_class) or "unknown",
		"basis": "按 usage 估算（非账单实付）",
	}


# --------------------------------------------------------------------------
# 组装 / 落盘
# --------------------------------------------------------------------------


def arm_manifest(context: Mapping[str, Any], variant: Mapping[str, Any]) -> dict[str, Any]:
	"""一条臂的完整可比面：共享上下文（去易变）+ 该臂变体。"""
	shared: dict[str, Any] = {}
	for name in CONTEXT_SECTIONS:
		if name in EXCLUDED_CONTEXT_SECTIONS:
			continue
		section = context.get(name)
		if isinstance(section, Mapping):
			shared[name] = {
				k: v for k, v in section.items() if _s(k) not in VOLATILE_KEYS
			}
		elif section is not None:
			shared[name] = section
	return {"context": shared, "variant": dict(variant or {})}


def build_manifest(
	*,
	experiment_id: str,
	mode: str,
	task_id: str,
	pair_id: str,
	repeat: int,
	context: Mapping[str, Any],
	variants: Mapping[str, Mapping[str, Any]],
	allowed_differences: Iterable[str] = (),
	note: str = "",
) -> dict[str, Any]:
	"""组装 manifest 并跑单变量判定；判定结果原样入档（证明"当时确实只有一处不同"）。"""
	mode = _s(mode)
	if mode not in MODES:
		raise ManifestError(f"unknown_mode: {mode or '(empty)'}")
	arms = {arm: arm_manifest(context, variants.get(arm) or {}) for arm in ARMS}
	comparability = compare_arms(arms, allowed_differences=allowed_differences)
	ts = time.time()
	return {
		"schema_version": SCHEMA_VERSION,
		"experiment_id": _s(experiment_id),
		"mode": mode,
		"task_id": _s(task_id),
		"pair_id": _s(pair_id),
		"repeat": int(repeat),
		"generated_at": round(ts, 3),
		"allowed_differences": [_s(p) for p in allowed_differences if _s(p)],
		"context": {k: dict(v) if isinstance(v, Mapping) else v for k, v in context.items()},
		"arms": arms,
		"comparability": comparability,
		"note": _s(note),
		"marker_policy": "实验身份不进入任何模型可见文本",
	}


def experiment_dir(experiment_id: str) -> Path:
	return store.experiments_dir() / _s(experiment_id)


def manifest_path(experiment_id: str) -> Path:
	return experiment_dir(experiment_id) / "manifest.json"


def write_manifest(manifest: Mapping[str, Any], *, directory: Path | None = None) -> Path:
	"""写一次；重复写不同内容即失败（manifest 不可变是配对可信的前提）。"""
	path = (directory or experiment_dir(_s(manifest.get("experiment_id")))) / "manifest.json"
	if not path.parent.name:
		raise ManifestError("missing_experiment_id")
	if path.is_file():
		previous = store.read_json(path)
		if previous is None:
			raise ManifestError(f"manifest_unreadable: {path}")
		if previous != dict(manifest):
			raise ManifestImmutableError(f"manifest_immutable: {path}")
		return path
	store.write_json(path, dict(manifest))
	return path


def load_manifest(experiment_id: str) -> dict[str, Any] | None:
	return store.read_json(manifest_path(experiment_id))


def require_comparable(manifest: Mapping[str, Any]) -> dict[str, Any]:
	"""闸门：不可比就抛 ``SingleVariableViolation``，调用方不得发任何请求。"""
	comparability = manifest.get("comparability") or {}
	if not comparability.get("ok"):
		raise SingleVariableViolation(dict(comparability))
	return dict(comparability)


__all__ = [
	"ARMS",
	"CONTEXT_SECTIONS",
	"MODES",
	"ManifestError",
	"ManifestImmutableError",
	"SCHEMA_VERSION",
	"SingleVariableViolation",
	"arm_manifest",
	"budget_section",
	"build_manifest",
	"code_section",
	"compare_arms",
	"digest",
	"experiment_dir",
	"file_inventory",
	"flatten",
	"history_section",
	"inventory_digest",
	"load_manifest",
	"manifest_path",
	"model_section",
	"permission_section",
	"price_from_pricing",
	"require_comparable",
	"runtime_section",
	"tool_schema_section",
	"verifier_section",
	"workspace_section",
	"write_manifest",
]
