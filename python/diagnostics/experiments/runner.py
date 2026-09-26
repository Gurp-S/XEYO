"""实验 runner：manifest → 分派 A0/A1/A2 → results.jsonl → report.md。

三条不可让的口径：
  1. ``idempotency_key`` 先认领再执行——同一个键只会跑一次，重连不重复发请求。
  2. 无效运行也入档、也占预算；不因某臂失败就从账上抹掉。
  3. 报告按维度分别呈现（任务/变更/行为/上下文/性能/费用），不出加权总分；
     小样本标"探索性"，"无显著差异"不得写成等价。
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from diagnostics import store
from diagnostics.identity import _s, request_key
from diagnostics.experiments import a0 as a0_mod
from diagnostics.experiments import a1 as a1_mod
from diagnostics.experiments import a2 as a2_mod
from diagnostics.experiments import manifest as mf
from diagnostics.experiments.reservation import Ledger

MODES = mf.MODES
#: 配对样本少于此数只能算探索性读数（不足以支撑确认性结论）。
EXPLORATORY_PAIRS = 30
NO_SIGNIFICANT_DIFFERENCE = "无显著差异 ≠ 等价：本样本量只说明测不出差异，不证明两臂相同。"
BLENDED_SCORE = "不给加权总分：各维度分别呈现，任一维度的退步不会被别的维度抵掉。"

STATUS_REFUSED = "refused"
STATUS_FAILED = "failed"
STATUS_INCOMPLETE = "incomplete"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"


class RunnerError(RuntimeError):
	"""runner 层的中性错误。"""


def experiment_id_for(idempotency_key: str) -> str:
	clean = _s(idempotency_key)
	if not clean:
		raise RunnerError("missing_idempotency_key")
	return "exp_" + hashlib.sha256(clean.encode("utf-8", "replace")).hexdigest()[:16]


def index_path() -> Path:
	return store.experiments_dir() / "index.json"


def state_path(experiment_id: str) -> Path:
	return mf.experiment_dir(experiment_id) / "state.json"


def results_path(experiment_id: str) -> Path:
	return mf.experiment_dir(experiment_id) / "results.jsonl"


def report_path(experiment_id: str) -> Path:
	return mf.experiment_dir(experiment_id) / "report.md"


def load_index() -> dict[str, Any]:
	return store.read_json(index_path()) or {"schema": 1, "by_key": {}}


def _claim(idempotency_key: str, experiment_id: str) -> dict[str, Any]:
	"""认领幂等键：已被认领就直接返回既有实验，绝不第二次执行。"""
	from coord.locking import FileGuard

	lock = store.experiments_dir() / "locks" / "index.lock"
	lock.parent.mkdir(parents=True, exist_ok=True)
	with FileGuard(lock, ttl=20.0, timeout=10.0) as ok:
		index = load_index()
		by_key = index.setdefault("by_key", {})
		existing = _s(by_key.get(idempotency_key))
		if existing or mf.manifest_path(experiment_id).is_file():
			found = existing or experiment_id
			return {"claimed": False, "experiment_id": found, "reused": True, "locked": bool(ok)}
		if not ok:
			# 拿不到锁又查不到既有记录：无法确认是否已被别处认领，宁可不执行。
			return {"claimed": False, "experiment_id": experiment_id, "reused": False, "locked": False}
		by_key[idempotency_key] = experiment_id
		index["updated_at"] = round(time.time(), 3)
		store.write_json(index_path(), index)
		record = mf.experiment_dir(experiment_id)
		record.mkdir(parents=True, exist_ok=True)
		store.write_json(
			state_path(experiment_id),
			{
				"experiment_id": experiment_id,
				"idempotency_key": idempotency_key,
				"status": "running",
				"started_at": round(time.time(), 3),
			},
		)
		return {"claimed": True, "experiment_id": experiment_id, "reused": False, "locked": True}


def _save_state(experiment_id: str, **fields: Any) -> dict[str, Any]:
	state = store.read_json(state_path(experiment_id)) or {"experiment_id": experiment_id}
	state.update(fields)
	state["updated_at"] = round(time.time(), 3)
	store.write_json(state_path(experiment_id), state)
	return state


def _append_row(experiment_id: str, row: dict[str, Any]) -> None:
	store.append_jsonl(results_path(experiment_id), row)


# --------------------------------------------------------------------------
# 计划与上下文
# --------------------------------------------------------------------------


def plan(
	*,
	mode: str,
	task_id: str = "",
	variants: Mapping[str, Mapping[str, Any]] | None = None,
	checkpoint: a1_mod.Checkpoint | None = None,
	task_spec: Mapping[str, Any] | None = None,
	allowed_differences: Iterable[str] = (),
	budget_cny: float | None = None,
	price: Mapping[str, Any] | None = None,
	limits: Mapping[str, Any] | None = None,
	billable: bool | None = None,
) -> dict[str, Any]:
	"""报价与可行性：不发任何请求，只回答"能跑哪种、缺什么、最多花多少"。"""
	mode = _s(mode)
	if mode not in MODES:
		raise RunnerError(f"unknown_mode: {mode}")
	price_row = dict(price or {})
	billable_flag = (mode != "a0") if billable is None else bool(billable)
	out: dict[str, Any] = {
		"mode": mode,
		"task_id": _s(task_id),
		"billable": billable_flag,
		"allowed_differences": [_s(p) for p in allowed_differences if _s(p)],
		"price": price_row,
		"budget_cny": budget_cny,
		"limits": dict(limits or {}),
		"cost_basis": "按 usage 估算（非账单实付）" if billable_flag else "无模型调用",
	}
	if mode == "a0":
		out["model_requests"] = 0
		out["feasible"] = True
		out["statement"] = "A0 零模型调用、零成本：只产出静态差异与确定性重算。"
	elif mode == "a1":
		arms = {arm: a1_mod.render_arm(a1_mod.apply_variant(checkpoint, (variants or {}).get(arm) or {}))
			for arm in mf.ARMS} if checkpoint is not None else {}
		comparability = mf.compare_arms(arms, allowed_differences=list(allowed_differences) or _auto(arms))
		out["comparability"] = comparability
		out["feasible"] = bool(comparability.get("ok"))
		out["model_requests"] = len(mf.ARMS)
		out["statement"] = (
			"A1 每臂一条请求；工具调用不执行，因此只回答下一步是否变化。"
			if out["feasible"]
			else "A1 不可比：两臂差异超出声明项。"
		)
		out["missing"] = [] if out["feasible"] else [r["code"] for r in comparability.get("reasons") or []]
	else:
		gate = a2_mod.eligibility(dict(task_spec or {}))
		out["eligibility"] = gate
		out["feasible"] = bool(gate.get("ok"))
		out["model_requests"] = None
		out["statement"] = gate["statement"]
		out["missing"] = list(gate.get("missing") or [])
		if billable_flag and budget_cny is None:
			out["feasible"] = False
			out["missing"] = sorted(set(out["missing"]) | {"budget_cap_missing"})
		if billable_flag and _s(price_row.get("status")) != "ok":
			out["feasible"] = False
			out["missing"] = sorted(set(out["missing"]) | {"price_unknown"})
	return out


def _auto(arms: Mapping[str, Mapping[str, Any]]) -> list[str]:
	flat = {arm: mf.flatten(doc) for arm, doc in arms.items()}
	paths = sorted({p for v in flat.values() for p in v})
	import json as _json

	return [
		p
		for p in paths
		if len({_json.dumps(flat[a].get(p), default=str) for a in flat}) > 1
	]


def default_context(
	*,
	mode: str,
	task_id: str,
	checkpoint: a1_mod.Checkpoint | None = None,
	task_spec: Mapping[str, Any] | None = None,
	registry: Any = None,
	price: Mapping[str, Any] | None = None,
	budget_cny: float | None = None,
	limits: Mapping[str, Any] | None = None,
	cwd: str = "",
) -> dict[str, Any]:
	"""§8 要求的共享上下文；缺项如实标注，不用默认值冒充。"""
	spec = dict(task_spec or {})
	workspace_root = _s((spec.get("workspace") or {}).get("root")) or cwd or str(Path.cwd())
	cp = checkpoint
	context: dict[str, Any] = {
		"code": mf.code_section(),
		"runtime": mf.runtime_section(cwd=workspace_root, profile=spec.get("runtime_profile_name")),
		"tools": mf.tool_schema_section(registry if registry is not None else (spec.get("registry") or None)),
		"permissions": mf.permission_section(cwd=workspace_root),
		"workspace": mf.workspace_section(
			workspace_root,
			snapshot_commit=_s(spec.get("snapshot_commit")),
			ignored_supplied=spec.get("supplied_ignored") or [],
		),
		"history": mf.history_section(
			messages=cp.messages if cp else (spec.get("messages") or []),
			system=cp.system_text() if cp else "",
			blocks=cp.blocks if cp else {},
			block_order=cp.block_order if cp else [],
			checkpoint=_s(spec.get("checkpoint")) or (_s(cp.source.get("checkpoint")) if cp and cp.source else ""),
			captures=spec.get("captures") or [],
			source=spec.get("history_source") or (cp.source if cp else {}),
		),
		"model": mf.model_section(
			provider=_s(cp.provider) if cp else _s(spec.get("provider")),
			model=_s(cp.model) if cp else _s(spec.get("model")),
			params=dict(cp.params) if cp else dict(spec.get("params") or {}),
			seed_supported=(spec.get("seed_supported") if "seed_supported" in spec else None),
		),
		"verifier": mf.verifier_section(
			name=_s((spec.get("verifier") or {}).get("name")) or ("none" if mode == "a1" else ""),
			command=_s((spec.get("verifier") or {}).get("command")),
			success_condition=_s((spec.get("verifier") or {}).get("success_condition")),
			allowed_commands=(spec.get("verifier") or {}).get("allowed_commands") or [],
			termination=_s((spec.get("verifier") or {}).get("termination_condition")),
			retention=_s(spec.get("evidence_retention")),
			version=_s((spec.get("verifier") or {}).get("version")),
		),
		"budget": mf.budget_section(
			price=price,
			cap_cny=budget_cny,
			max_requests=(limits or {}).get("max_requests"),
			max_retries=(limits or {}).get("max_retries"),
			max_output_tokens=(limits or {}).get("max_output_tokens"),
			max_turns=(limits or {}).get("max_turns"),
			max_wall_sec=(limits or {}).get("max_wall_sec"),
			billing_class=_s(spec.get("billing_class")),
		),
	}
	return context


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------


def start(
	*,
	idempotency_key: str,
	mode: str,
	task_id: str = "",
	pair_id: str = "p1",
	repeat: int = 0,
	variants: Mapping[str, Mapping[str, Any]] | None = None,
	allowed_differences: Iterable[str] = (),
	checkpoint: a1_mod.Checkpoint | None = None,
	task_spec: Mapping[str, Any] | None = None,
	context: Mapping[str, Any] | None = None,
	price: Mapping[str, Any] | None = None,
	budget_cny: float | None = None,
	limits: Mapping[str, Any] | None = None,
	billable: bool | None = None,
	client: Any = None,
	runner: Any = None,
	registry: Any = None,
	watch: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	"""启动（或复用）一个实验。返回含 ``reused`` 的执行摘要；不重复执行是硬要求。"""
	mode = _s(mode)
	if mode not in MODES:
		raise RunnerError(f"unknown_mode: {mode}")
	store.ensure_dirs()
	key = _s(idempotency_key)
	experiment_id = experiment_id_for(key)
	claim = _claim(key, experiment_id)
	if claim.get("reused"):
		reused_id = _s(claim.get("experiment_id"))
		return {
			"experiment_id": reused_id,
			"reused": True,
			"executed": False,
			"status": _s((store.read_json(state_path(reused_id)) or {}).get("status")),
			"progress": progress(reused_id),
		}
	if not claim.get("claimed"):
		return {
			"experiment_id": experiment_id,
			"reused": False,
			"executed": False,
			"status": STATUS_REFUSED,
			"reason": "index_lock_contended",
		}

	billable_flag = (mode != "a0") if billable is None else bool(billable)
	price_row = dict(price or {})
	budget = None
	if billable_flag:
		budget = Ledger(
			experiment_id,
			cap_cny=budget_cny,
			price=price_row,
			provider=_s((task_spec or {}).get("provider")) or (_s(checkpoint.provider) if checkpoint else ""),
			model=_s((task_spec or {}).get("model")) or (_s(checkpoint.model) if checkpoint else ""),
			max_requests=(limits or {}).get("max_requests"),
		)
		opened = budget.open()
		if not opened.get("allowed"):
			return _finish(
				experiment_id,
				status=STATUS_REFUSED,
				reason=_s(opened.get("reason")),
				manifest_doc=None,
				rows=[],
				extra={"budget": opened},
			)

	built = dict(context or {})
	if not built:
		built = default_context(
			mode=mode,
			task_id=task_id,
			checkpoint=checkpoint,
			task_spec=task_spec,
			registry=registry,
			price=price_row,
			budget_cny=budget_cny,
			limits=limits,
		)
	elif "budget" not in built:
		built["budget"] = mf.budget_section(
			price=price_row,
			cap_cny=budget_cny,
			max_requests=(limits or {}).get("max_requests"),
			max_retries=(limits or {}).get("max_retries"),
			max_output_tokens=(limits or {}).get("max_output_tokens"),
			max_turns=(limits or {}).get("max_turns"),
			max_wall_sec=(limits or {}).get("max_wall_sec"),
			billing_class=_s((task_spec or {}).get("billing_class")),
		)
	doc = mf.build_manifest(
		experiment_id=experiment_id,
		mode=mode,
		task_id=task_id or _s((task_spec or {}).get("task_id")),
		pair_id=_s(pair_id),
		repeat=int(repeat or 0),
		context=built,
		variants=variants or {},
		allowed_differences=list(allowed_differences) or _auto_allowed(mode, checkpoint, variants),
	)
	mf.write_manifest(doc)

	rows: list[dict[str, Any]] = []
	status = STATUS_DONE
	reason = ""
	payload: dict[str, Any] = {}
	try:
		mf.require_comparable(doc)
	except mf.SingleVariableViolation as exc:
		return _finish(
			experiment_id,
			status=STATUS_REFUSED,
			reason="pairing_rejected",
			manifest_doc=doc,
			rows=[],
			extra={"comparability": exc.comparability},
		)
	try:
		if mode == "a0":
			watch_doc = dict(watch or a0_mod.prompt_file_changes())
			payload = a0_mod.run(watch=watch_doc)
			rows.append(
				_row(
					experiment_id,
					mode=mode,
					arm="-",
					pair_id=pair_id,
					repeat=repeat,
					passed=None,
					invalid=False,
					note="静态差异与确定性重算：无臂、无模型调用",
					extra={"changed_count": payload.get("changed_count"), "prompt_watch_changed": (watch_doc or {}).get("changed")},
				)
			)
		elif mode == "a1":
			payload = a1_mod.run_pair(
				checkpoint=checkpoint or a1_mod.Checkpoint(),
				variants=dict(variants or {}),
				client=client,
				allowed_differences=doc["allowed_differences"],
				budget=budget,
				experiment_id=experiment_id,
				request_keys={
					arm: request_key(f"{experiment_id}_{_s(pair_id)}_{arm}", repeat or None)
					for arm in mf.ARMS
				},
				max_output_tokens=(limits or {}).get("max_output_tokens"),
				timeout_sec=(limits or {}).get("max_wall_sec"),
			)
			rows += _arm_rows(experiment_id, mode=mode, result=payload, pair_id=pair_id, repeat=repeat)
		else:
			payload = a2_mod.run_pair(
				task_spec=dict(task_spec or {}),
				experiment_id=experiment_id,
				variants=dict(variants or {}),
				budget=budget,
				runner=runner,
				timeout_sec=(limits or {}).get("max_wall_sec"),
			)
			if payload.get("refused"):
				status = STATUS_REFUSED
				reason = "a2_eligibility_denied"
			rows += _arm_rows(experiment_id, mode=mode, result=payload, pair_id=pair_id, repeat=repeat)
	except mf.SingleVariableViolation as exc:
		status = STATUS_REFUSED
		reason = "pairing_rejected"
		payload = {"comparability": exc.comparability}
	except (a1_mod.A1Error, a2_mod.A2Error, mf.ManifestError) as exc:
		status = STATUS_FAILED
		reason = _s(str(exc))[:200]
	except OSError as exc:
		status = STATUS_FAILED
		reason = f"io_error:{type(exc).__name__}"

	if billable_flag:
		ledger_state = budget.state() if budget is not None else {}
		if ledger_state.get("ledger_unwritable") or ledger_state.get("ledger_write_errors"):
			# 账本写不进去 ⇒ 绝不允许标成功（也无法证明花了多少）。
			status = STATUS_INCOMPLETE
			reason = reason or "ledger_unwritable"
		if any(not (row.get("budget") or {}).get("allowed", True) for row in rows):
			status = STATUS_INCOMPLETE if status == STATUS_DONE else status
			reason = reason or "reservation_denied"
		payload["budget_state"] = ledger_state
	return _finish(
		experiment_id,
		status=status,
		reason=reason,
		manifest_doc=doc,
		rows=rows,
		extra=payload,
	)


def _auto_allowed(mode: str, checkpoint: Any, variants: Mapping[str, Mapping[str, Any]] | None) -> list[str]:
	if mode != "a1" or checkpoint is None:
		return []
	arms = {arm: a1_mod.render_arm(a1_mod.apply_variant(checkpoint, (variants or {}).get(arm) or {})) for arm in mf.ARMS}
	return _auto(arms)


def _row(
	experiment_id: str,
	*,
	mode: str,
	arm: str,
	pair_id: str,
	repeat: int,
	passed: bool | None,
	invalid: bool,
	note: str = "",
	invalid_reason: str = "",
	extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	row: dict[str, Any] = {
		"schema": "diagnostics.experiment_row.v1",
		"experiment_id": experiment_id,
		"mode": mode,
		"arm": arm,
		"pair_id": _s(pair_id) or "p1",
		"repeat": int(repeat or 0),
		"passed": passed,
		"invalid": bool(invalid),
		"at": round(time.time(), 3),
	}
	if note:
		row["note"] = note
	if invalid_reason:
		row["invalid_reason"] = invalid_reason
	row.update({k: v for k, v in dict(extra or {}).items() if v is not None})
	return row


def _arm_rows(
	experiment_id: str,
	*,
	mode: str,
	result: Mapping[str, Any],
	pair_id: str,
	repeat: int,
) -> list[dict[str, Any]]:
	"""逐臂落一行：无效也落行、也计预算（§9 "无效试验也占预算"）。"""
	rows: list[dict[str, Any]] = []
	for arm in mf.ARMS:
		entry = dict((result.get("arms") or {}).get(arm) or {})
		if not entry:
			continue
		response = dict(entry.get("response") or {})
		run = dict(entry.get("run") or {})
		budget_row = dict(entry.get("budget") or {})
		if mode == "a1":
			reply_chars = len(_as_text(response.get("text")))
			tool_calls = len(response.get("tool_calls") or [])
			wall_ms = int(response.get("wall_ms") or 0)
			tokens = response.get("usage")
			usage_seen = bool(response.get("usage_seen"))
			# A1 只回答"下一步输出是否变化"，不判任务成败 ⇒ passed 留空，不写 False。
			passed: bool | None = None
		else:
			reply_chars = int(run.get("reply_chars") or 0)
			tool_calls = int(run.get("tool_calls") or 0)
			wall_ms = int(run.get("wall_ms") or 0)
			tokens = run.get("usage")
			usage_seen = bool(run.get("usage_seen"))
			passed = bool(entry.get("passed")) if entry.get("passed") is not None else None
		invalid = bool(entry.get("invalid")) or not entry.get("sent", True)
		rows.append(
			_row(
				experiment_id,
				mode=mode,
				arm=arm,
				pair_id=pair_id,
				repeat=repeat,
				passed=passed,
				invalid=invalid,
				invalid_reason=_s(entry.get("invalid_reason") or entry.get("error")),
				extra={
					"reply_chars": reply_chars,
					"wall_ms": wall_ms,
					"tool_calls": tool_calls,
					"usage_seen": usage_seen,
					"tokens": tokens,
					"sent": bool(entry.get("sent")),
					"spent_cny": budget_row.get("spent_cny"),
					"reserved_cny": budget_row.get("reserved_cny") or budget_row.get("reserved"),
					"released_cny": budget_row.get("released_cny"),
					"reservation_allowed": bool(budget_row.get("allowed", True)),
					"reservation_reason": _s(budget_row.get("reason")),
					"verifier": entry.get("verifier"),
					"run": run or None,
					"request": entry.get("request"),
					"note": "无效运行：仍计入预算" if invalid else "",
				},
			)
		)
	return rows


def _as_text(value: Any) -> str:
	if value is None:
		return ""
	return value if isinstance(value, str) else str(value)


def _finish(
	experiment_id: str,
	*,
	status: str,
	reason: str,
	manifest_doc: Mapping[str, Any] | None,
	rows: list[dict[str, Any]],
	extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	store.ensure_dirs()
	for row in rows:
		_append_row(experiment_id, row)
	doc = dict(manifest_doc or mf.load_manifest(experiment_id) or {})
	# payload 单独落盘：results.jsonl 保持一行一臂的瘦记录，A1 的两臂正文进这里。
	store.write_json(mf.experiment_dir(experiment_id) / "payload.json", dict(extra or {}))
	report = render_report(experiment_id, manifest=doc, rows=rows, payload=extra or {}, status=status, reason=reason)
	path = report_path(experiment_id)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(report, encoding="utf-8", newline="\n")
	state = _save_state(
		experiment_id,
		status=status,
		reason=reason,
		mode=_s(doc.get("mode")),
		runs=len(rows),
		finished_at=round(time.time(), 3),
	)
	return {
		"experiment_id": experiment_id,
		"reused": False,
		"executed": True,
		"status": status,
		"reason": reason,
		"rows": len(rows),
		"report_locator": str(path),
		"state": state,
		"payload": dict(extra or {}),
	}


# --------------------------------------------------------------------------
# 读取 / 取消
# --------------------------------------------------------------------------


def read_rows(experiment_id: str) -> list[dict[str, Any]]:
	return store.read_jsonl(results_path(experiment_id), limit=0)


def pairing_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
	"""按 (pair_id, repeat) 配对：A-only / B-only / 均通过 / 均失败 / 无效。"""
	out = {"pairs": 0, "a_only_pass": 0, "b_only_pass": 0, "both_pass": 0, "both_fail": 0, "invalid": 0}
	grouped: dict[tuple[str, int], dict[str, Mapping[str, Any]]] = {}
	for row in rows:
		if _s(row.get("arm")) not in mf.ARMS:
			continue
		grouped.setdefault((_s(row.get("pair_id")) or "p1", int(row.get("repeat") or 0)), {})[
			_s(row.get("arm"))
		] = row
	for arms in grouped.values():
		a = arms.get("A")
		b = arms.get("B")
		if a is None or b is None or a.get("invalid") or b.get("invalid"):
			out["invalid"] += 1
			continue
		if a.get("passed") is None or b.get("passed") is None:
			out["invalid"] += 1
			continue
		out["pairs"] += 1
		if a.get("passed") and b.get("passed"):
			out["both_pass"] += 1
		elif a.get("passed"):
			out["a_only_pass"] += 1
		elif b.get("passed"):
			out["b_only_pass"] += 1
		else:
			out["both_fail"] += 1
	return out


def progress(experiment_id: str) -> dict[str, Any]:
	state = store.read_json(state_path(experiment_id)) or {"experiment_id": _s(experiment_id)}
	rows = read_rows(experiment_id)
	ledger = Ledger(_s(experiment_id)).state()
	return {
		"experiment_id": _s(experiment_id),
		"status": _s(state.get("status")),
		"reason": _s(state.get("reason")),
		"mode": _s(state.get("mode")),
		"runs_recorded": len(rows),
		"runs_invalid": sum(1 for r in rows if r.get("invalid")),
		"pairing": pairing_counts(rows),
		"budget": {
			"cap_cny": ledger.get("cap_cny"),
			"committed_cny": ledger.get("committed_cny"),
			"remaining_cny": ledger.get("remaining_cny"),
			"unknown_outcome": list(ledger.get("unknown_outcome") or []),
			"ledger_unwritable": bool(ledger.get("ledger_unwritable")),
			"must_stop": bool(ledger.get("must_stop")),
		},
		"started_at": state.get("started_at"),
		"updated_at": state.get("updated_at"),
	}


def results(experiment_id: str) -> dict[str, Any]:
	"""manifest + 逐臂行 + 分维度汇总 + 预算状态（一次读全，报告口径同源）。"""
	doc = mf.load_manifest(experiment_id) or {}
	rows = read_rows(experiment_id)
	pairing = pairing_counts(rows)
	payload = store.read_json(mf.experiment_dir(experiment_id) / "payload.json") or {}
	dimensions = _dimensions(rows)
	return {
		"experiment_id": _s(experiment_id),
		"mode": _s(doc.get("mode")),
		"status": _s((store.read_json(state_path(experiment_id)) or {}).get("status")),
		"manifest": doc,
		"rows": rows,
		"pairing": pairing,
		"dimensions": dimensions,
		"exploratory": pairing["pairs"] < EXPLORATORY_PAIRS,
		"blended_score": None,
		"blended_score_statement": BLENDED_SCORE,
		"budget": Ledger(_s(experiment_id)).state(),
		"payload": payload,
		"report_locator": str(report_path(experiment_id)),
	}


def cancel(experiment_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
	"""取消：未知结局的请求一律按最大预留保留（可能仍在计费），不释放任何额度。"""
	ident = _s(experiment_id)
	ledger = Ledger(ident)
	state = ledger.state()
	abandoned: list[dict[str, Any]] = []
	for key in list(state.get("unknown_outcome") or []):
		abandoned.append(ledger.abandon(key, reason=_s(reason) or "cancelled"))
	updated = _save_state(
		ident,
		status=STATUS_CANCELLED,
		reason=_s(reason) or "cancelled",
		cancelled_at=round(time.time(), 3),
		kept_reservations=[_s(r.get("request_key")) for r in abandoned],
	)
	return {"experiment_id": ident, "status": STATUS_CANCELLED, "kept_reservations": abandoned, "state": updated}


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------


_DIMENSIONS = ("task", "change", "behaviour", "context", "performance", "cost")


def _dimensions(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
	grouped: dict[str, list[Mapping[str, Any]]] = {}
	for row in rows:
		grouped.setdefault(_s(row.get("arm")) or "-", []).append(row)
	out: dict[str, Any] = {}
	for arm, items in grouped.items():
		latest = items[-1]
		run = dict(latest.get("run") or {})
		verifier = dict(latest.get("verifier") or {})
		out[arm] = {
			"task": {
				"passed": latest.get("passed"),
				"verifier_ran": bool(verifier.get("ran")),
				"exit_code": verifier.get("exit_code"),
				"reason": _s(verifier.get("reason") or latest.get("invalid_reason")),
				"invalid": bool(latest.get("invalid")),
			},
			"change": {
				"files_touched": int(run.get("files_touched") or 0),
				"touched_paths": list(run.get("touched_paths") or [])[:20],
				"needs_review": True,
			},
			"behaviour": {
				"tool_calls": int(run.get("tool_calls") or latest.get("tool_calls") or 0),
				"tool_errors": int(run.get("tool_errors") or 0),
				"model_requests": int(run.get("model_requests") or 0),
				"retries": int(run.get("retries") or 0),
				"turns": int(run.get("turns") or 0),
				"repeated_errors": int(run.get("repeated_errors") or 0),
			},
			"context": {
				"usage_seen": bool(latest.get("usage_seen")),
				"tokens": latest.get("tokens"),
				"request": dict(latest.get("request") or {}),
			},
			"performance": {"wall_ms": int(latest.get("wall_ms") or run.get("wall_ms") or 0)},
			"cost": {
				"spent_cny": latest.get("spent_cny"),
				"reserved_cny": latest.get("reserved_cny"),
				"released_cny": latest.get("released_cny"),
				"basis": "按 usage 估算（非账单实付）",
				"usage_seen": bool(latest.get("usage_seen")),
			},
		}
	return {arm: {dim: out[arm][dim] for dim in _DIMENSIONS} for arm in sorted(out)}


def render_report(
	experiment_id: str,
	*,
	manifest: Mapping[str, Any] | None = None,
	rows: list[dict[str, Any]] | None = None,
	payload: Mapping[str, Any] | None = None,
	status: str = "",
	reason: str = "",
) -> str:
	"""写 ``report.md` 的正文：维度分开列，配对计数原样给，结论边界写在末尾。"""
	doc = dict(manifest or mf.load_manifest(experiment_id) or {})
	all_rows = rows if rows is not None else read_rows(experiment_id)
	pairing = pairing_counts(all_rows)
	mode = _s(doc.get("mode"))
	lines = [f"# XEYO 实验报告（{mode.upper() or '—'}）", ""]
	lines.append(f"- 实验：`{_s(experiment_id)}` · 状态：`{_s(status) or '—'}`" + (f" · 原因：`{_s(reason)}`" if reason else ""))
	lines.append(
		"- 代码版本（写这份产物的进程）：`{}` @ `{}`（工作树 {}）；实验行不带版本，跨构建时不能当成跑实验的引擎版本".format(
			_s((doc.get("context") or {}).get("code", {}).get("commit")),
			_s((doc.get("context") or {}).get("code", {}).get("branch")),
			_s((doc.get("context") or {}).get("code", {}).get("worktree_state")),
		)
	)
	lines.append(f"- 任务：`{_s(doc.get('task_id'))}` · pair `{_s(doc.get('pair_id'))}` · repeat {doc.get('repeat')}")
	lines.append(f"- 允许的唯一变化项：{', '.join(_s(doc.get('allowed_differences')) or []) or '—'}")
	comparability = doc.get("comparability") or (payload or {}).get("comparability") or {}
	lines.append(
		"- 单变量闸门：{}（差异 {} 处：{}）".format(
			"通过" if comparability.get("ok") else "未通过",
			len(comparability.get("differences") or []),
			", ".join(_s(p) for p in (comparability.get("differences") or [])) or "无",
		)
	)
	if not comparability.get("ok"):
		lines.append("  - 判定：" + "；".join(_s(r.get("code")) for r in comparability.get("reasons") or []))
	lines += ["", "## 配对计数", ""]
	for name in ("pairs", "a_only_pass", "b_only_pass", "both_pass", "both_fail", "invalid"):
		lines.append(f"- {name}：{pairing[name]}")
	lines.append(f"- 样本量判定：{'探索性（配对数 < %d）' % EXPLORATORY_PAIRS if pairing['pairs'] < EXPLORATORY_PAIRS else '达到确认性下限'}")
	lines += ["", "## 分维度结果", ""]
	dimensions = _dimensions(all_rows)
	if not dimensions:
		lines.append("无臂运行记录。")
	for arm in sorted(dimensions):
		lines.append(f"### 臂 {arm}")
		lines.append("")
		for dim in _DIMENSIONS:
			values = dimensions[arm][dim]
			lines.append(f"- {dim}：" + "；".join(f"{k}={values[k]}" for k in sorted(values)))
		lines.append("")
	if mode == "a0":
		lines += ["", "## A0 明细", ""]
		lines.append(f"- 变化条目：{(payload or {}).get('changed_count', 0)}")
		for item in (payload or {}).get("mechanical_constraints") or []:
			lines.append(f"- 受影响机械约束：{item.get('constraint')}（相关变化 {item.get('affected_changes')} 处）")
		lines.append(str(_s((payload or {}).get("coverage_gap"))))
	if mode == "a1":
		lines += ["", "## A1 两臂并排", ""]
		lines.append(a1_mod.to_markdown(dict(payload or {})))
	budget = dict((payload or {}).get("budget_state") or Ledger(_s(experiment_id)).state())
	lines += ["", "## 预算与用量口径", ""]
	lines.append(f"- 统一上限（两臂/重试/repeat 共用）：{budget.get('cap_cny')}")
	lines.append(f"- 已入账（含未定结局的保留）：{budget.get('committed_cny')} · 剩余：{budget.get('remaining_cny')}")
	lines.append(f"- 费用依据：按 usage 估算（非账单实付）；价格版本 {_s(budget.get('price_version')) or '—'}")
	unknown = list(budget.get("unknown_outcome") or [])
	lines.append(
		"- 结局未知的请求：%d 个%s（保留最大预留，重启后不自动重发）"
		% (len(unknown), "：" + ", ".join(_s(k) for k in unknown[:10]) if unknown else "")
	)
	lines.append(f"- 账本可写：{not budget.get('ledger_unwritable')}")
	lines += ["", "## 结论边界", ""]
	lines.append(f"- {BLENDED_SCORE}")
	lines.append(f"- {NO_SIGNIFICANT_DIFFERENCE}")
	if mode == "a1":
		lines.append(f"- {_s(a1_mod.CAVEAT)}")
		lines.append(f"- 能回答：{_s((payload or {}).get('answers') or a1_mod.ANSWERS)}")
		lines.append(f"- 不能回答：{_s((payload or {}).get('does_not_answer') or a1_mod.DOES_NOT_ANSWER)}")
	if mode == "a2":
		gate = (payload or {}).get("eligibility") or {}
		lines.append(f"- A2 准入已核验：{gate.get('checked', {}).get('isolation') if gate else '—'}")
		lines.append(f"- 覆盖缺口：{_s((payload or {}).get('coverage_gap'))}")
	if mode == "a0":
		lines.append("- A0 不证明模型表现提高：它没有发过任何模型请求。")
	return "\n".join(lines) + "\n"


__all__ = [
	"EXPLORATORY_PAIRS",
	"MODES",
	"NO_SIGNIFICANT_DIFFERENCE",
	"RunnerError",
	"STATUS_CANCELLED",
	"STATUS_DONE",
	"STATUS_FAILED",
	"STATUS_INCOMPLETE",
	"STATUS_REFUSED",
	"cancel",
	"default_context",
	"experiment_id_for",
	"pairing_counts",
	"plan",
	"progress",
	"read_rows",
	"render_report",
	"report_path",
	"results",
	"results_path",
	"start",
	"state_path",
]
