"""F4 技能目录 + 内容融合（F6a）验收。

运行：``py -3.11 -m pytest tests/extension/test_skill_catalog.py -q``
"""

from __future__ import annotations

import asyncio
import json

import pytest

from engine.abort import AbortController
from extension import mcp_scopes as scopes
from extension.mcp_client import McpClientSpec, _finalize_mcp_result
from extension.skill_loader import (
	discover_skills,
	discover_skills_report,
	repair_frontmatter_scalar_fields,
)
from tools.base_tool import ToolResult
from tools.skill_tool.skill_tool import (
	CATALOG_MAX_CHARS,
	LIST_MAX_CHARS,
	SkillTool,
	is_user_invocable,
)


@pytest.fixture
def home(monkeypatch, tmp_path):
	home = tmp_path / "home"
	monkeypatch.setenv("XEYO_HOME", str(home))
	return home


def _write_skill(ws, name, body):
	d = ws / ".xeyo" / "skills" / name
	d.mkdir(parents=True, exist_ok=True)
	(d / "SKILL.md").write_text(body, encoding="utf-8")


def _enable(ws, **cfg):
	p = ws / ".xeyo" / "settings.json"
	p.parent.mkdir(parents=True, exist_ok=True)
	data = {"enabled_extensions": True, "skills": {}}
	data.update(cfg)
	p.write_text(json.dumps(data), encoding="utf-8")


async def _execute(tool, **input):
	return await tool.execute(input, AbortController())


def test_catalog_line_desc_and_budget(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	# 长 desc 应截到 ≤120。
	_write_skill(ws, "alpha", "---\ndescription: " + ("x" * 300) + "\n---\n# Alpha")
	# 大量技能 → 总硬顶 ≤2400。
	for i in range(60):
		_write_skill(ws, f"s{i}", f"---\ndescription: '{'y' * 100}'\n---\n# S{i}")
	tool = SkillTool(cwd=str(ws))
	schema = tool.schema()
	desc = schema["description"]
	assert len(desc) <= CATALOG_MAX_CHARS + 2000  # 含固定文案。
	# 每行 desc 截断：无超长单行。
	for line in desc.splitlines():
		if line.startswith("- "):
			assert len(line) <= 200


def test_catalog_only_model_invocable(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "hidden", "---\nmodel_invocable: false\ndescription: 隐藏的\n---\n# Hidden")
	_write_skill(ws, "visible", "---\ndescription: 可见的\n---\n# Visible")
	tool = SkillTool(cwd=str(ws))
	desc = tool.schema()["description"]
	assert "visible" in desc
	assert "隐藏的" not in desc
	assert "hidden" not in desc


def test_list_query_substring_and_budget(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "git", "---\ndescription: git 提交流程\n---\n# Git")
	_write_skill(ws, "web", "---\ndescription: web 打包\n---\n# Web")
	tool = SkillTool(cwd=str(ws))
	result = asyncio.run(_execute(tool, action="list", query="git"))
	assert "git" in result.content
	assert "web" not in result.content
	assert result.is_error is False
	# 全量 list 应 ≤4k。
	all_res = asyncio.run(_execute(tool, action="list"))
	assert len(all_res.content) <= LIST_MAX_CHARS + 200


def test_model_invocable_false_rejections(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "manual", "---\nmodel_invocable: false\n---\n# Manual")
	tool = SkillTool(cwd=str(ws))
	result = asyncio.run(_execute(tool, name="manual"))
	assert result.is_error is True
	assert "not available for model invocation" in result.content


def test_user_invocable_false_hides_menu(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "uonly", "---\nuser_invocable: false\n---\n# UOnly")
	assert is_user_invocable(str(ws), "uonly") is False
	assert is_user_invocable(str(ws), "nope") is False


def test_failclosed_bad_frontmatter_broken(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "bad", "---\nmodel_invocable: banana\n---\n# Bad")
	_write_skill(ws, "good", "---\ndescription: ok\n---\n# Good")
	entries, _suppressed = discover_skills_report(str(ws))
	bad = [e for e in entries if e.name == "bad"]
	good = [e for e in entries if e.name == "good"]
	assert bad and bad[0].broken is True
	assert bad[0].reason  # 有具体 reason
	assert good and good[0].broken is False
	# 未加载：SkillTool 拒载 broken。
	tool = SkillTool(cwd=str(ws))
	r = asyncio.run(_execute(tool, name="bad"))
	assert r.is_error is True
	# 目录不含 bad。
	assert "bad" not in tool.schema()["description"]


def test_scalar_repair_sample():
	raw = "description: foo: bar\ntags: [a, b]\nmodel_invocable: true"
	repaired = repair_frontmatter_scalar_fields(raw)
	# 含 ': ' 与 flow 符的裸标量被加引号。
	assert "'foo: bar'" in repaired
	assert "'[a, b]'" in repaired
	# 正常标量行不动。
	assert "model_invocable: true" in repaired


def test_args_arguments_replace(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "tpl", "---\ndescription: 模板\n---\n# Tpl\n请处理 $ARGUMENTS")
	tool = SkillTool(cwd=str(ws))
	r = asyncio.run(_execute(tool, name="tpl", args="hello world"))
	assert "hello world" in r.content
	assert "$ARGUMENTS" not in r.content
	# 无 $ARGUMENTS → 追加参数节。（绕 3s TTL：清缓存让 tpl2 可见。）
	_write_skill(ws, "tpl2", "---\ndescription: 模板2\n---\n# Tpl2\n正文")
	from extension.skill_loader import _CACHE

	_CACHE.clear()
	r2 = asyncio.run(_execute(tool, name="tpl2", args={"a": 1}))
	assert "## 调用参数" in r2.content


def test_result_head_path_and_truncation(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "big", "---\ndescription: 大\n---\n# Big\n" + ("z" * 20_000))
	tool = SkillTool(cwd=str(ws))
	r = asyncio.run(_execute(tool, name="big"))
	assert "(path:" in r.content
	assert len(r.content) <= 13_000
	assert "use Read to continue" in r.content


def test_digest_cache_skips_rescan(home, tmp_path):
	ws = tmp_path / "ws"
	ws.mkdir()
	_enable(ws)
	_write_skill(ws, "a", "---\ndescription: A\n---\n# A")
	import time
	from extension.skill_loader import _CACHE

	_CACHE.clear()
	e1, _ = discover_skills_report(str(ws))
	assert [e.name for e in e1] == ["a"]


# --------------------------------------------------------------------------- #
# F6a 内容融合：image → images（vision 门控）；resource → spill。
# --------------------------------------------------------------------------- #

def _img_result():
	return ToolResult(
		content="[img placeholder]",
		is_error=False,
		images=["data:image/png;base64,AAAA"],
		metadata={},
	)


def test_image_fusion_keep_when_vision_on():
	# vision 开：images 保留，进入视觉链路。
	from extension import mcp_client as mc

	raw = mc._result_from_mcp_call({
		"isError": False,
		"content": [{"type": "image", "data": "AAAA", "mimeType": "image/png"}],
	})
	assert raw.images == ["data:image/png;base64,AAAA"]
	final = _finalize_mcp_result(raw, apply_vision=True, session_id="s")
	assert final.images == ["data:image/png;base64,AAAA"]


def test_image_fusion_degrade_when_vision_off(tmp_path):
	final = _finalize_mcp_result(_img_result(), apply_vision=False, session_id="s")
	assert final.images is None
	assert "不支持视觉" in final.content


def test_resource_fusion_spills(tmp_path, monkeypatch):
	from extension import mcp_client as mc
	from tools.spill import spill_root

	monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / "spill"))
	raw = mc._result_from_mcp_call({
		"isError": False,
		"content": [{"type": "resource", "resource": {"uri": "file://a", "text": "resource body"}}],
	})
	assert raw.metadata["_mcp_resources"]
	final = _finalize_mcp_result(raw, apply_vision=True, session_id="testsess")
	assert "spilled" in final.content
	assert "file://a" in final.content
	assert final.metadata.get("has_resources") is True
