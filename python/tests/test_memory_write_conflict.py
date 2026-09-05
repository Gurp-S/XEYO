"""MemoryWrite 冲突处理回归：不同主题共存、同主题替换且替换链正确。

曾触发：写一条 user 笔记会把同 scope 的 feedback 笔记 supersede 掉
（冲突键只看 scope/applies_to），导致"记住的事实"从索引/搜索静默消失。
"""

from __future__ import annotations

from engine.abort import AbortController
from memory.memdir import load_index_text, load_notes, workspace_id
from memory.search import search
from tools.memory_tool import MemoryTool


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / "usage"))
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "home" / "memory"))
    proj = tmp_path / "proj"
    proj.mkdir()
    from session.cwd import set_cwd

    set_cwd(str(proj), set_as_original=True)
    return proj


async def test_write_different_topic_coexists_and_searchable(tmp_path, monkeypatch):
    proj = _env(tmp_path, monkeypatch)
    w = MemoryTool(cwd=str(proj))
    abort = AbortController()

    r1 = await w.execute(
        {"action": "write", "type": "feedback", "content": "测试必须打真库", "title": "真实DB",
         "source_kind": "user", "confidence": 1.0},
        abort,
    )
    assert not r1.is_error
    r2 = await w.execute(
        {"action": "write", "type": "user", "content": "评测偏好用中文", "title": "语言偏好",
         "source_kind": "user", "confidence": 1.0},
        abort,
    )
    assert not r2.is_error

    wsid = workspace_id(str(proj))
    active = [n for n in load_notes(wsid) if n.status == "active"]
    assert len(active) == 2  # 不同主题共存，不再互相吞掉

    hits = search("真库", cwd=str(proj), scope="workspace")
    # 检索命中标题为 真实DB 的 feedback 笔记
    assert hits and "真实DB" in hits[0].title and hits[0].type == "feedback"

    idx = load_index_text(wsid)
    assert "真实DB" in idx
    assert "语言偏好" in idx


async def test_write_same_topic_supersedes_with_chain(tmp_path, monkeypatch):
    proj = _env(tmp_path, monkeypatch)
    w = MemoryTool(cwd=str(proj))
    abort = AbortController()

    r1 = await w.execute(
        {"action": "write", "type": "feedback", "content": "测试必须打真库", "title": "真实DB",
         "source_kind": "user", "confidence": 1.0},
        abort,
    )
    assert not r1.is_error
    wsid = workspace_id(str(proj))
    first = [n for n in load_notes(wsid) if n.status == "active"][0]

    r2 = await w.execute(
        {"action": "write", "type": "feedback", "content": "测试必须打真库（更新）", "title": "真实DB",
         "source_kind": "user", "confidence": 1.0},
        abort,
    )
    assert not r2.is_error

    notes = load_notes(wsid)
    active = [n for n in notes if n.status == "active"]
    assert len(active) == 1
    new_note = active[0]
    # 新笔记记录替换链，指向被替换的旧笔记
    assert new_note.supersedes == first.id
    # 任何被标 superseded 的笔记不得自引用
    for n in notes:
        if n.status == "superseded":
            assert n.supersedes != n.id
    # 索引仍指向新笔记
    assert "真实DB" in load_index_text(wsid)
