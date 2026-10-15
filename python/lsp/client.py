"""LSP stdio JSON-RPC 客户端（Content-Length 分帧）。

只做「够用且不阻塞」的一层：读线程分发响应/通知，请求带超时，服务器反向请求
（``workspace/configuration`` / ``client/registerCapability``）一律中性应答——
不应答会让某些服务器在初始化后卡住，那是"看起来能连、实际不能用"的坏形态。

不使用第三方 LSP SDK：依赖面越小，越不容易因为某个 SDK 的版本变化让"读代码"
这条主路径挂掉。协议面只覆盖 definition / references / hover / documentSymbol /
publishDiagnostics —— 即"文本搜索给不了"的那几件事。
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lsp.servers import ServerSpec

_log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 20.0
#: 初始化给服务器更长的时间（大仓索引慢）。
INIT_TIMEOUT_S = 60.0


class LspError(RuntimeError):
    """语言服务器不可用或协议失败（消息为中性事实）。"""


@dataclass
class Diagnostic:
    line: int
    character: int
    end_line: int
    end_character: int
    severity: int
    message: str
    source: str = ""
    code: str = ""

    def render(self, path: str) -> str:
        names = {1: "error", 2: "warning", 3: "info", 4: "hint"}
        level = names.get(int(self.severity or 0), "info")
        src = f" [{self.source}]" if self.source else ""
        return (
            f"{path}:{self.line + 1}:{self.character + 1}: {level}{src} "
            f"{self.message.strip()}"
        )


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Any = None


class LspClient:
    """一个语言服务器进程 + 一条 stdio 连接。"""

    def __init__(
        self,
        spec: ServerSpec,
        root: str | Path,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.spec = spec
        self.root = Path(root).resolve()
        self.timeout = float(timeout)
        self._proc: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._pending_lock = threading.Lock()
        self._diagnostics: dict[str, list[Diagnostic]] = {}
        self._diag_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._open_docs: dict[str, int] = {}
        self._closed = False

    # -- 生命周期 -----------------------------------------------------------

    def start(self) -> None:
        if self._proc is not None:
            return
        try:
            self._proc = subprocess.Popen(
                list(self.spec.command),
                cwd=str(self.root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise LspError(f"cannot start {self.spec.label}: {exc}") from exc
        self._reader = threading.Thread(
            target=self._read_loop, name="xeyo-lsp-reader", daemon=True
        )
        self._reader.start()
        self.initialize()

    def stop(self) -> None:
        self._closed = True
        proc = self._proc
        if proc is None:
            return
        try:
            self.notify("exit", None)
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None

    # -- 协议 ---------------------------------------------------------------

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        stream = proc.stdout
        while not self._closed:
            try:
                length = self._read_headers(stream)
            except Exception:  # noqa: BLE001 — 连接断开：唤醒所有等待者
                break
            if length is None:
                break
            if length <= 0:
                continue
            try:
                body = stream.read(length)
            except Exception:  # noqa: BLE001
                break
            if not body:
                break
            try:
                message = json.loads(body.decode("utf-8", "replace"))
            except (ValueError, UnicodeDecodeError):
                continue
            self._dispatch(message)
        self._fail_all_pending("language server connection closed")

    @staticmethod
    def _read_headers(stream: Any) -> int | None:
        length: int | None = None
        while True:
            line = stream.readline()
            if not line:
                return None
            text = line.decode("utf-8", "replace").strip()
            if not text:
                return length
            if ":" in text:
                key, _, value = text.partition(":")
                if key.strip().lower() == "content-length":
                    try:
                        length = int(value.strip())
                    except ValueError:
                        length = None

    def _dispatch(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        method = str(message.get("method") or "")
        msg_id = message.get("id")
        if msg_id is not None and not method:
            with self._pending_lock:
                pending = self._pending.pop(int(msg_id), None)
            if pending is not None:
                pending.result = message.get("result")
                pending.error = message.get("error")
                pending.event.set()
            return
        if msg_id is not None and method:
            # 服务器 → 客户端请求：中性应答，避免服务器在初始化后卡住。
            self._answer_server_request(msg_id, method, message.get("params"))
            return
        if method == "textDocument/publishDiagnostics":
            self._store_diagnostics(message.get("params") or {})

    def _answer_server_request(self, msg_id: Any, method: str, params: Any) -> None:
        result: Any = None
        if method == "workspace/configuration":
            items = (params or {}).get("items") if isinstance(params, dict) else None
            result = [None] * len(items) if isinstance(items, list) else []
        try:
            self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})
        except Exception:  # noqa: BLE001 — 应答失败不影响本进程结论
            _log.debug("lsp server request answer failed: %s", method)

    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise LspError("language server is not running")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        frame = b"Content-Length: %d\r\n\r\n" % len(data) + data
        with self._write_lock:
            proc.stdin.write(frame)
            proc.stdin.flush()

    def request(self, method: str, params: Any, *, timeout: float | None = None) -> Any:
        with self._id_lock:
            self._next_id += 1
            request_id = self._next_id
        pending = _Pending()
        with self._pending_lock:
            self._pending[request_id] = pending
        try:
            self._send(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
        except LspError:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        wait = self.timeout if timeout is None else float(timeout)
        if not pending.event.wait(wait):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise LspError(f"{method} timed out after {wait:g}s")
        if pending.error is not None:
            raise LspError(f"{method} failed: {pending.error}")
        return pending.result

    def notify(self, method: str, params: Any) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _fail_all_pending(self, reason: str) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.error = {"message": reason}
            item.event.set()

    # -- 高层能力 -----------------------------------------------------------

    def initialize(self) -> None:
        self.request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "xeyo", "version": "1"},
                "rootUri": self.root.as_uri(),
                "workspaceFolders": [
                    {"uri": self.root.as_uri(), "name": self.root.name or "workspace"}
                ],
                "capabilities": {
                    "textDocument": {
                        "definition": {},
                        "references": {},
                        "hover": {"contentFormat": ["plaintext", "markdown"]},
                        "documentSymbol": {},
                        "publishDiagnostics": {},
                        "synchronization": {},
                    },
                    "workspace": {"configuration": True, "workspaceFolders": True},
                },
            },
            timeout=INIT_TIMEOUT_S,
        )
        self.notify("initialized", {})

    def uri_for(self, path: str | Path) -> str:
        target = Path(path)
        if not target.is_absolute():
            target = self.root / target
        return target.resolve().as_uri()

    def ensure_open(self, path: str | Path, language_id: str) -> str:
        """确保文档已 didOpen（服务器只对已打开文档提供位置类能力）。"""
        uri = self.uri_for(path)
        with self._write_lock:
            already = uri in self._open_docs
        if already:
            return uri
        target = Path(path)
        if not target.is_absolute():
            target = self.root / target
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise LspError(f"cannot read {target}: {exc}") from exc
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )
        with self._write_lock:
            self._open_docs[uri] = 1
        return uri

    def definition(self, uri: str, line: int, character: int) -> Any:
        return self.request(
            "textDocument/definition",
            {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
        )

    def references(self, uri: str, line: int, character: int, *, include_declaration: bool = True) -> Any:
        return self.request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": bool(include_declaration)},
            },
        )

    def hover(self, uri: str, line: int, character: int) -> Any:
        return self.request(
            "textDocument/hover",
            {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}},
        )

    def document_symbols(self, uri: str) -> Any:
        return self.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})

    # -- 诊断 ---------------------------------------------------------------

    def _store_diagnostics(self, params: dict[str, Any]) -> None:
        uri = str(params.get("uri") or "")
        raw = params.get("diagnostics")
        if not uri or not isinstance(raw, list):
            return
        parsed: list[Diagnostic] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            start = item.get("range", {}).get("start", {}) if isinstance(item.get("range"), dict) else {}
            end = item.get("range", {}).get("end", {}) if isinstance(item.get("range"), dict) else {}
            parsed.append(
                Diagnostic(
                    line=int(start.get("line") or 0),
                    character=int(start.get("character") or 0),
                    end_line=int(end.get("line") or 0),
                    end_character=int(end.get("character") or 0),
                    severity=int(item.get("severity") or 0),
                    message=str(item.get("message") or ""),
                    source=str(item.get("source") or ""),
                    code=str(item.get("code") or ""),
                )
            )
        with self._diag_lock:
            self._diagnostics[uri] = parsed

    def diagnostics(self, path: str | Path) -> list[Diagnostic]:
        uri = self.uri_for(path)
        with self._diag_lock:
            return list(self._diagnostics.get(uri, ()))


__all__ = ["DEFAULT_TIMEOUT_S", "INIT_TIMEOUT_S", "Diagnostic", "LspClient", "LspError"]
