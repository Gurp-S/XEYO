"""P2-2 任务级 rollout 归档：会话结束写一份、保留最新 N 份、喂 L4 检索带引用锚点。"""

from __future__ import annotations

import os
import time

from memory.memdir import workspace_id
from memory.search import search_rollout_summaries
from memory.session_md import archive_session_rollout, path_for, rollout_dir


def _env(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / ".xeyo"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / ".xeyo" / "memory"))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	root = tmp_path / "proj"
	root.mkdir()
	return root


def _write_session_md(sid: str, body: str) -> None:
	path = path_for(sid)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(body, encoding="utf-8")


def test_archive_writes_rollout_summary(tmp_path, monkeypatch):
	root = _env(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	_write_session_md("sess_one", "# Session\n## Goal\n跑通 P2-2 归档测试\n## Current state\n进行中\n")
	archived = archive_session_rollout("sess_one", wsid=wsid)
	assert archived is not None
	text = archived.read_text(encoding="utf-8")
	assert "session_id: sess_one" in text
	assert "archived_at:" in text
	assert "# Session" in text
	assert "跑通 P2-2 归档测试" in text


def test_archive_no_session_md_returns_none(tmp_path, monkeypatch):
	root = _env(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	assert archive_session_rollout("never-existed", wsid=wsid) is None


def test_archive_prunes_oldest(tmp_path, monkeypatch):
	root = _env(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	for i in range(4):
		_write_session_md(f"sess_{i}", f"# Session\n## Goal\n任务 {i}\n")
		archive_session_rollout(f"sess_{i}", wsid=wsid, max_keep=2)
		# 拉开 mtime：最后归档的三个按 0.1s/份递增留出可判定顺序
		d = rollout_dir(wsid)
		files = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime)
		if files:
			old = time.time() - (len(files) + 1)
			os.utime(files[0], (old, old))
	files = sorted(rollout_dir(wsid).glob("*.md"))
	assert len(files) <= 2
	# 最新的 sess_3 一定保留
	assert any("sess_3" in f.read_text(encoding="utf-8") for f in files)


def test_search_rollout_summaries_finds_and_cites(tmp_path, monkeypatch):
	root = _env(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	_write_session_md(
		"sess_cite", "# Session\n## Goal\n记住本仓库用 pnpm 装依赖\n## Completed\ndone\n"
	)
	archive_session_rollout("sess_cite", wsid=wsid)
	hits = search_rollout_summaries("pnpm", wsid=wsid)
	assert hits and hits[0].session_id == "sess_cite"
	assert "pnpm" in hits[0].excerpt
	cite = hits[0].citation
	assert "<citation_entries>" in cite
	assert "rollout_summaries/" in cite
	assert "sess_cite" in cite
	assert "|note=[" in cite


def test_search_rollout_summaries_empty(tmp_path, monkeypatch):
	root = _env(tmp_path, monkeypatch)
	wsid = workspace_id(str(root))
	assert search_rollout_summaries("不存在的词xyzzy", wsid=wsid) == []
