"""P0：Memory index 块一行化 + 围栏 + 去条件化的契约回归。

背景：整份索引尾插在用户文本后、贴近生成点，弱模型（glm-4.5-air 实测）
会把条目当成任务对象（「帮我修改」被绑定到记忆条目上）。P0 冻结契约：
1. 块体只含一行计数摘要，条目标题 / 路径不进投影；
2. 摘要数据包在 ``<memory_index readonly>`` 围栏内（房风同 prompt/fence.py）；
3. 免责指令无条件 + 锚定用户消息字样，不再要求模型判断「用户是否在问记忆」；
4. 无条目时整块省略（空工作区不再发空头块）；
5. 块头保留 ``# Memory index`` 前缀（query_loop._content_parts 统计依赖）；
6. 块体尺寸有界（200 条索引也不得膨胀）。
"""

from memory.runtime import (
	_memory_index_block,
	_memory_index_digest,
	memory_index_context_block,
)

_INDEX_FULL = (
	"# Memory index\n"
	"[feedback] 代理收割证据的置信度封顶为 0.6 → topics/feedback-a.md\n"
	"[feedback] NightShift 是记忆整理机制，负责候选晋升 → topics/feedback-b.md\n"
	"[user] Memory Test Note → topics/user-a.md\n"
	"[project] 工具测试记录 → topics/project-a.md\n"
	"[reference] 调试优先查看audit.jsonl → topics/reference-a.md\n"
)


def test_digest_counts_by_type_desc():
	digest = _memory_index_digest(_INDEX_FULL)
	assert digest.startswith("Memory index: 5 entries")
	assert "feedback 2" in digest
	assert "user 1" in digest
	assert "project 1" in digest
	assert "reference 1" in digest
	# 检索出路必须给出（push 转 pull 的引子）
	assert "Memory(action=search)" in digest


def test_digest_never_leaks_entry_titles_or_paths():
	digest = _memory_index_digest(_INDEX_FULL)
	# 条目标题 / topics 路径是本次事故的劫持面，一律不进摘要
	assert "代理收割" not in digest
	assert "NightShift" not in digest
	assert "Memory Test Note" not in digest
	assert "topics/" not in digest


def test_digest_empty_and_header_only():
	assert _memory_index_digest("") == ""
	assert _memory_index_digest(None) == ""
	assert _memory_index_digest("# Memory index\n") == ""
	# 无法识别类型的行归入 other，不丢计数
	assert "other 1" in _memory_index_digest("没有方括号的散行\n")


def test_block_shape_fenced_and_pure_info():
	block = _memory_index_block(_INDEX_FULL)
	lines = block.splitlines()
	assert lines[0].startswith("# Memory index (background only")
	assert '<memory_index readonly="true">' in block
	assert "</memory_index>" in block
	assert "Memory index: 5 entries" in block
	# 铁律 5（2026-09-09 裁决维持下线）：正文不再含行为指令/条件式措辞，
	# 来源由块头 + readonly 围栏承担。
	for marker in ("禁止", "除非", "忽略", "仅当", "否则"):
		assert marker not in block, f"Memory index 块含行为指令: {marker}"
	assert "不是用户请求" not in block
	assert "记忆 / memory" not in block
	# 正文止于摘要行：除围栏标签外无额外说明
	assert block.rstrip().endswith("</memory_index>")


def test_block_omitted_without_entries():
	# 无条目（空工作区 / 仅头行）→ 整块省略，不发空头块
	assert _memory_index_block("# Memory index\n") == ""
	assert _memory_index_block("") == ""
	assert _memory_index_block(None) == ""


def test_block_size_bounded_even_for_big_index():
	many = "# Memory index\n" + "".join(
		f"[feedback] 标题{i} 很长的描述内容还带中文 → topics/feedback-{i}.md\n"
		for i in range(200)
	)
	block = _memory_index_block(many)
	assert "200 entries" in block
	assert len(block) < 500


def test_context_block_uses_digest(monkeypatch):
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: _INDEX_FULL)
	monkeypatch.setattr("memory.memdir.workspace_id", lambda p: "ws")
	monkeypatch.setattr("engine.workspace_context.get_cwd", lambda: "/ws")
	block = memory_index_context_block()
	assert block.startswith("# Memory index")
	assert "entries" in block
	assert "代理收割" not in block
	assert "topics/" not in block


def test_context_block_swallows_errors(monkeypatch):
	# load_index_text 自身只吞 OSError；RuntimeError 穿透后由
	# memory_index_context_block 的兜底 except 吞掉 → 空块，不炸调用链
	def _boom(wsid):
		raise RuntimeError("unexpected")

	monkeypatch.setattr("memory.memdir.load_index_text", _boom)
	assert memory_index_context_block() == ""
