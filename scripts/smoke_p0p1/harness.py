"""冒烟 Harness：自启真实引擎 + mock LLM，驱动 HTTP/SSE。

启动方式（隔离）：
    XEYO_HOME=<tmp home>   # 配置/会话/spill/审计/memdir 全隔离
    XEYO_HTTP_PORT=<free>  # __main__.py 从该端口起找空闲，写入 portfile
    XEYO_ALLOW_LOCAL_MODEL=1
    python -m server       # uvicorn 单 worker

驱动契约（对齐 server/routers/chat.py）：
    POST /v1/chat/completions 头 X-Session-Id / X-Provider / X-Base-Url / X-Xeyo-Surface
    SSE 帧：data:{json}，xeyo 事件在 json["xy"]，助手文本在 json["choices"][0].delta.content
    权限挂起：xy.type == "permission_pending" 且带 request_id -> POST /v1/permission/resolve
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PY_DIR = REPO_ROOT / "python"

from scripts.smoke_p0p1.mock_llm import MockLLMServer, ScriptedLLM  # noqa: E402


class SmokError(RuntimeError):
    pass


@dataclass
class TurnResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    assistant: str = ""
    mock_requests: list[dict[str, Any]] = field(default_factory=list)

    def event_types(self) -> list[str]:
        return [e.get("type") for e in self.events]


class Harness:
    def __init__(self, scene_name: str, responses) -> None:
        self.scene = scene_name
        self._tmp = pathlib.Path(tempfile.mkdtemp(prefix="smoke_"))
        self.home = self._tmp / "home"
        self.workspace = self._tmp / "ws"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.requests = self._tmp / "requests.jsonl"
        self.portfile_path = self._tmp / "backend_port.json"
        self.spill_dir = self._tmp / "spill"
        self.spill_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self._tmp / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        # responses 可以是 list，也可以是 callable(h) -> list（用 workspace 注入工具路径）
        if callable(responses):
            responses = responses(self)
        self.mock = ScriptedLLM(responses, str(self.requests))
        self.file_write_tool = "Write"
        self.mock_server = MockLLMServer(self.mock.dispatch).start()
        self.base_url = ""

    # ---- lifecycle ----
    def up(self) -> "Harness":
        # 重启场景（T4/T39 会再次 up）：先杀掉残留 proc，防泄漏
        if getattr(self, "proc", None) is not None:
            self.kill_engine()
        env = {
            **os.environ,
            "XEYO_HOME": str(self.home),
            "XEYO_HTTP_HOST": "127.0.0.1",
            "XEYO_HTTP_PORT": "18100",
            "XEYO_ALLOW_LOCAL_MODEL": "1",
            "XEYO_REWIND_ENABLED": "1",
            "XEYO_PORT_FILE": str(self.portfile_path),
            "XEYO_SPILL_DIR": str(self.spill_dir),
            "XEYO_SESSIONS_DIR": str(self.sessions_dir),
        }
        out_dir = self._tmp / "logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        stdout = open(out_dir / "server.out", "w", encoding="utf-8")
        stderr = open(out_dir / "server.err", "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "server"],
            cwd=str(PY_DIR), env=env, stdout=stdout, stderr=stderr,
        )
        self.portfile = self._find_portfile()
        self.base_url = self._wait_health(self.proc)
        return self

    def down(self) -> None:
        self.kill_engine()
        try:
            self.mock_server.stop()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _find_portfile(self) -> pathlib.Path:
        for _ in range(40):
            if self.portfile_path.exists():
                return self.portfile_path
            time.sleep(0.5)
        raise SmokError("portfile not found; server may have failed to start")

    def _wait_health(self, proc: subprocess.Popen) -> str:
        deadline = time.time() + 45
        while time.time() < deadline:
            if proc.poll() is not None:
                raise SmokError(f"server exited early rc={proc.returncode}")
            try:
                data = json.loads(self.portfile.read_text("utf-8"))
                port = int(data.get("port") or 0)
            except Exception:  # noqa: BLE001
                time.sleep(0.4)
                continue
            if port <= 0:
                time.sleep(0.4)
                continue
            url = f"http://127.0.0.1:{port}"
            try:
                with urllib.request.urlopen(url + "/health", timeout=3) as r:
                    j = json.loads(r.read().decode("utf-8"))
                    if any(k in j for k in ("engine_version", "pid", "busy_sessions",
                                            "status", "ok")):
                        return url
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)
        raise SmokError("engine did not become healthy in time")

    def kill_engine(self) -> None:
        if not hasattr(self, "proc") or self.proc is None:
            return
        try:
            self.proc.kill()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def engine_pid(self) -> int:
        data = json.loads(self.portfile.read_text("utf-8"))
        return int(data.get("pid") or 0)

    # ---- HTTP 助手 ----
    def api(self, method: str, path: str, *, json_body: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any] | None]:
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(json_body).encode("utf-8") if json_body is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, {"_raw": raw}

    def create_session(self, workspace: str | None = None) -> str:
        body = {"workspace": workspace or str(self.workspace)}
        st, j = self.api("post", "/v1/sessions", json_body=body)
        if st != 200 or not j or not j.get("session_id"):
            raise SmokError(f"create_session failed: {st} {j}")
        return j["session_id"]

    def read_messages(self, sid: str) -> list[dict[str, Any]]:
        st, j = self.api("get", f"/v1/sessions/{sid}/messages")
        if st != 200:
            raise SmokError(f"read_messages failed: {st} {j}")
        messages = j.get("messages") if isinstance(j, dict) else None
        return messages or []

    def get_goal(self, sid: str) -> dict[str, Any]:
        st, j = self.api("get", f"/v1/sessions/{sid}/goal")
        if st != 200:
            raise SmokError(f"get_goal failed: {st} {j}")
        return j or {}

    def patch_goal(self, sid: str, body: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        return self.api("patch", f"/v1/sessions/{sid}/goal", json_body=body)

    def mock_requests(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            for line in self.requests.read_text("utf-8", errors="replace").splitlines():
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            pass
        return out

    # ---- 聊天驱动（读 SSE + 自动 resolve 权限）----
    def chat(self, sid: str, user_text: str, *,
             remember_permission: bool = False,
             timeout_ms: int | None = None,
             extra_body: dict[str, Any] | None = None,
             _result: "TurnResult | None" = None) -> TurnResult:
        body: dict[str, Any] = {
            "model": "mock",
            "stream": True,
            "provider": "local",
            "base_url": self.mock_server.base_url,
            "workspace": str(self.workspace),
            "messages": [{"role": "user", "content": user_text}],
        }
        if extra_body:
            body.update(extra_body)
        headers = {
            "X-Session-Id": sid,
            "X-Provider": "local",
            "X-Base-Url": self.mock_server.base_url,
            "X-Xeyo-Surface": "smoke",
            "Accept": "text/event-stream",
        }
        result = _result if _result is not None else TurnResult()
        done = threading.Event()

        def consume() -> None:
            import httpx
            with httpx.Client(timeout=300.0) as c:
                try:
                    with c.stream("POST", self.base_url + "/v1/chat/completions",
                                  json=body, headers=headers) as r:
                        if not r.is_success:
                            result.events.append({"type": "__http_error__",
                                                  "status": r.status_code})
                            return
                        for line in r.iter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            if not payload:
                                continue
                            try:
                                obj = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            xy = obj.get("xy")
                            if isinstance(xy, dict):
                                result.events.append(xy)
                                if xy.get("type") == "permission_pending":
                                    self._resolve_permission(xy.get("request_id", ""),
                                                            remember_permission)
                            else:
                                for ch in obj.get("choices") or []:
                                    d = ch.get("delta") or {}
                                    if d.get("content"):
                                        result.assistant += d["content"]
                except httpx.HTTPError as e:
                    result.events.append({"type": "__transport_error__",
                                          "detail": str(e), "status": 0})
                finally:
                    done.set()

        t = threading.Thread(target=consume, daemon=True)
        t.start()
        t.join(timeout=timeout_ms or 180.0)
        result.mock_requests = self.mock_requests()
        return result

    def chat_async(self, sid: str, user_text: str, **kw) -> "tuple[threading.Thread, TurnResult]":
        """非阻塞开启一轮 turn；调用方轮询 result.events 观察进行中状态（增量写入）。"""
        result = TurnResult()
        t = threading.Thread(
            target=lambda: self.chat(sid, user_text, _result=result, **kw), daemon=True)
        t.start()
        return t, result

    def _resolve_permission(self, request_id: str, remember: bool) -> None:
        if not request_id:
            return
        body = {"request_id": request_id, "approved": True, "actor": "smoke",
                "outcome": "allow", "remember": remember}
        req = urllib.request.Request(
            self.base_url + "/v1/permission/resolve",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
        except Exception:  # noqa: BLE001
            pass

    def read_spill_files(self) -> list[pathlib.Path]:
        if not self.spill_dir.exists():
            return []
        return [p for p in self.spill_dir.rglob("*") if p.is_file()]
