"""本地 bridge HTTP 面（`bridge/http.py`）的畸形请求体必须回 4xx，而不是掐连接。

缺陷（2026-10-03 真端口实测复现并修复）：`_read_json()` 里两处会抛**非 JSONDecodeError** 的异常——
`int(Content-Length)` 的 ValueError、`raw.decode("utf-8")` 的 UnicodeDecodeError，
而两个调用点只写 `except json.JSONDecodeError`。于是异常逃出 `do_POST`，
`BaseHTTPRequestHandler` 的行为是打一段 traceback 到 stderr 然后**关连接、不发任何响应**：

    C2 非 UTF-8 请求体        → 客户端 RemoteDisconnected（改后：400 …不是合法 UTF-8…）
    C3 Content-Length: abc    → 客户端 RemoteDisconnected（改后：400 …不是整数…）

这条对 GUI/桌宠的意义：桌面壳把 bridge 当本地服务用，"连接被掐"在界面上是一个没有
原因的中断，而服务端只留下一条 traceback。措辞上也没有说谎：非文本字节不叫 "bad json"。

第三处连带缺陷（同一次实测暴露）：拒掉畸形 `Content-Length` 时请求体没法排空，余下的字节
会在 keep-alive 连接上被当成下一个请求行 ⇒ 同连接的**下一枪**变成
`501 Unsupported method ('{"sessionId":"s"}')`。修法是这类拒绝显式关连接并写上
`Connection: close`；体已读干净的拒绝（非 UTF-8）仍保持连接存活。
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

import bridge.http as bh


class _StubPool:
    def try_begin(self, sid: str) -> bool:
        return True

    def end(self, sid: str) -> None:
        return None

    def get(self, sid: str, cwd: str | None = None) -> Any:
        raise ValueError("stub: no engine")

    def usage_snapshot(self) -> dict[str, Any]:
        return {}

    def interrupt(self, sid: str) -> bool:
        return True


@pytest.fixture()
def server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bh, "_ensure_runtime", lambda: (_StubPool(), object()))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), bh.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "bridge 服务线程没退出：夹具会拖住整套件"


def _post(port: int, path: str, body: bytes, content_length: str | None) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("POST", path)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Host", f"127.0.0.1:{port}")
        if content_length is not None:
            conn.putheader("Content-Length", content_length)
        conn.endheaders(body)
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        return resp.status, payload
    finally:
        conn.close()


NON_UTF8 = '{"text":"\xff\xfe"}'.encode("latin-1")


def _raw_request(
    port: int, path: str, body: bytes, content_length: str | None,
    follow_up: bytes | None = None,
) -> tuple[int | None, dict[str, str], bytes, bytes]:
    """裸 socket 走一枪（可选在同一条连接上再打第二枪），把竞态如实交回。

    畸形 `Content-Length` 的拒绝路径显式关连接，而请求体留在服务端接收缓冲里
    ⇒ Windows 常以 RST 收尾，`http.client.getresponse()` 会抛
    `ConnectionAbortedError [WinError 10053]`。那是"这条连接作废"的合法表现，
    不是缺陷；用它当判据会把负载竞态测成红。所以这里：
    - 状态/头部/正文能读到多少就返回多少，读不到返回 None；
    - 第二枪的原始字节一并返回，由调用方判"有没有被残留体污染成 501"。
    """
    head = f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
    if content_length is not None:
        head += f"Content-Length: {content_length}\r\n"
    sock = socket.socket()
    try:
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        try:
            sock.sendall(head.encode() + b"\r\n" + body)
        except OSError:
            return None, {}, b"", b""
        buf = b""
        try:
            while b"\r\n\r\n" not in buf:
                part = sock.recv(1024)
                if not part:
                    return None, {}, b"", b""
                buf += part
        except OSError:
            return None, {}, b"", b""
        head_blob, _, rest = buf.partition(b"\r\n\r\n")
        lines = head_blob.split(b"\r\n")
        try:
            status = int(lines[0].split()[1])
        except (IndexError, ValueError):
            return None, {}, b"", b""
        headers: dict[str, str] = {}
        for line in lines[1:]:
            k, _, v = line.partition(b":")
            headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
        need = 0
        try:
            need = max(0, int(headers.get("content-length", "0") or 0))
        except ValueError:
            need = 0
        try:
            while len(rest) < need:
                part = sock.recv(1024)
                if not part:
                    break
                rest += part
        except OSError:
            pass
        second = b""
        if follow_up is not None:
            try:
                sock.sendall(follow_up)
                while len(second) < 4096:
                    part = sock.recv(1024)
                    if not part:
                        break
                    second += part
            except OSError:
                second = b""
        return status, headers, rest, second
    finally:
        try:
            sock.close()
        except OSError:
            pass


def test_valid_json_still_reaches_the_handler(server: int) -> None:
    status, payload = _post(server, "/api/interrupt", b'{"text":"hi"}', None)
    assert status == 400
    assert payload["error"] == "sessionId required"


def test_non_utf8_body_returns_400_not_a_dropped_connection(server: int) -> None:
    """改前：RemoteDisconnected（连接被掐，无响应）。"""
    status, payload = _post(server, "/api/interrupt", NON_UTF8, str(len(NON_UTF8)))
    assert status == 400
    assert "UTF-8" in payload["error"], f"错误原因说错了：{payload}"
    assert "bad json" not in payload["error"], "非文本字节不该被报成 JSON 语法错"


def test_non_utf8_body_on_chat_endpoint(server: int) -> None:
    status, payload = _post(server, "/api/chat", NON_UTF8, str(len(NON_UTF8)))
    assert status == 400
    assert "UTF-8" in payload["error"]


def test_non_numeric_content_length_returns_400(server: int) -> None:
    """改前：`int('abc')` 的 ValueError 逃出 do_POST ⇒ RemoteDisconnected。"""
    status, payload = _post(server, "/api/interrupt", b'{"sessionId":"s"}', "abc")
    assert status == 400
    assert "Content-Length" in payload["error"]


def test_negative_content_length_returns_400(server: int, capsys) -> None:
    """read(-5) 会读到 EOF：连接不结束就永久卡在这一枪，必须在门口拒掉。

    判据用服务端真正发出的状态（访问日志）：这类拒绝显式关连接，客户端可能被
    RST 打断而读不到响应体——那是"这条连接作废"，不是"没有响应"。拿客户端读到
    什么当唯一判据，会把负载竞态测成红。
    """
    status, _headers, body, _second = _raw_request(
        server, "/api/interrupt", b'{"sessionId":"s"}', "-5"
    )
    err = capsys.readouterr().err
    assert '"POST /api/interrupt HTTP/1.1" 400 -' in err, err[-400:]
    if status is not None:
        assert status == 400
        assert "Content-Length" in json.loads(body.decode("utf-8"))["error"]


def test_malformed_json_text_still_reports_bad_json(server: int) -> None:
    """反向对照：收口不许把真正的 JSON 语法错也改成别的说法。"""
    body = b"{not json}"
    status, payload = _post(server, "/api/interrupt", body, str(len(body)))
    assert status == 400
    assert payload["error"].startswith("bad json:")


def test_malformed_content_length_does_not_poison_the_connection(server: int, capsys) -> None:
    """拒掉畸形长度时必须关连接：请求体没法排空，余下的字节会被当成下一个请求行。

    改前实测：同一连接上的第二枪拿到 `501 Unsupported method ('{"sessionId":"s"}')`。
    这里第二枪故意打在**同一条底层 socket** 上（不经 http.client 的自动重连），
    只判一件事：不许出现"残留体被当成请求行"的 501。连接已作废（一个字节都读不到
    或被 RST）同样合格——那正是 `Connection: close` 要求的后果。
    """
    follow = (
        b"POST /api/interrupt HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        b'Content-Length: 15\r\n\r\n{"text":"hi"}\r\n'
    )
    status, headers, _body, second = _raw_request(
        server, "/api/interrupt", b'{"sessionId":"s"}', "abc", follow_up=follow
    )
    err = capsys.readouterr().err
    if status is None:
        assert '"POST /api/interrupt HTTP/1.1" 400 -' in err, err[-400:]
    else:
        assert status == 400, (status, _body[:120])
        assert (headers.get("connection") or "").lower() == "close", headers
    assert b"501" not in second, second[:200]
    assert b"Unsupported method" not in second, second[:200]



def test_body_drained_rejections_keep_the_connection_alive(server: int) -> None:
    """反向对照：体已读干净的拒绝（非 UTF-8）不该顺手关连接——那是另一件事。"""
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    try:
        conn.request("POST", "/api/interrupt", NON_UTF8, {
            "Content-Type": "application/json",
            "Content-Length": str(len(NON_UTF8)),
        })
        first = conn.getresponse()
        first.read()
        assert first.status == 400
        assert (first.getheader("Connection") or "").lower() != "close"

        conn.request("POST", "/api/interrupt", b'{"text":"hi"}', {"Content-Type": "application/json"})
        second = conn.getresponse()
        assert second.status == 400
        assert b"sessionId" in second.read()
    finally:
        conn.close()


def test_read_json_raises_the_contained_type() -> None:
    """单元层钉子（不经过 socket）：两类畸形都必须是 MalformedRequestBody（ValueError 子类）。

    夹具自证放在 `test_valid_json_still_reaches_the_handler`：那条必须真连上服务端，
    否则socket 类用例可能因"根本没连通"而假绿。
    """
    with pytest.raises(bh.MalformedRequestBody):
        _call_read_json(b"{}", "abc")
    with pytest.raises(bh.MalformedRequestBody):
        _call_read_json(NON_UTF8, str(len(NON_UTF8)))


def _call_read_json(body: bytes, content_length: str) -> Any:
    class _R:
        def __init__(self, data: bytes) -> None:
            self._buf = data

        def read(self, n: int) -> bytes:
            out, self._buf = self._buf[:n], self._buf[n:]
            return out

    h = bh.Handler.__new__(bh.Handler)
    h.headers = {"Content-Length": content_length}  # type: ignore[assignment]
    h.rfile = _R(body)  # type: ignore[assignment]
    return h._read_json()
