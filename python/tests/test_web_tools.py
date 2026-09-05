"""WebFetch / WebSearch: outbound ASK + SSRF + mocked HTTP."""

from __future__ import annotations

import httpx
import pytest

from engine.abort import AbortController
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.web_common import focus_text, html_to_text, is_blocked_url
from tools.web_fetch_tool import WebFetchTool, clear_fetch_cache
from tools.web_search_tool import WebSearchTool
from tools.web_search_tool.config import set_searxng_url
from tools.web_search_tool.web_search_tool import _OUT_CAP, _format_results
from tools.web_fetch_tool.web_fetch_tool import _OUT_CAP as _FETCH_OUT_CAP


@pytest.fixture(autouse=True)
def _clear_web_fetch_cache() -> None:
	clear_fetch_cache()
	yield
	clear_fetch_cache()


def test_web_policy_asks() -> None:
	d = evaluate_policy(
		"WebFetch", {"url": "https://example.com"}, cwd="."
	)
	assert d.decision == PermissionDecision.ASK
	assert d.matched_rule == "outbound_ask"
	assert "example.com" in (d.prompt or "")

	s = evaluate_policy(
		"WebSearch", {"query": "python asyncio"}, cwd="."
	)
	assert s.decision == PermissionDecision.ASK
	assert "python asyncio" in (s.prompt or "")


def test_ssrf_helpers() -> None:
	assert is_blocked_url("file:///etc/passwd")
	assert is_blocked_url("http://127.0.0.1/x")
	assert is_blocked_url("http://localhost/x")
	assert is_blocked_url("http://10.0.0.1/x")
	assert is_blocked_url("http://169.254.169.254/latest")
	assert is_blocked_url("https://example.com/") is None


def test_web_concurrency_safe() -> None:
	assert WebFetchTool.is_concurrency_safe() is True
	assert WebSearchTool.is_concurrency_safe() is True


def test_dns_failed_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
	import socket

	def boom(*_a, **_k):
		raise socket.gaierror("fail")

	monkeypatch.setattr(socket, "getaddrinfo", boom)
	assert is_blocked_url("https://no-such-host.invalid/") == "dns_failed"


def test_format_results_capped() -> None:
	rows = [
		{
			"title": "T" * 80,
			"url": f"https://example.com/{i}",
			"snippet": "S" * 200,
		}
		for i in range(20)
	]
	body = _format_results("q", "bing", rows)
	assert len(body) <= _OUT_CAP
	assert "truncated" in body or len(body) < _OUT_CAP


@pytest.mark.asyncio
async def test_webfetch_blocks_private() -> None:
	tool = WebFetchTool()
	for url in (
		"file:///etc/passwd",
		"http://127.0.0.1/",
		"http://10.1.2.3/",
	):
		r = await tool.execute({"url": url}, AbortController())
		assert r.is_error
		assert "blocked" in r.content.lower()


@pytest.mark.asyncio
async def test_webfetch_success_html(monkeypatch: pytest.MonkeyPatch) -> None:
	html = (
		"<html><body><nav>Menu noise</nav><script>x</script>"
		"<p>Hello World</p><footer>© noise</footer></body></html>"
	)

	def handler(request: httpx.Request) -> httpx.Response:
		return httpx.Response(
			200,
			headers={"content-type": "text/html; charset=utf-8"},
			content=html.encode("utf-8"),
		)

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	tool = WebFetchTool()
	r = await tool.execute(
		{"url": "https://example.com/doc"}, AbortController()
	)
	assert not r.is_error
	assert "Hello World" in r.content
	assert "Menu noise" not in r.content
	assert "© noise" not in r.content


@pytest.mark.asyncio
async def test_webfetch_prompt_focus(monkeypatch: pytest.MonkeyPatch) -> None:
	html = """
	<html><body>
	<p>Intro about cats and dogs.</p>
	<p>Asyncio gather runs awaitables concurrently.</p>
	<p>Unrelated weather report for Tuesday.</p>
	</body></html>
	"""

	def handler(request: httpx.Request) -> httpx.Response:
		return httpx.Response(
			200,
			headers={"content-type": "text/html"},
			content=html.encode("utf-8"),
		)

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	tool = WebFetchTool()
	r = await tool.execute(
		{
			"url": "https://example.com/async",
			"prompt": "How does asyncio gather work?",
		},
		AbortController(),
	)
	assert not r.is_error
	assert "gather" in r.content.lower()
	assert "weather" not in r.content.lower()


@pytest.mark.asyncio
async def test_webfetch_cache_hit(monkeypatch: pytest.MonkeyPatch) -> None:
	calls = {"n": 0}

	def handler(request: httpx.Request) -> httpx.Response:
		calls["n"] += 1
		return httpx.Response(
			200,
			headers={"content-type": "text/plain"},
			content=b"cached body",
		)

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	tool = WebFetchTool()
	a = await tool.execute(
		{"url": "https://example.com/c"}, AbortController()
	)
	b = await tool.execute(
		{"url": "https://example.com/c"}, AbortController()
	)
	assert not a.is_error and not b.is_error
	assert a.content == b.content
	assert calls["n"] == 1


def test_html_to_text_strips_chrome() -> None:
	html = "<nav>Nav</nav><p>Body</p><footer>Foot</footer>"
	text = html_to_text(html)
	assert "Body" in text
	assert "Nav" not in text
	assert "Foot" not in text


def test_focus_text_picks_matching_para() -> None:
	body = "Cats sleep.\n\nAsyncio gather waits.\n\nRain today."
	out = focus_text(body, "asyncio gather", max_chars=200)
	assert "gather" in out.lower()
	assert "Rain" not in out


@pytest.mark.asyncio
async def test_webfetch_redirect_to_private(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	def handler(request: httpx.Request) -> httpx.Response:
		if "example.com" in str(request.url):
			return httpx.Response(
				302, headers={"location": "http://127.0.0.1/secret"}
			)
		return httpx.Response(200, content=b"should not reach")

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		kwargs["follow_redirects"] = False
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	tool = WebFetchTool()
	r = await tool.execute(
		{"url": "https://example.com/go"}, AbortController()
	)
	assert r.is_error
	assert "blocked" in r.content.lower()


@pytest.mark.asyncio
async def test_websearch_parses_bing(monkeypatch: pytest.MonkeyPatch) -> None:
	html = """
	<ol id="b_results">
	  <li class="b_algo">
	    <h2><a href="https://docs.python.org/3/">Python Docs</a></h2>
	    <p>Official documentation</p>
	  </li>
	  <li class="b_algo">
	    <h2><a href="https://peps.python.org/">PEPs</a></h2>
	    <p>Python Enhancement Proposals</p>
	  </li>
	</ol>
	"""

	def handler(request: httpx.Request) -> httpx.Response:
		host = request.url.host or ""
		if "mojeek.com" in host:
			raise httpx.ConnectTimeout("mojeek blocked")
		assert "bing.com" in host
		return httpx.Response(200, text=html)

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	monkeypatch.delenv("XEYO_BRAVE_API_KEY", raising=False)
	monkeypatch.delenv("XEYO_WEBSEARCH_INCLUDE_DDG", raising=False)
	monkeypatch.delenv("XEYO_SEARXNG_URL", raising=False)
	set_searxng_url(None)
	tool = WebSearchTool()
	r = await tool.execute({"query": "python docs"}, AbortController())
	assert not r.is_error
	assert "Python Docs" in r.content
	assert "docs.python.org" in r.content
	assert "provider: bing" in r.content


@pytest.mark.asyncio
async def test_websearch_mojeek_when_bing_fails(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	mojeek_html = """
	<ul>
	  <li>
	    <a class="title" href="https://example.com/doc">Example Doc</a>
	    <p class="s">Useful snippet here</p>
	  </li>
	</ul>
	"""

	def handler(request: httpx.Request) -> httpx.Response:
		host = request.url.host or ""
		if "bing.com" in host:
			raise httpx.ConnectTimeout("connect timed out")
		if "mojeek.com" in host:
			return httpx.Response(200, text=mojeek_html)
		return httpx.Response(500, text="nope")

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	monkeypatch.delenv("XEYO_BRAVE_API_KEY", raising=False)
	monkeypatch.delenv("XEYO_WEBSEARCH_INCLUDE_DDG", raising=False)
	monkeypatch.delenv("XEYO_SEARXNG_URL", raising=False)
	set_searxng_url(None)
	tool = WebSearchTool()
	r = await tool.execute({"query": "example", "count": 3}, AbortController())
	assert not r.is_error
	assert "Example Doc" in r.content
	assert "provider: mojeek" in r.content


@pytest.mark.asyncio
async def test_websearch_searxng_preferred(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	payload = {
		"results": [
			{
				"title": "Asyncio Guide",
				"url": "https://docs.python.org/3/library/asyncio.html",
				"content": "Official asyncio docs",
			},
			{
				"title": "Private",
				"url": "http://127.0.0.1/secret",
				"content": "should drop",
			},
		]
	}

	def handler(request: httpx.Request) -> httpx.Response:
		host = request.url.host or ""
		if host in ("127.0.0.1", "localhost"):
			return httpx.Response(200, json=payload)
		# 不应需要公共搜索引擎
		raise httpx.ConnectTimeout("should not call")

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	monkeypatch.delenv("XEYO_BRAVE_API_KEY", raising=False)
	set_searxng_url("http://127.0.0.1:8080")
	tool = WebSearchTool()
	r = await tool.execute({"query": "asyncio", "count": 5}, AbortController())
	set_searxng_url(None)
	assert not r.is_error
	assert "provider: searxng" in r.content
	assert "Asyncio Guide" in r.content
	assert "127.0.0.1/secret" not in r.content


@pytest.mark.asyncio
async def test_websearch_brave_then_race(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	bing_html = """
	<ol id="b_results">
	  <li class="b_algo">
	    <h2><a href="https://example.com/doc">Example Doc</a></h2>
	    <p>Useful snippet here</p>
	  </li>
	</ol>
	"""

	def handler(request: httpx.Request) -> httpx.Response:
		host = request.url.host or ""
		if "api.search.brave.com" in host:
			raise httpx.ConnectTimeout("connect timed out")
		if "bing.com" in host:
			return httpx.Response(200, text=bing_html)
		if "mojeek.com" in host:
			raise httpx.ConnectTimeout("mojeek slow")
		return httpx.Response(500, text="nope")

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	monkeypatch.setenv("XEYO_BRAVE_API_KEY", "test-key")
	monkeypatch.delenv("XEYO_WEBSEARCH_INCLUDE_DDG", raising=False)
	set_searxng_url(None)
	tool = WebSearchTool()
	r = await tool.execute({"query": "example", "count": 3}, AbortController())
	assert not r.is_error
	assert "Example Doc" in r.content
	assert "provider: bing" in r.content


@pytest.mark.asyncio
async def test_websearch_all_fail_has_hint(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	def handler(request: httpx.Request) -> httpx.Response:
		raise httpx.ConnectTimeout("connect timed out")

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	monkeypatch.delenv("XEYO_BRAVE_API_KEY", raising=False)
	monkeypatch.delenv("XEYO_WEBSEARCH_INCLUDE_DDG", raising=False)
	set_searxng_url(None)
	tool = WebSearchTool()
	r = await tool.execute({"query": "x", "count": 2}, AbortController())
	assert r.is_error
	assert "ConnectTimeout" in r.content or "timed out" in r.content.lower()
	assert "SearXNG" in r.content or "WebFetch" in r.content


@pytest.mark.asyncio
async def test_webfetch_oversized(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	big = b"x" * (200_000 + 50)

	def handler(request: httpx.Request) -> httpx.Response:
		return httpx.Response(
			200,
			headers={"content-type": "text/plain"},
			content=big,
		)

	transport = httpx.MockTransport(handler)
	real_client = httpx.AsyncClient

	def fake_client(*args, **kwargs):
		kwargs["transport"] = transport
		return real_client(*args, **kwargs)

	monkeypatch.setattr(httpx, "AsyncClient", fake_client)
	tool = WebFetchTool()
	r = await tool.execute(
		{"url": "https://example.com/big"}, AbortController()
	)
	assert not r.is_error
	assert "truncated" in r.content.lower()
	assert len(r.content) < _FETCH_OUT_CAP + 500
