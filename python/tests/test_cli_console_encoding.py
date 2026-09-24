"""CLI 的 --json 输出必须能在英文/中文 Windows 控制台上打印非 ASCII 会话数据。

``print(json.dumps(..., ensure_ascii=False))`` 在 cp437/cp936 下会抛
UnicodeEncodeError——恰恰是机器读数的那条路径（--json 用来被管道/脚本消费）。
这类缺陷只能在真实子进程里复现：测试自己的 stdout 不是终端。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PY_ROOT = Path(__file__).resolve().parents[1]

_STUB = """
import json, sys
import cli.http_api as http_api
http_api.list_sessions = lambda client: [
    {"id": "sess_x", "title": "修 bug 🚀 压缩", "updated_at": 1},
]
http_api.get_messages = lambda client, sid: {
    "session_id": sid,
    "messages": [{"role": "user", "content": "帮我看这个 🚀"}],
}
from cli.sessions_cmd import cmd_list, cmd_show
rc1 = cmd_list(as_json=True)
rc2 = cmd_show("sess_x", as_json=True)
print(json.dumps({"rc_list": rc1, "rc_show": rc2}))
"""


@pytest.mark.parametrize("encoding", ["cp437", "cp936", "ascii"])
def test_json_output_survives_a_hostile_console_encoding(encoding: str) -> None:
	"""ascii 是最狠的一档：中文提示词一行都编码不下。"""
	import os

	proc = subprocess.run(
		[sys.executable, "-c", _STUB],
		cwd=str(PY_ROOT),
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=120,
		env={**os.environ, "PYTHONIOENCODING": encoding, "PYTHONPATH": str(PY_ROOT)},
	)
	assert "UnicodeEncodeError" not in proc.stderr, proc.stderr[-400:]
	assert "修 bug 🚀 压缩" in proc.stdout, proc.stdout[-400:]
	assert '"rc_list": 0' in proc.stdout and '"rc_show": 0' in proc.stdout
