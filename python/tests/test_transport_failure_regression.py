import httpcore
import httpx
import pytest
from common.errors import classify_llm_failure


@pytest.mark.parametrize('kind', [httpx.ReadError, httpx.WriteError, httpx.CloseError,
    httpx.RemoteProtocolError, httpx.ProxyError, httpcore.ReadError, httpcore.WriteError,
    httpcore.RemoteProtocolError])
def test_transient_transport_errors_are_retryable(kind):
    failure = classify_llm_failure(kind('transport interrupted'))
    assert failure.code == 'network' and failure.retryable


def test_custom_transport_subclass_uses_base_contract():
    class ProviderReadError(httpx.ReadError):
        pass
    assert classify_llm_failure(ProviderReadError('')).retryable
    class ProviderSlow(httpx.ReadTimeout):
        pass
    assert classify_llm_failure(ProviderSlow('')).code == 'timeout'


@pytest.mark.parametrize('kind', [httpx.UnsupportedProtocol, httpx.LocalProtocolError, httpx.TooManyRedirects, ValueError])
def test_configuration_errors_are_not_retried(kind):
    assert not classify_llm_failure(kind('bad configuration')).retryable


@pytest.mark.asyncio
async def test_read_error_retries_before_output_only(monkeypatch):
    from tests.test_query_loop_retry_a2 import _FlakyClient, _run
    from common.errors import NetworkError
    from msgtypes.events import LlmRetryEvent
    client = _FlakyClient(error=httpx.ReadError('connection reset'))
    events, store = await _run(client, monkeypatch)
    assert client.calls == 2 and sum(isinstance(e, LlmRetryEvent) for e in events) == 1
    assert len([m for m in store.items if m.role == 'assistant']) == 1
    partial = _FlakyClient(error=httpx.ReadError('connection reset'), chunk_before_error=True)
    with pytest.raises(NetworkError):
        await _run(partial, monkeypatch)
    assert partial.calls == 1
