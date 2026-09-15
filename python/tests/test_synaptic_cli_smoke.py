"""synaptic CLI 冒烟（第六轮真实盲区）：``__main__`` 全路径必须真的能跑。

## 为什么有本文件

``f5652db`` 给 ``run_session`` 接上生产触发口径旁路开关，并在
``__main__._replay`` 里读 ``XEYO_WSC_TRIGGER_RATIO`` / ``XEYO_WSC_CONTEXT_LIMIT``
——但该文件漏了 ``import os`` ⇒ CLI 一跑就 ``NameError``，**A/B 根本没跑**。

当时的 ``tests/wsc`` 全是 ``project()`` 级单测，**不经过 ``__main__._replay``**，
所以整条 CLI 接线是零覆盖。本文件把 CLI 表面钉住：走真实子进程（等价用户敲的
命令），任何 import / 环境变量接线 / 报告落盘错误都会在这里红，而不是等到
"以为在跑 A/B、其实一条都没跑"。

运行：``py -3.11 -m pytest tests/test_synaptic_cli_smoke.py -q``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PY_ROOT = Path(__file__).resolve().parents[1]

#: 最小合成会话：user/assistant 交替 + 若干 tool 行。不依赖任何 live 语料。
_SESSION_ROWS: tuple[dict, ...] = tuple(
	row
	for i in range(1, 7)
	for row in (
		{"role": "user", "content": f"第 {i} 个用户回合：请分析模块 {i} 的实现细节。"},
		{"role": "assistant", "content": f"我先读一下 module_{i}.py 再给结论。"},
		{
			"role": "tool",
			"name": "Read",
			"content": f"module_{i}.py 的正文占位（第 {i} 段）" + "x" * 40,
		},
		{"role": "assistant", "content": f"module_{i}.py 的结论：结构清晰，见上文。"},
	)
)


def _run(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
	env = dict(os.environ)
	env["PYTHONPATH"] = str(_PY_ROOT)
	# 触发口径默认必须干净：由用例显式设置，避免宿主环境泄漏进 A/B
	env.pop("XEYO_WSC_TRIGGER_RATIO", None)
	env.pop("XEYO_WSC_CONTEXT_LIMIT", None)
	if env_extra:
		env.update(env_extra)
	return subprocess.run(
		[sys.executable, "-m", "synaptic", *args],
		cwd=str(_PY_ROOT),
		env=env,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		timeout=300,
	)


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
	d = tmp_path / "sessions"
	d.mkdir()
	(d / "sess_demo.jsonl").write_text(
		"".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _SESSION_ROWS),
		encoding="utf-8",
	)
	return d


def test_levels_lists_tiers() -> None:
	"""``levels`` 子命令：import 面 + 水位分档表可用。"""
	cp = _run("levels")
	assert cp.returncode == 0, cp.stderr
	assert "Medium+" in cp.stdout


def test_check_is_clean() -> None:
	"""``check``：静态禁止 import 自检必须干净（0 退出码）。"""
	cp = _run("check")
	assert cp.returncode == 0, cp.stderr
	payload = json.loads(cp.stdout)
	assert payload["forbidden_imports"] == []


def test_replay_runs_end_to_end(session_dir: Path, tmp_path: Path) -> None:
	"""``replay`` 全路径可执行并落盘报告（第六轮 NameError 的回归锚）。"""
	out = tmp_path / "out"
	cp = _run(
		"replay",
		"--sessions-dir",
		str(session_dir),
		"--out",
		str(out),
		"--min-messages",
		"1",
	)
	assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"
	report = out / "wsc_offline_report.json"
	assert report.is_file(), f"报告未落盘：{cp.stdout}"
	payload = json.loads(report.read_text(encoding="utf-8"))
	assert payload.get("n_files") == 1


def test_replay_accepts_trigger_env_without_error(session_dir: Path, tmp_path: Path) -> None:
	"""触发口径环境变量被 CLI 读到且不炸（第六轮 ``NameError`` 的直接回归锚）。

	⚠️ 待办②：§4 要求的 ``trigger_skip_rate`` **报告字段目前不存在** ——
	``report.py`` 只聚合 ``gain_gate_skip_rate``；第六轮只做到
	``TurnRecord.trigger_skipped`` 的逐条埋点，聚合出表尚未落地。本用例
	**不假装它已存在**（那是待办②第一件事），只钉住"CLI 读得到这两个环境
	变量、且报告照常落盘"这条第六轮真正断掉的接线。
	"""
	out_on = tmp_path / "on"
	cp = _run(
		"replay",
		"--sessions-dir",
		str(session_dir),
		"--out",
		str(out_on),
		"--min-messages",
		"1",
		env_extra={
			"XEYO_WSC_TRIGGER_RATIO": "0.8",
			"XEYO_WSC_CONTEXT_LIMIT": "16",
		},
	)
	assert cp.returncode == 0, f"stdout={cp.stdout}\nstderr={cp.stderr}"
	on = json.loads((out_on / "wsc_offline_report.json").read_text(encoding="utf-8"))
	assert on.get("n_files") == 1
