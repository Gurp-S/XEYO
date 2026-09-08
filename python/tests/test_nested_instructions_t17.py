"""T17：项目指令加载器三件套。

- SHA-1 去重：内容相同的嵌套文件只渲染一次（含可见 notice）。
- 预算渲染：装不下整份丢（不拦腰截），仅最具体文件可截断，均带 notice。
- touch 驱动增量：Read **与** Write/Edit 触碰都驱动发现；已加载文件
  更新/移除 → 下一轮 T_now diff 通知（commit 才摘墓碑/刷新哈希）。
"""

from __future__ import annotations


from memory.instruction_maintain import (
	load_nested_instruction_text,
	note_read_path_for_nested,
	reconcile_nested_state,
)
from memory.working import WorkingSnapshot, _from_dict, _to_dict
from prompt.pre_llm_inject import _discover_nested_from_projection


# ---------------------------------------------------------------------------
# SHA-1 去重 + 预算渲染
# ---------------------------------------------------------------------------


def test_dedupe_same_content_different_paths(tmp_path):
	a = tmp_path / "a"
	b = tmp_path / "b"
	a.mkdir()
	b.mkdir()
	p1 = a / "XEYO.md"
	p2 = b / "XEYO.md"
	p1.write_text("同样的规则内容", encoding="utf-8")
	p2.write_text("  同样的规则内容  \n", encoding="utf-8")  # trim 后等价

	out = load_nested_instruction_text([str(p1), str(p2)])
	assert "同样的规则内容" in out
	assert out.count("同样的规则内容") == 1  # 只渲染一次
	assert "内容重复跳过" in out  # notice 提到被跳过的文件


def test_budget_drops_whole_files_and_truncates_most_specific(tmp_path):
	paths: list[str] = []
	# 最具体（第一个）：2KB 宽文件
	wide = tmp_path / "wide.md"
	wide.write_text("W" * 2000, encoding="utf-8")
	paths.append(str(wide))
	# 中间：小文件
	small = tmp_path / "small.md"
	small.write_text("S" * 200, encoding="utf-8")
	paths.append(str(small))
	# 更宽的第三个
	huge = tmp_path / "huge.md"
	huge.write_text("H" * 3000, encoding="utf-8")
	paths.append(str(huge))

	out = load_nested_instruction_text(paths, max_chars=1000)
	# wide 整份未保留；只有「最具体」的 wide 被截断 salvaged（剩余预算填入）
	assert "W" * 2000 not in out
	assert out.count("W") in range(64, 2000)  # 截断片段，非全量
	# 小文件整份保留
	assert "S" * 200 in out
	# huge 更宽且不最具体：整份丢、绝不截断
	assert out.count("H") == 0
	# notice 可见：整份略过 = huge；截断 = wide
	assert "整份略过" in out and "huge.md" in out
	assert "仅截断最具体文件" in out and "wide.md" in out


# ---------------------------------------------------------------------------
# 哈希登记 + 更新/移除墓碑
# ---------------------------------------------------------------------------


def test_note_read_records_hashes(tmp_path):
	pkg = tmp_path / "pkg"
	pkg.mkdir()
	nested = pkg / "XEYO.md"
	nested.write_text("规则 v1", encoding="utf-8")
	snap = WorkingSnapshot(session_id="t")
	new = note_read_path_for_nested(snap, str(pkg / "a.py"), str(tmp_path))
	assert len(new) == 1
	assert snap.nested_hashes and list(snap.nested_hashes.values())[0]
	# 无变更 → 无通知
	# 裁决 5：通知块已删，reconcile 静默维护状态、零文本。
	assert reconcile_nested_state(snap) is None


def test_reconcile_refreshes_hash_silently(tmp_path):
	pkg = tmp_path / "pkg"
	pkg.mkdir()
	nested = pkg / "XEYO.md"
	nested.write_text("规则 v1", encoding="utf-8")
	snap = WorkingSnapshot(session_id="t")
	note_read_path_for_nested(snap, str(pkg / "a.py"), str(tmp_path))

	nested.write_text("规则 v2 —— 新增禁区", encoding="utf-8")
	reconcile_nested_state(snap)  # 哈希静默刷新，无任何模型可见输出
	assert snap.loaded_nested_instruction_paths  # 文件仍在 → loaded 不动


def test_reconcile_tombstone_on_removal(tmp_path):
	pkg = tmp_path / "pkg"
	pkg.mkdir()
	nested = pkg / "XEYO.md"
	nested.write_text("规则 v1", encoding="utf-8")
	snap = WorkingSnapshot(session_id="t")
	note_read_path_for_nested(snap, str(pkg / "a.py"), str(tmp_path))
	loaded = list(snap.loaded_nested_instruction_paths)
	assert loaded

	nested.unlink()
	reconcile_nested_state(snap)
	# 墓碑静默摘除（无通知块）
	assert snap.loaded_nested_instruction_paths == []


def test_snapshot_roundtrip_nested_hashes(tmp_path):
	pkg = tmp_path / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("规则 v1", encoding="utf-8")
	snap = WorkingSnapshot(session_id="t")
	note_read_path_for_nested(snap, str(pkg / "a.py"), str(tmp_path))

	raw = _to_dict(snap)
	assert raw["nested_hashes"]
	restored = _from_dict(raw, "t")
	assert restored.nested_hashes == snap.nested_hashes
	# 旧快照（无该字段）→ 默认空 dict
	old = _from_dict({"session_id": "x"}, "x")
	assert old.nested_hashes == {}


# ---------------------------------------------------------------------------
# Write/Edit touch 驱动发现
# ---------------------------------------------------------------------------


def _write_projection(path):
	return [
		{"role": "user", "content": "task"},
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": "w1",
					"name": "Write",
					"input": {"path": str(path)},
				}
			],
		},
		{
			"role": "tool",
			"name": "Write",
			"tool_call_id": "w1",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": "w1",
					"content": "ok",
					"is_error": False,
				}
			],
		},
	]


def test_write_touch_discovers_nested(tmp_path):
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	nested = pkg / "XEYO.md"
	nested.write_text("写路径也能发现我", encoding="utf-8")
	target = pkg / "code.py"
	target.write_text("x=1\n", encoding="utf-8")

	snap = WorkingSnapshot(session_id="t")
	new = _discover_nested_from_projection(
		_write_projection(target), snap, str(root)
	)
	assert any(p.endswith("XEYO.md") for p in new)
	assert snap.nested_hashes


def test_edit_touch_discovers_nested(tmp_path):
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("edit 也能发现", encoding="utf-8")
	target = pkg / "code.py"

	projected = [
		{"role": "user", "content": "task"},
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": "e1",
					"name": "Edit",
					"input": {"file_path": str(target)},
				}
			],
		},
		{
			"role": "tool",
			"name": "Edit",
			"tool_call_id": "e1",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": "e1",
					"content": "ok",
					"is_error": False,
				}
			],
		},
	]
	snap = WorkingSnapshot(session_id="t")
	new = _discover_nested_from_projection(projected, snap, str(root))
	assert any(p.endswith("XEYO.md") for p in new)


def test_failed_write_does_not_discover(tmp_path):
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("不应发现", encoding="utf-8")
	target = pkg / "code.py"
	projected = _write_projection(target)
	# 置为错误结果
	projected[2]["content"][0]["is_error"] = True
	snap = WorkingSnapshot(session_id="t")
	new = _discover_nested_from_projection(projected, snap, str(root))
	assert new == []
