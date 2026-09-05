"""Memory write_policy + multilingual search smoke tests."""

from __future__ import annotations

import asyncio

from engine.abort import AbortController
from memory.search import search
from memory.write_policy import refuse_reason
from tools.memory_tool import MemoryTool


def test_refuse_directory_tree_and_temp_plan():
	assert refuse_reason(content="本仓库用 pytest") is None
	assert refuse_reason(title="目录树", content="见附件") is not None
	tree = "\n".join(
		[
			"project/",
			"├── src/",
			"│   └── main.py",
			"├── tests/",
			"│   └── test_a.py",
			"└── README.md",
		]
	)
	assert refuse_reason(content=tree) is not None
	assert refuse_reason(content="把今天的临时计划存起来：买菜、洗碗") is not None


def test_memory_tool_write_refuses_tree(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	tool = MemoryTool(cwd=str(root))
	tree = "\n".join(
		[
			"gui/",
			"├── src/",
			"│   └── App.tsx",
			"├── package.json",
			"└── vite.config.ts",
			"python/",
			"└── memory/",
		]
	)
	out = asyncio.run(
		tool.execute(
			{
				"action": "write",
				"type": "project",
				"title": "当前目录树",
				"content": tree,
				"source_kind": "user",
			},
			AbortController(),
		)
	)
	assert out.is_error
	assert "refused" in (out.content or "").lower()


def test_search_fullwidth_normalize(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	root = tmp_path / "proj"
	root.mkdir()
	tool = MemoryTool(cwd=str(root))
	asyncio.run(
		tool.execute(
			{
				"action": "write",
				"type": "project",
				"title": "包管理",
				"content": "前端用 pnpm，测试用 pytest",
				"source_kind": "user",
			},
			AbortController(),
		)
	)
	# 全角 ｐｙｔｅｓｔ → NFKC 后可命中
	hits = search("ｐｙｔｅｓｔ", cwd=str(root), touch=False)
	assert hits and "pytest" in hits[0].content
