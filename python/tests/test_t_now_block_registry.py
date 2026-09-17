"""T_now 硬准入执法（问题#2 修复）：登记表 ↔ 装配点标记双向核对。

规矩（AGENTS.md「工程硬规矩」+ pre_llm_inject 硬准入节）：
- run_pre_llm_inject 每个 `tagged.append` 装配点必须带 `# block: <名>` 标记；
- <名> 必须在 T_NOW_BLOCK_REGISTRY 登记（klass 合法、why 非空）；
- 登记数硬顶 T_NOW_BLOCK_HARD_CAP（=存量：加一必须删一或显式调高上限）；
- 登记表不得腐烂：每个登记名必须能在源码里找到对应装配点。

新块准入流程：装配点加标记 → 登记表加行（klass/why）→ 若超硬顶，先删旧块
或给出预算不破的理由调高上限。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.pre_llm_inject import (
	PIPE_EVENT,
	PIPE_STATE,
	T_NOW_BLOCK_HARD_CAP,
	T_NOW_BLOCK_REGISTRY,
)

_SRC = (
	Path(__file__).resolve().parents[1] / "prompt" / "pre_llm_inject.py"
).read_text(encoding="utf-8")

_CALL_RE = re.compile(r'_tag_block\(\s*tagged,\s*"([A-Za-z0-9_]+)"')

#: ``_tag_block`` 助手本体的唯一 append 形态（唯一入口的机器凭证）
_ALLOWED_APPEND = "\ttagged.append((name, body))"


def _marked_names() -> list[str]:
	"""全文扫描：装配点统一走 `_tag_block(tagged, "名", 正文)`（允许跨行）——
	登记名是真实代码参数（比注释强，改名即测试红）。裸 `tagged.append(`
	在本文件禁止。"""
	assert "tagged.append(" not in _SRC.replace(
		_ALLOWED_APPEND, "", 1
	), "装配点必须走 _tag_block（仅 _tag_block 助手本体允许 append）"
	return _CALL_RE.findall(_SRC)


def test_hard_cap_not_exceeded():
	assert len(T_NOW_BLOCK_REGISTRY) <= T_NOW_BLOCK_HARD_CAP, (
		"块登记数超硬顶：加一必须删一，或给出预算不破的理由显式调高 "
		"T_NOW_BLOCK_HARD_CAP"
	)


def test_every_append_site_is_marked_and_registered():
	marked = _marked_names()
	# 无遗漏 / 无未登记名 / 无重复标记
	unregistered = set(marked) - set(T_NOW_BLOCK_REGISTRY)
	assert not unregistered, f"装配点未登记：{sorted(unregistered)}"
	dupes = {n for n in marked if marked.count(n) > 1}
	assert not dupes, f"标记重复：{sorted(dupes)}"


def test_registry_has_no_dead_entries():
	marked = set(_marked_names())
	dead = set(T_NOW_BLOCK_REGISTRY) - marked
	assert not dead, f"登记表存在无装配点的死条目：{sorted(dead)}"


def test_registry_entries_are_complete():
	for name, meta in T_NOW_BLOCK_REGISTRY.items():
		assert meta.get("pipe") in {PIPE_STATE, PIPE_EVENT}, (
			f"{name}.pipe 非法：{meta.get('pipe')!r}"
		)
		assert isinstance(meta.get("quota"), bool), f"{name}.quota 必须是布尔"
		assert isinstance(meta.get("dedup"), bool), f"{name}.dedup 必须是布尔"
		if meta.get("pipe") == PIPE_EVENT:
			# 管道 3 = drain 语义：去重会把"第二次发生"读成"没发生"，
			# 配额裁剪会静默丢事件。两条都不许碰。
			assert meta.get("dedup") is False, f"{name} 是事件块，不得声明去重"
			assert meta.get("quota") is False, f"{name} 是事件块，不得受配额裁剪"
		why = (meta.get("why") or "").strip()
		assert len(why) >= 8, f"{name} 的 why 必须回答「为什么必须在上下文」"
		# 答不出 why 的高危句式：空话/绕过话术
		assert not why.startswith(("待定", "TODO", "应该", "可能")), (
			f"{name} 的 why 是空话：{why!r}"
		)


def test_legacy_taxonomy_removed():
	"""旧类目不得复活：装配点只剩登记名，类目单一来源 = 登记表。"""
	assert "KLASS_" not in _SRC, "旧 KLASS_* 类目已被 pipe/quota/dedup 取代"
	assert "T_NOW_INVENTORY_MAX" not in _SRC, "旧 inventory 预算常量已更名"
	assert "_is_vague_referent_turn" not in _SRC.replace(
		"# ``_VAGUE_CODE_MARKERS`` / ``_is_vague_referent_turn`` 及装配口那一道",
		"",
		1,
	), "D1 弱模型特化（模糊指代轮门控）不得复活"
