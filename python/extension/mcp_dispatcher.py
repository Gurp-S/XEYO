"""One receiver per transport generation; replies have exactly one request owner."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    response: dict | None = None
    error: BaseException | None = None


class McpDispatcher:
    def __init__(self, transport: Any, notification: Callable[[dict], None]):
        self.transport = transport
        self.notification = notification
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._closed = threading.Event()
        self._notifications: queue.Queue = queue.Queue()
        self._reader = threading.Thread(target=self._receive, daemon=True, name="mcp-replies")
        self._worker = threading.Thread(target=self._notify, daemon=True, name="mcp-notifications")
        self._reader.start()
        self._worker.start()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def request(self, request: dict, timeout: float, abort=None) -> Any:
        from extension.mcp_client import McpError, McpProtocolError, McpTimeoutError

        rid = request["id"]
        pending = _Pending()
        with self._lock:
            if self._closed.is_set():
                raise McpProtocolError("mcp transport closed")
            self._pending[rid] = pending
        unsubscribe = None
        def cancel(reason):
            with self._lock:
                if pending.event.is_set():
                    return
                pending.error = McpProtocolError("mcp request cancelled; remote outcome unconfirmed")
                pending.event.set()
            try:
                self.transport.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                     "params": {"requestId": rid, "reason": str(reason)}})
            except Exception:
                pass
        try:
            self.transport.send(request)
            if abort is not None:
                unsubscribe = abort.on_abort(cancel)
            if not pending.event.wait(max(0.0, timeout)):
                # Cancellation is best effort. It does not establish that remote
                # execution stopped or that its side effects were rolled back.
                if request["method"] != "initialize":
                    try:
                        self.transport.send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                             "params": {"requestId": rid, "reason": "request timeout"}})
                    except Exception:
                        pass
                raise McpTimeoutError(f"mcp request {request['method']} timed out after {timeout}s")
            if pending.error is not None:
                raise pending.error
            response = pending.response or {}
            if response.get("error") is not None:
                raise McpError(f"mcp {request['method']} error: {response['error']}")
            if "result" not in response:
                raise McpProtocolError(f"mcp {request['method']} missing result")
            return response["result"]
        finally:
            if unsubscribe is not None:
                unsubscribe()
            with self._lock:
                self._pending.pop(rid, None)

    def _receive(self) -> None:
        from extension.mcp_client import McpProtocolError

        try:
            while not self._closed.is_set():
                response = self.transport.recv(0.1)
                if response is None:
                    if not self.transport.alive():
                        raise McpProtocolError("mcp transport exited")
                    # Some test/embedded transports return immediately.
                    self._closed.wait(0.001)
                    continue
                if "id" not in response:
                    self._notifications.put(response)
                    continue
                with self._lock:
                    pending = self._pending.get(response.get("id"))
                    if pending is not None and not pending.event.is_set():
                        pending.response = response
                        pending.event.set()
                # Late/unknown ids have no owner; never deliver to another call.
        except Exception as exc:
            self._fail(McpProtocolError(f"mcp receive failed: {type(exc).__name__}: {exc}"))

    def _notify(self) -> None:
        while not self._closed.is_set():
            item = self._notifications.get()
            if item is None or self._closed.is_set():
                return
            try:
                self.notification(item)
            except Exception:
                # A failed schema refresh cannot take down reply delivery.
                import logging
                logging.getLogger(__name__).exception("mcp notification handler failed")

    def _fail(self, error: BaseException) -> None:
        with self._lock:
            self._closed.set()
            for pending in self._pending.values():
                if not pending.event.is_set():
                    pending.error = error
                    pending.event.set()
        self._notifications.put(None)

    def close(self) -> None:
        from extension.mcp_client import McpProtocolError

        self._fail(McpProtocolError("mcp transport closed"))
        for thread in (self._reader, self._worker):
            if thread is not threading.current_thread():
                thread.join(timeout=1)

