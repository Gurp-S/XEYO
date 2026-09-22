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


def test_in_service_dated_vendor_names_are_registered() -> None:
    """带日期后缀的在服型号必须被前缀表接住，否则白拿 128k 兜底 ⇒ 提前开始压上下文。

    事故形状（2026-09-22 取证）：账本里跑了 2,662 枪的 `deepseek-v4.1-flash-expires-on-0910`
    实测 prompt 到过 693,894，却因为表里没有 `deepseek-v4.1-` 而按 128k 算 ⇒ 压力门在
    ~105k 就开始取舍上下文。
    """
    from engine.query_engine import KNOWN_CONTEXT_WINDOWS, _known_context_window

    assert _known_context_window("deepseek-v4.1-flash-expires-on-0910") == 1_000_000
    # 表自身不许出现"更长前缀被更短前缀挡在外面"的形状
    for prefix, window in KNOWN_CONTEXT_WINDOWS:
        assert _known_context_window(prefix) == window, f"{prefix} 被别的前缀抢走"
        assert window > CONSERVATIVE_CONTEXT_WINDOW, (
            f"{prefix} 登记的窗口比兜底还小 ⇒ 登记反而让引擎更早做取舍")


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
