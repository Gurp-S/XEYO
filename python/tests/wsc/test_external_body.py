"""外置正文回填契约（2026-09-20 事故回归）。

事故形态：transcript 里 >32KB 的 tool content 落 ``{stem}.blobs/<id>.json``，行里只剩
``content_ref`` + ``content_hash`` + ``content_bytes``。加载层不回填时，这一行

  - 没有正文（信息审计里是个空节点）；
  - `_as_api_message` 旧实现把它变成 ``{"role":"user","content":None}`` ⇒ **连配对信号
    也没有**，保尾边界只能按条数兜底（可落在调用与结果之间 ⇒ 尾部以孤立 tool_result
    开头 ⇒ 调用方整体回退）。

26-task 语料实测：这类行 9 条（gcode-to-text 3 / train-fasttext 2 / sanitize-git-repo 4）。

契约：① 有 blob 且 hash 相符 → 回填正文且配对可见；② blob 缺失 / hash 不符 →
保持 ``content=None``（不编造），但配对信号仍然保住；③ inline 行不受影响。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engine.compact import tool_pair_ranges
from synaptic.replay import _as_api_message, hydrate_external_rows, load_jsonl
from synaptic.textutil import tool_result_blocks

_ROUNDS = 3


def _rows() -> list[dict]:
	rows: list[dict] = [{"role": "user", "content": "跑一下"}]
	for i in range(_ROUNDS):
		uid = f"call_{i}"
		rows.append({"role": "assistant", "content": [
			{"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": "ls"}},
		]})
		rows.append({
			"id": f"msg_{i}",
			"role": "tool",
			"tool_call_id": uid,
			"name": "Bash",
			"ts": 1.0 + i,
		})
	return rows


def _externalize(rows: list[dict], blob_dir: Path, *, corrupt: bool = False) -> list[dict]:
	"""把 ``role=tool`` 行改成外置形态，并写下 blob（corrupt=True 时写坏 hash）。"""
	blob_dir.mkdir(parents=True, exist_ok=True)
	out: list[dict] = []
	for row in rows:
		if row.get("role") != "tool":
			out.append(row)
			continue
		content = f"step {row['tool_call_id']} output\n" * 4
		payload = json.dumps(content, ensure_ascii=False).encode("utf-8")
		blob_dir.joinpath(f"{row['id']}.json").write_bytes(payload)
		digest = hashlib.sha256(payload).hexdigest()
		if corrupt:
			digest = "0" * 64
		out.append({
			**row,
			"content_ref": f"{row['id']}.json",
			"content_hash": f"sha256:{digest}",
			"content_bytes": len(payload),
		})
	return out


def _write(path: Path, rows: list[dict]) -> Path:
	with path.open("w", encoding="utf-8") as fh:
		for r in rows:
			fh.write(json.dumps(r, ensure_ascii=False) + "\n")
	return path


# ---------------------------------------------------------------------------
# ① 有 blob 且 hash 相符 → 回填 + 配对可见
# ---------------------------------------------------------------------------


def test_external_row_is_hydrated_and_pairing_stays_visible(tmp_path: Path):
	path = _write(tmp_path / "s.jsonl", _externalize(_rows(), tmp_path / "s.blobs"))
	rows = load_jsonl(path)
	tools = [r for r in rows if r.get("role") == "tool"]
	assert len(tools) == _ROUNDS
	assert all(isinstance(r.get("content"), str) and r["content"] for r in tools), "正文没有回填"

	api = [_as_api_message(r) for r in rows]
	assert len(tool_pair_ranges(api)) == _ROUNDS
	for i in range(_ROUNDS):
		tool_msg = api[2 * i + 2]
		blocks = tool_result_blocks(tool_msg)
		assert len(blocks) == 1 and blocks[0]["tool_use_id"] == f"call_{i}"


def test_hydration_stats_are_reported(tmp_path: Path):
	path = _write(tmp_path / "s.jsonl", _externalize(_rows(), tmp_path / "s.blobs"))
	raw = load_jsonl(path, hydrate=False)
	assert all(r.get("content") is None for r in raw if r.get("role") == "tool")
	rows, stats = hydrate_external_rows(raw, path)
	assert stats == {"rows": len(raw), "externalized": _ROUNDS, "hydrated": _ROUNDS, "unresolved": 0}


# ---------------------------------------------------------------------------
# ② blob 缺失 / hash 不符 → 不编造，但配对仍在
# ---------------------------------------------------------------------------


def test_missing_blob_is_unresolved_and_not_fabricated(tmp_path: Path):
	path = _write(tmp_path / "s.jsonl", _externalize(_rows(), tmp_path / "missing.blobs"))
	rows, stats = hydrate_external_rows(load_jsonl(path, hydrate=False), path)
	assert stats["externalized"] == _ROUNDS and stats["hydrated"] == 0
	assert stats["unresolved"] == _ROUNDS
	tools = [r for r in rows if r.get("role") == "tool"]
	assert all(r.get("content") is None for r in tools), "拿不到正文时必须保持 None，不许填空串"

	api = [_as_api_message(r) for r in rows]
	assert len(tool_pair_ranges(api)) == _ROUNDS, "配对信号与正文是否拿到无关，必须保住"
	assert tool_result_blocks(api[2])[0]["tool_use_id"] == "call_0"


def test_hash_mismatch_is_not_trusted(tmp_path: Path):
	path = _write(tmp_path / "s.jsonl", _externalize(_rows(), tmp_path / "s.blobs", corrupt=True))
	rows, stats = hydrate_external_rows(load_jsonl(path, hydrate=False), path)
	assert stats["hydrated"] == 0 and stats["unresolved"] == _ROUNDS
	assert all(r.get("content") is None for r in rows if r.get("role") == "tool")


# ---------------------------------------------------------------------------
# ③ inline 行不受影响
# ---------------------------------------------------------------------------


def test_inline_rows_are_untouched(tmp_path: Path):
	rows = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
	path = _write(tmp_path / "s.jsonl", rows)
	out, stats = hydrate_external_rows(load_jsonl(path, hydrate=False), path)
	assert out == rows
	assert stats["externalized"] == 0


def test_hydrate_false_leaves_refs_alone(tmp_path: Path):
	path = _write(tmp_path / "s.jsonl", _externalize(_rows(), tmp_path / "s.blobs"))
	rows = load_jsonl(path, hydrate=False)
	assert any(r.get("content_ref") for r in rows)
	assert all(r.get("content") is None for r in rows if r.get("role") == "tool")
