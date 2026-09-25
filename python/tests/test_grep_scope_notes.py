"""Grep 的空结果要说清"这一趟没扫什么"，而且说的话必须是真的。

"No matches found" 被模型读成"整个仓库没有这个串"，而 rg 只扫它愿意扫的面：
被 ignore 文件挡掉的路径、XEYO 排除的构建/版本目录、凭据文件。范围不写出来，
缺失的证据就会被当成不存在的证据。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.grep_tool.grep_tool import GrepTool

_ABSENT = "zzz_no_such_literal_anywhere"
_SCOPE_CLAIM = "Not searched by this pass"


@pytest.fixture
def work(tmp_path: Path) -> Path:
	(tmp_path / "keep.py").write_text("VISIBLE_MARKER = 1\n", encoding="utf-8")
	return tmp_path


@pytest.mark.asyncio
@pytest.mark.parametrize(
	"mode", ["files_with_matches", "content", "count"], ids=["files", "content", "count"]
)
async def test_empty_result_states_the_unsearched_surface(
	work: Path, mode: str
) -> None:
	r = await GrepTool(cwd=str(work)).execute(
		{"pattern": _ABSENT, "output_mode": mode, "path": "."},
		AbortController(),
	)
	assert not r.is_error, r.content
	assert _SCOPE_CLAIM in r.content, r.content


@pytest.mark.asyncio
async def test_hits_do_not_drag_the_scope_note_in(work: Path) -> None:
	"""有命中时不加免责句——否则每次命中都在交税。"""
	r = await GrepTool(cwd=str(work)).execute(
		{"pattern": "VISIBLE_MARKER", "path": "."},
		AbortController(),
	)
	assert "keep.py" in r.content
	assert _SCOPE_CLAIM not in r.content, r.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
	("rel", "marker", "ignore_rule"),
	[
		("ignored/shadowed.py", "HIDDEN_BY_IGNORE_MARKER", "ignored/\n"),
		("node_modules/dep.js", "HIDDEN_BY_DEP_DIR_MARKER", ""),
		("creds/.env", "HIDDEN_BY_CRED_MARKER", ""),
	],
	ids=["ignore-file", "dependency-dir", "credential-file"],
)
async def test_every_claim_in_the_note_is_true(
	work: Path, rel: str, marker: str, ignore_rule: str
) -> None:
	"""注脚声称不扫的面，必须真的扫不到——否则免责句本身成了新的错话。

	（.gitignore 只在 git 工作树里生效：实测非 git 目录下 rg 仍会扫，所以措辞里
	限定成 "inside a git working tree"，这里也只断言无条件的三条。）
	"""
	if ignore_rule:
		(work / ".ignore").write_text(ignore_rule, encoding="utf-8")
	f = work / rel
	f.parent.mkdir(parents=True, exist_ok=True)
	f.write_text(f"{marker} = 1\n", encoding="utf-8")
	assert f.is_file()

	tool = GrepTool(cwd=str(work))
	r = await tool.execute({"pattern": marker, "path": "."}, AbortController())
	assert "No files found" in r.content, r.content
	assert _SCOPE_CLAIM in r.content
	# 同一次调用面里必须仍能看见没被排除的文件，否则"扫不到"可能只是整条链路坏了。
	control = await tool.execute(
		{"pattern": "VISIBLE_MARKER", "path": "."}, AbortController()
	)
	assert "keep.py" in control.content, control.content
