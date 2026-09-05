"""codeindex.graph：文件 import 图与架构折叠。"""

from __future__ import annotations

from pathlib import Path

from codeindex.graph import build_workspace_graph, infer_layer, package_id


def test_infer_layer_and_package() -> None:
	assert infer_layer("gui/src/components/ChatPage.tsx") == "ui"
	assert infer_layer("python/server/routers/chat.py") == "api"
	assert infer_layer("python/engine/query_loop.py") == "engine"
	assert infer_layer("python/tools/grep_tool/grep_tool.py") == "tools"
	assert infer_layer("python/tests/test_codeindex.py") == "test"
	assert package_id("gui/src/stores/chatStore.ts") == "gui/src/stores"
	assert package_id("python/engine/query_loop.py") == "python/engine"


def test_python_import_edge(tmp_path: Path) -> None:
	engine = tmp_path / "python" / "engine"
	engine.mkdir(parents=True)
	(engine / "query_loop.py").write_text("def run():\n\treturn 1\n", encoding="utf-8")
	(engine / "compact.py").write_text(
		"from engine.query_loop import run\n\ndef x():\n\treturn run()\n",
		encoding="utf-8",
	)
	graph = build_workspace_graph(str(tmp_path))
	ids = {n["id"] for n in graph["files"]}
	assert "python/engine/query_loop.py" in ids
	assert "python/engine/compact.py" in ids
	assert any(
		e["from"] == "python/engine/compact.py" and e["to"] == "python/engine/query_loop.py"
		for e in graph["fileEdges"]
	)
	pkg_ids = {p["id"] for p in graph["packages"]}
	assert "python/engine" in pkg_ids


def test_ts_alias_and_relative(tmp_path: Path) -> None:
	src = tmp_path / "gui" / "src"
	stores = src / "stores"
	pages = src / "pages"
	stores.mkdir(parents=True)
	pages.mkdir(parents=True)
	(stores / "chatStore.ts").write_text("export const useChatStore = {}\n", encoding="utf-8")
	(pages / "ChatPage.tsx").write_text(
		'import {useChatStore} from "@/stores/chatStore";\nexport function ChatPage() { return useChatStore; }\n',
		encoding="utf-8",
	)
	(stores / "other.ts").write_text(
		'import {useChatStore} from "./chatStore";\nexport const x = useChatStore;\n',
		encoding="utf-8",
	)
	graph = build_workspace_graph(str(tmp_path))
	edges = {(e["from"], e["to"]) for e in graph["fileEdges"]}
	assert ("gui/src/pages/ChatPage.tsx", "gui/src/stores/chatStore.ts") in edges
	assert ("gui/src/stores/other.ts", "gui/src/stores/chatStore.ts") in edges
	pkg_edges = {(e["from"], e["to"]) for e in graph["packageEdges"]}
	assert ("gui/src/pages", "gui/src/stores") in pkg_edges
	ui = [p for p in graph["packages"] if p["id"] == "gui/src/pages"]
	assert ui and ui[0]["layer"] == "ui"


def test_skips_node_modules_and_external(tmp_path: Path) -> None:
	src = tmp_path / "gui" / "src" / "lib"
	src.mkdir(parents=True)
	nm = tmp_path / "gui" / "node_modules" / "react"
	nm.mkdir(parents=True)
	(nm / "index.js").write_text("export default 1;\n", encoding="utf-8")
	(src / "utils.ts").write_text(
		'import React from "react";\nexport const cn = () => React;\n',
		encoding="utf-8",
	)
	graph = build_workspace_graph(str(tmp_path))
	ids = {n["id"] for n in graph["files"]}
	assert "gui/src/lib/utils.ts" in ids
	assert not any("node_modules" in i for i in ids)
	assert graph["fileEdges"] == []


def test_graph_cache_hit_and_refresh(tmp_path: Path) -> None:
	from codeindex.graph import clear_graph_cache

	clear_graph_cache()
	pkg = tmp_path / "python" / "engine"
	pkg.mkdir(parents=True)
	(pkg / "a.py").write_text("def a():\n\treturn 1\n", encoding="utf-8")
	g1 = build_workspace_graph(str(tmp_path))
	(pkg / "b.py").write_text("def b():\n\treturn 2\n", encoding="utf-8")
	g2 = build_workspace_graph(str(tmp_path))  # cache hit — still without b
	ids2 = {n["id"] for n in g2["files"]}
	assert "python/engine/b.py" not in ids2
	assert g1 is g2 or g1["fileCount"] == g2["fileCount"]
	g3 = build_workspace_graph(str(tmp_path), refresh=True)
	ids3 = {n["id"] for n in g3["files"]}
	assert "python/engine/b.py" in ids3
	clear_graph_cache()
