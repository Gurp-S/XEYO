"""G67: build_default_engine 为缺失 context_limit 的客户端注入保守窗口,恢复 C2 触发。"""

from __future__ import annotations

from engine.query_engine import _default_context_limit


def test_default_limits_table() -> None:
    assert _default_context_limit("deepseek", "deepseek-v4-flash") == 65536
    assert _default_context_limit("openai", "gpt-4o") == 128_000
    assert _default_context_limit("openai", "gpt-4o-mini") == 128_000
    assert _default_context_limit("openai", "unknown-model-x") is None
    assert _default_context_limit("fake", "fake") is None


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("XEYO_CONTEXT_LIMIT", "90000")
    assert _default_context_limit("deepseek", "m") == 90000
    assert _default_context_limit("openai", "unknown-x") == 90000
    monkeypatch.setenv("XEYO_CONTEXT_LIMIT", "abc")
    assert _default_context_limit("deepseek", "m") is None


def test_deepseek_client_has_context_limit_attr() -> None:
    from model.deepseek import DeepSeekModelClient

    import inspect

    src = inspect.getsource(DeepSeekModelClient.__init__)
    assert "self.context_limit: int | None = None" in src


def test_build_default_engine_deepseek_sets_context_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-g67")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    from engine.query_engine import build_default_engine

    eng = build_default_engine(cwd=str(tmp_path), model_backend="deepseek")
    assert eng._model.context_limit == 65536
