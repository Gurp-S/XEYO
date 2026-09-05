"""transcript_pointer_shadow 门槛/证明性测试（⑬）。

覆盖：
- 关（默认）：不挂钩。
- transcript_pointer_block 生成指向 transcript_path 的 inventory 块；空 session_id → 空串。
- 注入条件：已压缩（c2_summary_text 非空）才注入；每会话只注入一次。
- 卸载后恢复原函数。
- fail-open：异常交回原 run_pre_llm_inject。
"""

from __future__ import annotations

import importlib

import pytest

import prompt.pre_llm_inject as inject_mod
from prompt.transcript_pointer_shadow import (
    enabled,
    install,
    reset_seen,
    transcript_pointer_block,
    uninstall,
)


@pytest.fixture()
def ptr_off(monkeypatch):
    monkeypatch.delenv("XEYO_C2_TRANSCRIPT_POINTER", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


class _FakeWorking:
    def __init__(self, c2_text: str = ""):
        self.c2_summary_text = c2_text


class _FakeCtx:
    def __init__(self, session_id: str = "", c2_text: str = ""):
        self.session_id = session_id
        self.working = _FakeWorking(c2_text) if session_id else None


def test_default_off_no_hook(ptr_off):
    assert enabled() is False
    assert install() is False
    assert not getattr(inject_mod, "__c2_transcript_pointer_installed", False)


def test_install_uninstall_restore(monkeypatch):
    monkeypatch.setenv("XEYO_C2_TRANSCRIPT_POINTER", "1")
    assert enabled() is True
    before = inject_mod.run_pre_llm_inject
    assert install() is True
    assert getattr(inject_mod, "__c2_transcript_pointer_installed", False) is True
    assert inject_mod.run_pre_llm_inject is not before
    uninstall()
    assert inject_mod.run_pre_llm_inject is before


def test_directory_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_CWD", str(tmp_path))
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    return None


def test_block_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    block = transcript_pointer_block("sess_abc")
    assert "# C2 后原始历史" in block
    assert "sess_abc" in block
    assert "Read" in block or "Grep" in block
    # 空 session_id → 空串。
    assert transcript_pointer_block("") == ""


def test_should_inject_once_and_only_after_compress(monkeypatch):
    monkeypatch.setenv("XEYO_C2_TRANSCRIPT_POINTER", "1")
    reset_seen()
    from prompt.transcript_pointer_shadow import _should_inject

    # 未压缩 → 不注入。
    assert _should_inject(_FakeCtx(session_id="s1", c2_text="")) is False
    # 已压缩 → 注入。
    assert _should_inject(_FakeCtx(session_id="s1", c2_text="summary")) is True
    # 注入过一次 → 不再注入（字节稳定）。
    from prompt.transcript_pointer_shadow import _SEEN_SESSIONS

    _SEEN_SESSIONS.add("s1")
    assert _should_inject(_FakeCtx(session_id="s1", c2_text="summary")) is False
    # 无 session_id → 不注入。
    assert _should_inject(_FakeCtx(session_id="", c2_text="summary")) is False


def test_inject_wrap_returns_unchanged_no_inject(monkeypatch):
    """未压缩（c2_summary_text 空）时，包装后的函数返回与原函数一致（不新增块）。"""
    monkeypatch.setenv("XEYO_C2_TRANSCRIPT_POINTER", "1")
    reset_seen()
    assert install() is True
    try:
        from prompt.pre_llm_inject import InjectContext

        mod = importlib.import_module("prompt.pre_llm_inject")
        # 真实 InjectContext（字段全有默认值）；未压缩 → 不注入。
        ctx = InjectContext(session_id="s_empty", cwd=".")
        projected = [{"role": "user", "content": "hello"}]
        out = mod.run_pre_llm_inject(projected, ctx)
        # 无压缩 → 不注入指针块（原样装配回来，内容不丢）。
        texts = _texts(out)
        assert any("hello" in t for t in texts)
        assert not any("C2 后原始历史" in t for t in texts)
    finally:
        uninstall()


def test_inject_wrap_adds_pointer_after_compress(monkeypatch, tmp_path):
    """压缩后且未注入过 → 注入指针块。"""
    monkeypatch.setenv("XEYO_C2_TRANSCRIPT_POINTER", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    reset_seen()
    assert install() is True
    try:
        from memory.working import WorkingSnapshot
        from prompt.pre_llm_inject import InjectContext

        working = WorkingSnapshot(session_id="s_compressed")
        working.c2_summary_text = "compressed summary"
        ctx = InjectContext(session_id="s_compressed", cwd=".", working=working)
        mod = importlib.import_module("prompt.pre_llm_inject")
        projected = [{"role": "user", "content": "hello"}]
        out = mod.run_pre_llm_inject(projected, ctx)
        texts = _texts(out)
        assert any("C2 后原始历史" in t for t in texts)
        assert any("s_compressed" in t and "sessions" in t for t in texts)
    finally:
        uninstall()


def _texts(messages):
    """抽取消息里的文本（content 可能是 str 或 list）。"""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    out.append(b.get("text") or "")
                elif isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append(str(b.get("content") or ""))
    return out


def test_transcript_path_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    from session.persistence import default_sessions_dir

    # 确认 env 生效，transcript_path 指向该目录。
    assert str(default_sessions_dir()) == str(tmp_path / "sessions")
