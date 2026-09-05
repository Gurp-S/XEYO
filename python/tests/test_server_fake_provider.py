"""HTTP 全栈测试用 `fake` provider 门禁契约测试。

运行:
  py -3.11 -m pytest tests/test_server_fake_provider.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from server.app import app  # noqa: E402


def _client() -> TestClient:
	return TestClient(app)


def _join_delta_content(text: str) -> str:
	"""从 SSE frame 里抽出 `choices[0].delta.content` 并拼接。

	FakeModelClient 逐字符流式（一帧一字符），原始 SSE 文本不含连续子串，
	故按 delta.content 抽取后拼接再断言。
	"""
	parts: list[str] = []
	for m in re.finditer(r'"delta"\s*:\s*\{[^}]*"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
		parts.append(m.group(1))
	return "".join(parts)


def _chat_json() -> dict:
	return {
		"model": "fake",
		"stream": True,
		"session_id": "fake-http-test",
		"provider": "fake",
		"messages": [{"role": "user", "content": "hi"}],
	}


def test_fake_provider_requires_gate(monkeypatch) -> None:
	"""XEYO_ALLOW_FAKE_MODEL 未开启时，provider=fake 必须被拒（400）。"""
	monkeypatch.delenv("XEYO_ALLOW_FAKE_MODEL", raising=False)
	c = _client()
	r = c.post("/v1/chat/completions", json=_chat_json())
	assert r.status_code == 400
	assert r.json()["error"]["type"] == "invalid_request"
	assert "unsupported provider: fake" in r.json()["error"]["message"]


def test_fake_provider_streams_ok(monkeypatch) -> None:
	"""门禁开启后，provider=fake 走 FakeModelClient 流式应答 `ok: <text>`。"""
	monkeypatch.setenv("XEYO_ALLOW_FAKE_MODEL", "1")
	c = _client()
	# 每个用例用独立 session，避免 SessionPool 内存态串扰。
	r = c.post(
		"/v1/chat/completions",
		json={**_chat_json(), "session_id": "fake-http-ok"},
	)
	assert r.status_code == 200
	assert r.headers.get("content-type", "").startswith("text/event-stream")
	assert "ok: hi" in _join_delta_content(r.text)
	# 收尾帧：finish_reason=stop
	assert "[DONE]" in r.text


def test_fake_provider_no_api_key_ok(monkeypatch) -> None:
	"""fake 与 local 同权：允许空 API Key（Authorization 未带 key 不被 401）。"""
	monkeypatch.setenv("XEYO_ALLOW_FAKE_MODEL", "1")
	c = _client()
	r = c.post(
		"/v1/chat/completions",
		json={**_chat_json(), "session_id": "fake-http-nokey"},
	)
	assert r.status_code == 200
	assert "ok: hi" in _join_delta_content(r.text)
