"""脚本化的 OpenAI 兼容 LLM 上游，供端到端冒烟使用。

实现 /v1/chat/completions（流式 SSE）。每条场景按顺序消费 responses[i]，
超出响应数时复用最后一条（吞掉标题增强/子代理等旁路请求，保持确定性）。

关键协议对齐（model/_openai_common.py）：
- 每行形如 ``data: {json}``；
- 助手文本增量用 ``choices[0].delta.content``；
- 工具用 ``choices[0].delta.tool_calls[index] = {index,id,type,function:{name,arguments}}``，
  arguments 可整段发出（能解析即触发 tool_use）；
- 末帧可带 ``usage``（prompt_tokens/completion_tokens/total_tokens/context_limit）；
- 结束用 ``data: [DONE]``。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


def _sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # noqa: D102
        pass

    def _read_body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        body = self._read_body()
        sse = self.server.dispatch(body)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("x-request-id", "mock")
        self.end_headers()
        try:
            for chunk in sse:
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.write(b"\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class MockLLMServer:
    """启动脚本化 mock 上游；dispatch(body) -> list[str]（SSE 行）。"""

    def __init__(self, dispatch: Callable[[dict[str, Any]], list[str]]) -> None:
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._srv.dispatch = dispatch  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._srv.server_address
        return f"http://{host}:{port}/v1"

    def start(self) -> "MockLLMServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()


def _render(response: dict[str, Any]) -> list[str]:
    """把一个响应模板转成 SSE 行。"""
    lines: list[str] = []
    lines.append(_sse({"id": "mock", "object": "chat.completion", "model": "mock",
                       "choices": [{"index": 0, "delta": {"role": "assistant"},
                                    "finish_reason": None}]}))
    content = response.get("content") or ""
    if content:
        lines.append(_sse({"id": "mock", "object": "chat.completion.chunk", "model": "mock",
                           "choices": [{"index": 0, "delta": {"content": content},
                                        "finish_reason": None}]}))
    tool_calls = response.get("tool_calls") or []
    for i, tc in enumerate(tool_calls):
        args = tc.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args, ensure_ascii=False)
        lines.append(_sse({
            "id": "mock", "object": "chat.completion.chunk", "model": "mock",
            "choices": [{"index": 0,
                         "delta": {"tool_calls": [{"index": i, "id": tc.get("id") or f"call_{i}",
                                                   "type": "function",
                                                   "function": {"name": tc["name"],
                                                                "arguments": args}}]},
                         "finish_reason": None}]}))
    finish = "tool_calls" if tool_calls else "stop"
    lines.append(_sse({"id": "mock", "object": "chat.completion.chunk", "model": "mock",
                       "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}))
    usage = response.get("usage") or {"prompt_tokens": 20, "completion_tokens": 8,
                                      "total_tokens": 28, "context_limit": 128000}
    lines.append(_sse({"id": "mock", "object": "chat.completion.chunk", "model": "mock",
                       "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
                       "usage": usage}))
    lines.append("data: [DONE]")
    return lines


class ScriptedLLM:
    """按顺序消费 responses；记录每个请求到 requests_path。"""

    def __init__(self, responses: list[dict[str, Any]], requests_path: str) -> None:
        self.responses = responses
        self.requests_path = requests_path
        self._idx = 0
        self._lock = threading.Lock()

    def dispatch(self, body: dict[str, Any]) -> list[str]:
        self._record(body)
        # 主轮次请求带 tools（引擎把工具目录发给模型）；旁路（标题增强等）不带 tools。
        # 旁路请求不消费场景脚本，返回一段最小 content，保持主脚本确定性。
        if not body.get("tools"):
            return _render({"content": "（skipped）"})
        with self._lock:
            i = min(self._idx, len(self.responses) - 1) if self.responses else -1
            self._idx += 1
        if i < 0:
            return _render({"content": "done"})
        return _render(self.responses[i])

    def _record(self, body: dict[str, Any]) -> None:
        rec = {
            "model": body.get("model", ""),
            "stream": body.get("stream", True),
            "messages": [{"role": m.get("role"), "content": _short(m.get("content"))}
                         for m in body.get("messages", [])],
            "tools": [t.get("function", {}).get("name") if isinstance(t, dict) else t
                      for t in body.get("tools", [])],
        }
        try:
            with open(self.requests_path, "a", encoding="utf-8", errors="replace") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _short(content: Any, limit: int = 1_000_000) -> str:
    if isinstance(content, str):
        return content[:limit]
    if isinstance(content, list):
        s = json.dumps(content, ensure_ascii=False)
        return s[:limit]
    return str(content)[:limit]
