"""mock_llm 固定端口启动器（供 Playwright 全栈的后端上游使用）。

把 scripts/smoke_p0p1/mock_llm.py 的 ScriptedLLM 作为独立进程、固定端口拉起来，
并在 /health 上返回 {"ok":true}，这样 Playwright 的 webServer 可以把它当成
「已就绪」的服务。

不改动 mock_llm.py 本身，只是复用 ScriptedLLM（含「请求带 tools 才消费场景脚本、
旁路返回最小 content」的确定性语义）。

用法：
    py -3.11 scripts/smoke_p0p1/mock_runner.py --port 8490 --scenario t13_envelope --requests <jsonl path>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.smoke_p0p1.mock_llm import ScriptedLLM  # noqa: E402

SCENARIOS_DIR = pathlib.Path(__file__).resolve().parent / "scenarios"


def _load_responses(scenario: str):
    """加载 scenarios/<scenario>.py 的 RESPONSES（可能是 list 或 callable(h)）。"""
    path = SCENARIOS_DIR / f"{scenario}.py"
    if not path.exists():
        raise SystemExit(f"scenario not found: {scenario} ({path})")
    spec = importlib.util.spec_from_file_location(f"mock_scen_{scenario}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    responses = getattr(mod, "responses", None) or getattr(mod, "RESPONSES", None)
    if responses is None:
        raise SystemExit(f"scenario {scenario} has no responses/RESPONSES")
    # callable(h) 形式：无法在无 harness 时求值，这里仅支持 list；callable 报错提醒。
    if callable(responses):
        raise SystemExit(
            f"scenario {scenario} responses is callable(h); mock_runner needs a plain list"
        )
    return responses


def _is_continuation(msgs: list[dict], last: dict | None) -> bool:
    """是否为「工具轮后继续」的请求（决定回文本还是再次发 tool_call）。

    引擎 continuation 的真实形态（见 prompt/turn_context.py 注释）：
    - 末条 role == "tool"（tool_result）；或
    - 末条是合成 user，内容含 Continue 指令
      （append_text_blocks_to_last_user 在末条为 tool 时新插一条 user）。
    仅当这两个判定都否定才是「新用户轮」（fresh → 发 responses[0] 工具调用）。
    """
    if last is None:
        return False
    if last.get("role") == "tool":
        return True
    if last.get("role") != "user":
        return False
    content = last.get("content")
    if isinstance(content, list):
        text = " ".join(
            str(b.get("text") or "") for b in content if isinstance(b, dict)
        )
    else:
        text = str(content or "")
    return "# Continue（续写原问题" in text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--scenario", default="")
    ap.add_argument("--responses", default="", help="JSON 文件，内容是 responses 列表")
    ap.add_argument("--requests", default="")
    args = ap.parse_args()

    if args.responses:
        resp_path = pathlib.Path(args.responses)
        responses = json.loads(resp_path.read_text("utf-8"))
    elif args.scenario:
        responses = _load_responses(args.scenario)
    else:
        raise SystemExit("need --responses <json> or --scenario <name>")

    from scripts.smoke_p0p1.mock_llm import _render

    def _record(mode: str, body: dict) -> None:
        """诊断：把每个主轮请求的角色序列 + 命中分支落到 --requests jsonl。

        用于排查「Write 被重复发起」类问题——能直接看到 continuation 轮
        (last.role) 到底是不是 'tool'，以及 mock 每轮回的是 responses[0] 还是 [1]。
        """
        if not args.requests:
            return
        msgs = body.get("messages") or []
        rec = {
            "mode": mode,
            "roles": [str(m.get("role")) for m in msgs],
            "has_tools": bool(body.get("tools")),
            "last_role": msgs[-1].get("role") if msgs else None,
            "last_content_head": (
                str(msgs[-1].get("content") or "")[:200]
                if msgs
                else None
            ),
        }
        try:
            with open(args.requests, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _dispatch(body: dict) -> list[str]:
        # 无 tools = 旁路请求（标题增强等）：返回最小文本，不消费主场景。
        if not body.get("tools"):
            _record("bypass", body)
            return _render({"content": "（skipped）"})
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else None
        # continuation turn 判定：引擎在工具轮后会把 Continue 指令作为一条
        # 合成 user 消息尾插（turn_context.append_text_blocks_to_last_user 末条
        # 是 tool 时新增 user），因此不能只看 last.role=='tool'——那样会把
        # continuation 误判成 fresh，重复发起 tool_call（Write 被发两次的根源）。
        # 命中 Continue 语义（末条为 tool，或末条 user 带 Continue 指令）→
        # 纯本文收尾；否则是新用户轮 → 发起工具调用。
        if _is_continuation(msgs, last):
            r = responses[1] if len(responses) > 1 else responses[0]
            _record("continue", body)
        else:
            r = responses[0]
            _record("fresh", body)
        return _render(r)

    class _Handler(  # type: ignore[misc]
        __import__("http.server").server.BaseHTTPRequestHandler
    ):
        def log_message(self, *a):  # noqa: D102
            pass

        def _ok(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))

        def do_GET(self):  # noqa: N802
            if self.path in ("/health", "/health/"):
                self._ok()
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):  # noqa: N802
            if self.path != "/v1/chat/completions":
                self.send_response(404)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length", "0") or "0")
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in _dispatch(body):
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.write(b"\n")
                self.wfile.flush()

    from http.server import ThreadingHTTPServer

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"mock_llm listening on http://127.0.0.1:{args.port}/v1", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
