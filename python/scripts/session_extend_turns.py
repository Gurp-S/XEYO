# ruff: noqa: T201
"""把真实会话 JSONL 按 user 轮次循环扩展，用于 A1 超长 live 命中率评测。

用法:
  python scripts/session_extend_turns.py --turns 200
  python scripts/session_extend_turns.py --turns 200 --source ~/.xenyon/sessions/sess_msy1p5ev_up68xw.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from memory.simulator.replay import _is_user_text, load_jsonl

DEFAULT_SOURCE_CANDIDATES = (
	Path.home() / ".xeyo" / "sessions" / "sess_msy1p5ev_up68xw.jsonl",
	Path.home() / ".xenyon" / "sessions" / "sess_msy1p5ev_up68xw.jsonl",
)
DEFAULT_OUT = Path.home() / ".xeyo" / "sessions" / "sess_real_200turn_c2.jsonl"


def resolve_source(explicit: str | None) -> Path:
	if explicit:
		p = Path(explicit).expanduser()
		if not p.is_file():
			raise FileNotFoundError(f"source not found: {p}")
		return p
	env = os.environ.get("XEYO_REAL_SESSION", "").strip()
	if env:
		p = Path(env).expanduser()
		if p.is_file():
			return p
	for p in DEFAULT_SOURCE_CANDIDATES:
		if p.is_file():
			return p
	raise FileNotFoundError(
		"no real session JSONL; set --source or XEYO_REAL_SESSION "
		f"(tried {[str(p) for p in DEFAULT_SOURCE_CANDIDATES]})"
	)


def _user_turn_slices(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
	"""按 user 文本轮切分（与 replay._user_turn_indices 一致）。"""
	starts: list[int] = []
	for i, row in enumerate(rows):
		role = str(row.get("role") or "")
		content = row.get("content")
		msg = {"role": role, "content": content}
		if _is_user_text(msg):
			starts.append(i)
	if not starts:
		return [rows] if rows else []
	slices: list[list[dict[str, Any]]] = []
	for t, start in enumerate(starts):
		end = starts[t + 1] if t + 1 < len(starts) else len(rows)
		slices.append(rows[start:end])
	return slices


def _remap_turn(turn_rows: list[dict[str, Any]], *, cycle: int, turn_idx: int) -> list[dict[str, Any]]:
	"""深拷贝一轮并重写 id / tool_use_id，避免循环拼接后引用冲突。"""
	prefix = f"c{cycle:03d}t{turn_idx:02d}"
	id_map: dict[str, str] = {}

	def map_id(old: str) -> str:
		old = (old or "").strip()
		if not old:
			return old
		if old not in id_map:
			id_map[old] = f"{prefix}_{old}"[:120]
		return id_map[old]

	def walk_content(content: Any) -> Any:
		if isinstance(content, str):
			return content
		if not isinstance(content, list):
			return content
		out_blocks: list[Any] = []
		for block in content:
			if not isinstance(block, dict):
				out_blocks.append(block)
				continue
			b = copy.deepcopy(block)
			bt = b.get("type")
			if bt == "tool_use" and b.get("id"):
				b["id"] = map_id(str(b["id"]))
			elif bt == "tool_result" and b.get("tool_use_id"):
				b["tool_use_id"] = map_id(str(b["tool_use_id"]))
			out_blocks.append(b)
		return out_blocks

	out: list[dict[str, Any]] = []
	for row in turn_rows:
		r = copy.deepcopy(row)
		if r.get("id"):
			r["id"] = f"{prefix}_{uuid.uuid4().hex[:16]}"
		if r.get("tool_call_id"):
			r["tool_call_id"] = map_id(str(r["tool_call_id"]))
		r["content"] = walk_content(r.get("content"))
		out.append(r)
	return out


def extend_session_rows(
	rows: list[dict[str, Any]],
	*,
	target_user_turns: int,
) -> list[dict[str, Any]]:
	"""循环真实 user 轮直到达到 target_user_turns。"""
	if target_user_turns < 1:
		raise ValueError("target_user_turns must be >= 1")
	turns = _user_turn_slices(rows)
	if not turns:
		raise ValueError("empty session")
	out: list[dict[str, Any]] = []
	user_count = 0
	cycle = 0
	while user_count < target_user_turns:
		for turn_idx, turn_rows in enumerate(turns):
			out.extend(_remap_turn(turn_rows, cycle=cycle, turn_idx=turn_idx))
			user_count += 1
			if user_count >= target_user_turns:
				break
		cycle += 1
	return out


def rows_to_api(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	api: list[dict[str, Any]] = []
	for row in rows:
		if not isinstance(row, dict) or not row.get("role"):
			continue
		msg: dict[str, Any] = {"role": row["role"], "content": row.get("content")}
		if row.get("name"):
			msg["name"] = row["name"]
		if row.get("tool_call_id"):
			msg["tool_call_id"] = row["tool_call_id"]
		api.append(msg)
	return api


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as fh:
		for row in rows:
			fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_extended_session(
	*,
	source: Path | None = None,
	target_user_turns: int = 200,
	out_path: Path | None = None,
) -> Path:
	src = source or resolve_source(None)
	rows = load_jsonl(src)
	extended = extend_session_rows(rows, target_user_turns=target_user_turns)
	dest = out_path or DEFAULT_OUT
	write_jsonl(dest, extended)
	base_turns = len(_user_turn_slices(rows))
	api = rows_to_api(extended)
	from memory.simulator.replay import _user_turn_indices

	print(f"source: {src}")
	print(f"base user turns: {base_turns}, messages: {len(rows)}")
	print(f"extended user turns: {len(_user_turn_indices(api))}, messages: {len(extended)}")
	print(f"wrote: {dest}")
	return dest


def main() -> int:
	ap = argparse.ArgumentParser(description="Extend real session JSONL to N user turns (cycle + remap ids)")
	ap.add_argument("--turns", type=int, default=200, help="target user turns (default 200)")
	ap.add_argument("--source", default="", help="source JSONL (default: XEYO_REAL_SESSION or ~/.xeyo|xenyon/.../sess_msy1...)")
	ap.add_argument("--out", default="", help=f"output JSONL (default {DEFAULT_OUT})")
	args = ap.parse_args()
	try:
		src = resolve_source(args.source or None) if args.source else resolve_source(None)
		out = Path(args.out).expanduser() if args.out else DEFAULT_OUT
		build_extended_session(source=src, target_user_turns=args.turns, out_path=out)
	except (FileNotFoundError, ValueError) as exc:
		print(f"ERROR: {exc}")
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
