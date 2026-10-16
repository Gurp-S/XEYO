"""Offline installed-wheel checks for CLI and the GUI/TUI HTTP/SSE backend."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="xeyo-product-wheel-") as temporary:
        root = Path(temporary)
        for key, name in {"XEYO_HOME": "home", "XEYO_CWD": "workspace",
                          "XEYO_SESSIONS_DIR": "sessions", "XEYO_USAGE_DIR": "usage",
                          "XEYO_SNAPSHOTS_DIR": "snapshots", "XEYO_SPILL_DIR": "spill",
                          "XEYO_JOURNAL_DIR": "journal", "XEYO_METRICS_DIR": "metrics"}.items():
            directory = root / name
            directory.mkdir()
            os.environ[key] = str(directory)
        from engine.env_switches import isolation_pins
        for key, value in isolation_pins():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.environ["XEYO_ALLOW_FAKE_MODEL"] = "1"
        from cli.main import app as cli_app
        from typer.testing import CliRunner
        runner = CliRunner()
        help_result = runner.invoke(cli_app, ["--help"])
        assert help_result.exit_code == 0, help_result.stdout
        chat = runner.invoke(cli_app, ["chat", "--provider", "fake", "--cwd", str(root / "workspace"),
                                       "--print", "--json", "hello"])
        assert chat.exit_code == 0, chat.stdout + str(chat.exception)
        rows = [json.loads(line) for line in chat.stdout.splitlines() if line.strip()]
        assert any(row.get("type") == "result" and not row.get("is_error") for row in rows), rows
        console = Path(sys.executable).parent / ("xeyo.exe" if os.name == "nt" else "xeyo")
        environment = {**os.environ, "PYTHONUTF8": "1"}
        entry = subprocess.run([str(console), "--help"], cwd=root, capture_output=True,
                               text=True, encoding="utf-8", timeout=30, env=environment)
        assert entry.returncode == 0 and "XEYO" in entry.stdout, entry.stdout + entry.stderr
        module = subprocess.run([sys.executable, "-I", "-X", "utf8", "-m", "cli", "--help"], cwd=root,
                                capture_output=True, text=True, encoding="utf-8", timeout=30, env=environment)
        assert module.returncode == 0 and "XEYO" in module.stdout, module.stdout + module.stderr
        from server.app import app
        from fastapi.testclient import TestClient
        client = TestClient(app, client=("127.0.0.1", 12345))
        health = client.get("/health")
        assert health.status_code == 200 and health.json()["ok"]
        response = client.post("/v1/chat/completions", json={
            "provider": "fake", "model": "fake", "session_id": "wheel-http",
            "workspace": str(root / "workspace"), "stream": True,
            "messages": [{"role": "user", "content": "hello", "id": "wheel-user"}],
        })
        assert response.status_code == 200, response.text
        assert "[DONE]" in response.text, response.text
        frames = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ") and line[6:] != "[DONE]"]
        text = "".join(frame.get("choices", [{}])[0].get("delta", {}).get("content", "")
                       for frame in frames if frame.get("choices"))
        assert text == "ok: hello", response.text
        assert not any(frame.get("error") for frame in frames), frames
        client.close()
        print(json.dumps({"ok": True, "cli_help": True, "cli_fake_chat": True,
                          "console_entry": True, "module_entry": True,
                          "http_health": True, "http_sse_chat": True, "done_frame": True}))


if __name__ == "__main__":
    main()
