"""G58: DeepSeekModelClient 必须走用量账本(防账本黑洞);调用点存在性由 grep 型断言锁定。"""

from __future__ import annotations

import importlib

import pytest


def _source() -> str:
    return importlib.import_module("model.deepseek").__loader__.get_source(
        "model.deepseek"
    ) or ""


def test_deepseek_client_has_ledger_call_sites() -> None:
    src = _source()
    # 三个请求路径(httpx 流/stdlib 流/非流)都要有记账触发,且存在记账助手
    assert "def _record_usage_safe" in src
    assert "record_from_openai_usage" in src
    assert src.count("self._record_usage_safe(") >= 3


@pytest.mark.asyncio
async def test_record_usage_safe_writes_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    from model.deepseek import DeepSeekModelClient

    captured: dict = {}

    def fake_record(*, provider, model, api_key, usage, session_id):
        captured.update(
            provider=provider, model=model, api_key=api_key,
            usage=usage, session_id=session_id,
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-ds")
    monkeypatch.setattr(
        "usage.ledger.record_from_openai_usage", fake_record
    )
    client = DeepSeekModelClient(model="deepseek-chat")
    client.set_session_id("sess-1")
    client._record_usage_safe({"prompt_tokens": 5, "completion_tokens": 7})
    assert captured["provider"] == "deepseek"
    assert captured["model"] == "deepseek-chat"
    assert captured["session_id"] == "sess-1"
    assert captured["usage"]["prompt_tokens"] == 5


@pytest.mark.asyncio
async def test_record_usage_safe_noop_on_empty() -> None:
    from model.deepseek import DeepSeekModelClient

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-ds")

    class _NoopLedger:
        def __init__(self):
            self.called = False

    box = _NoopLedger()

    def fake_record(**kwargs):
        box.called = True

    monkeypatch.setattr("usage.ledger.record_from_openai_usage", fake_record)
    client = DeepSeekModelClient(model="m")
    client._record_usage_safe(None)
    assert not box.called
