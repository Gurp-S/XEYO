"""T38：生产热路径 memory.runtime 与离线 simulator 解耦。

核心不变量：
- import memory.runtime 不再拖入 memory.simulator（及子模块）；
- 默认 project 投影路径（C2 gate 关）也不触发 simulator import；
- 估参 token_len 在生产 memory.token 与 simulator.state_model 间单点共享（不漂移）。
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parents[1]

_IMPORT_ISOLATED_CODE = (
	"import sys\n"
	"import memory.runtime\n"
	"bad = sorted(m for m in sys.modules if m.startswith('memory.simulator'))\n"
	"assert not bad, f'memory.runtime imported simulator: {bad}'\n"
	"print('OK')\n"
)

_PROJECT_PATH_CODE = (
	"import sys\n"
	"from memory.runtime import project_for_model\n"
	"from memory.working import WorkingSnapshot\n"
	"msgs = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'ok'}]\n"
	"w = WorkingSnapshot()\n"
	"out = project_for_model(msgs, w, include_memory_index=False)\n"
	"assert out, 'project projection returned empty'\n"
	"bad = sorted(m for m in sys.modules if m.startswith('memory.simulator'))\n"
	"assert not bad, f'project path imported simulator: {bad}'\n"
	"print('OK')\n"
)


def _sys_exec(code: str) -> str:
	env = dict(os.environ)
	env["PYTHONPATH"] = str(_PY_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
	env["XEYO_TOOL_AGING"] = "0"
	# T38 解耦保证在 project 快路径上成立；2026-09-06 默认 v61（会加载 simulator），
	# 故子进程用隔离 settings 显式 project（快路径、不拉 simulator）。
	import tempfile

	home = tempfile.mkdtemp(prefix="xeyo-decouple-")
	(home_p := pathlib.Path(home) / ".xeyo").mkdir(parents=True, exist_ok=True)
	(home_p / "settings.json").write_text(
		json.dumps({"memory": {"XEYO_L5": "project"}}), encoding="utf-8"
	)
	env["XEYO_HOME"] = home
	env["XEYO_CWD"] = home
	proc = subprocess.run(
		[sys.executable, "-c", code],
		capture_output=True,
		text=True,
		check=False,
		cwd=str(_PY_ROOT),
		env=env,
	)
	return proc.stdout.strip() + proc.stderr.strip()


def test_import_runtime_does_not_pull_simulator() -> None:
	assert _sys_exec(_IMPORT_ISOLATED_CODE) == "OK"


def test_project_default_path_does_not_pull_simulator() -> None:
	assert _sys_exec(_PROJECT_PATH_CODE) == "OK"


def test_token_len_shared_parity() -> None:
	from memory.simulator.state_model import token_len as sim_token_len
	from memory.token import token_len as prod_token_len

	assert prod_token_len is not None
	assert sim_token_len is not None
	for s in ("", "A", "AAAA", "AAAAA", "你好世界 tool_result", "x" * 1000):
		assert prod_token_len(s) == sim_token_len(s), s
	assert prod_token_len("") == 0
	assert prod_token_len("A" * 4) == 1
	assert prod_token_len("A" * 5) == 2


def test_token_module_has_n_lines() -> None:
	from memory.token import n_lines

	assert n_lines("") == 0
	assert n_lines("a") == 1
	assert n_lines("a\nb") == 2
