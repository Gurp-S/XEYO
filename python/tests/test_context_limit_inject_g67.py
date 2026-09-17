"""G67: build_default_engine 为缺失 context_limit 的客户端注入**真实**窗口。

2026-09-16 修正：原实现对 deepseek 一律硬编码 65536，比 V4.1-Flash 的真实窗口
小 16 倍，导致压力门在 ~52k 就开始对上下文做取舍（TB 单题实测 peak 73-78k）。
现在按型号查表，未登记型号落 128k 保守兜底。
"""

from __future__ import annotations

from engine.query_engine import (
    CONSERVATIVE_CONTEXT_WINDOW,
    _default_context_limit,
)


def test_default_limits_table() -> None:
    # 已知型号 → 真实窗口（1M）
    assert _default_context_limit("deepseek", "deepseek-flash") == 1_000_000
    assert _default_context_limit("deepseek", "deepseek-v4-flash") == 1_000_000
    # 未登记 deepseek 型号 → 保守兜底（不再 65536）
    assert _default_context_limit("deepseek", "deepseek-未来型号") == (
        CONSERVATIVE_CONTEXT_WINDOW
    )
    assert _default_context_limit("openai", "gpt-4o") == 128_000
    assert _default_context_limit("openai", "gpt-4o-mini") == 128_000
    assert _default_context_limit("openai", "unknown-model-x") is None
    assert _default_context_limit("fake", "fake") is None


def test_deepseek_window_is_not_64k_anymore() -> None:
    """回归守卫：65536 是已确认的缺陷值，不得回来。"""
    for model in ("deepseek-flash", "deepseek-v4-flash", "deepseek-unknown"):
        got = _default_context_limit("deepseek", model)
        assert got is not None and got > 65_536


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
    assert eng._model.context_limit and eng._model.context_limit > 65_536
