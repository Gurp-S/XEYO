"""固定证据与基线：用户标记「这轮结果不对」和 verifier 记录的唯一落点。

固定下来的东西有两类：一是运行标记（含预期结果与引用），二是配额豁免名单
（``pinned_files``）——磁盘清理不得先删掉用户钉住的证据。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from diagnostics import store
from diagnostics.identity import EvidenceRef, _s

KIND_RUN_MARK = "run_mark"
KIND_VERIFIER = "verifier"
KIND_EVIDENCE = "evidence"


def _safe(session_id: str) -> str:
	from session.persistence import safe_session_filename

	return safe_session_filename(_s(session_id) or "session")


def _dir(session_id: str) -> Path:
	return store.pins_dir() / _safe(session_id)


def _pin_id(session_id: str, turn_id: str, kind: str, ts: float) -> str:
	raw = f"{session_id}|{turn_id}|{kind}|{ts:.3f}"
	return "pin_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _write(doc: dict[str, Any]) -> dict[str, Any]:
	store.ensure_dirs()
	path = store.artifact_path(
		_dir(_s(doc.get("session_id"))),
		_s(doc.get("pin_id")),
		suffix=".json",
		label="pin_id",
	)
	store.write_json(path, doc)
	record = dict(doc)
	record["locator"] = str(path)
	return record


def pin_run(
	session_id: str,
	turn_id: str,
	*,
	note: str,
	expected: str = "",
	evidence: list[dict[str, Any]] | None = None,
	pinned_files: list[str] | None = None,
) -> dict[str, Any]:
	"""标记「这一轮结果不对」并固定证据。不触发任何付费实验，也不改任务内容。"""
	ts = time.time()
	doc: dict[str, Any] = {
		"pin_id": _pin_id(_s(session_id), _s(turn_id), KIND_RUN_MARK, ts),
		"kind": KIND_RUN_MARK,
		"session_id": _s(session_id),
		"turn_id": _s(turn_id),
		"created_at": round(ts, 3),
		"note": _s(note),
		"expected": _s(expected),
		"evidence": [e for e in (evidence or []) if isinstance(e, dict)],
		"pinned_files": [str(p) for p in (pinned_files or []) if str(p)],
	}
	return _write(doc)


def record_verifier(
	session_id: str,
	turn_id: str,
	*,
	name: str,
	command: str = "",
	exit_code: int | None = None,
	output_ref: str = "",
	verifier_version: str = "",
	evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""记录一次验收。``exit_code`` 为 None 表示"未运行"，不写 0。"""
	ts = time.time()
	doc: dict[str, Any] = {
		"pin_id": _pin_id(_s(session_id), _s(turn_id), KIND_VERIFIER, ts),
		"kind": KIND_VERIFIER,
		"session_id": _s(session_id),
		"turn_id": _s(turn_id),
		"created_at": round(ts, 3),
		"name": _s(name),
		"command": _s(command),
		"exit_code": exit_code,
		"output_ref": _s(output_ref),
		"verifier_version": _s(verifier_version),
		"evidence": [e for e in (evidence or []) if isinstance(e, dict)],
		"pinned_files": [_s(output_ref)] if output_ref else [],
	}
	return _write(doc)


def pins_for_run(session_id: str, turn_id: str = "") -> list[dict[str, Any]]:
	root = _dir(session_id)
	if not root.is_dir():
		return []
	out: list[dict[str, Any]] = []
	for entry in sorted(root.glob("*.json")):
		doc = store.read_json(entry)
		if not doc:
			continue
		if turn_id and _s(doc.get("turn_id")) and _s(doc.get("turn_id")) != turn_id:
			continue
		doc.setdefault("pin_id", entry.stem)
		doc["locator"] = str(entry)
		out.append(doc)
	out.sort(key=lambda d: float(d.get("created_at") or 0))
	return out


def delete_pin(pin_id: str, session_id: str) -> bool:
	path = store.artifact_path(
		_dir(session_id), _s(pin_id), suffix=".json", label="pin_id"
	)
	if not path.is_file():
		return False
	try:
		path.unlink()
	except OSError:
		return False
	return True


# ---------- 基线（指令漂移与 A0 的参照点） ----------


def set_baseline(name: str, payload: dict[str, Any], *, note: str = "") -> dict[str, Any]:
	store.ensure_dirs()
	ts = time.time()
	items = {
		key: hashlib.sha256(
			json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8", "replace")
		).hexdigest()[:24]
		for key, value in (payload or {}).items()
		if isinstance(key, str)
	}
	doc = {
		"name": _s(name),
		"created_at": round(ts, 3),
		"note": _s(note),
		"hashes": items,
		"counts": {k: len(json.dumps(v, ensure_ascii=False)) for k, v in (payload or {}).items() if isinstance(k, str)},
	}
	path = store.baselines_dir() / f"{_safe(name)}.json"
	store.write_json(path, doc)
	doc["locator"] = str(path)
	return doc


def get_baseline(name: str) -> dict[str, Any] | None:
	return store.read_json(store.baselines_dir() / f"{_safe(name)}.json")


def compare_baseline(name: str, payload: dict[str, Any]) -> dict[str, Any]:
	"""返回 changed / added / removed 三组键；没有基线时如实报 ``no_baseline``。"""
	base = get_baseline(name)
	if not base:
		return {"name": _s(name), "state": "no_baseline", "changed": [], "added": [], "removed": []}
	old = {k: _s(v) for k, v in (base.get("hashes") or {}).items()}
	new = {
		key: hashlib.sha256(
			json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8", "replace")
		).hexdigest()[:24]
		for key, value in (payload or {}).items()
		if isinstance(key, str)
	}
	changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
	return {
		"name": _s(name),
		"state": "drift" if changed or set(old) != set(new) else "same",
		"changed": [
			{"key": k, "before": old[k][:12], "after": new[k][:12]} for k in changed
		],
		"added": sorted(set(new) - set(old)),
		"removed": sorted(set(old) - set(new)),
		"baseline_locator": str(store.baselines_dir() / f"{_safe(name)}.json"),
	}


def evidence_to_dicts(refs: Any) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	for ref in refs or []:
		if isinstance(ref, EvidenceRef):
			out.append(ref.to_dict())
		elif isinstance(ref, dict):
			out.append(ref)
	return out


__all__ = [
	"KIND_EVIDENCE",
	"KIND_RUN_MARK",
	"KIND_VERIFIER",
	"compare_baseline",
	"delete_pin",
	"evidence_to_dicts",
	"get_baseline",
	"pin_run",
	"pins_for_run",
	"record_verifier",
	"set_baseline",
]
