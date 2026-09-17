"""前台超时自动晋升 + shell 解析器（pwsh7→5.1 argv 调用）行为锁定。

- 晋升语义：进程**不重启**、已累积输出随晋升返回、abort 换绑后台通道。
- registry 可用 → 42 号 job（adopt_bash）；不可用 → 日志文件后台（adopt_background）。
- shell：argv 向量 + shell=False（杜绝 cmd 套壳）；Windows 上必为 PowerShell。
"""

from __future__ import annotations

import os
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.runner import (
	build_shell_argv,
	run_command,
	spawn_streaming,
)
from tools.bash_tool.bash_tool import (
	BashInput,
	BashTool,
	promote_threshold_for,
	promote_threshold_ms,
)


SLEEP_CMD = 'python -c "import time,sys; print(\'PROMOTE_ME\', flush=True); time.sleep(3)"'


# ---- shell 解析器 ----

def test_shell_argv_is_powershell_no_cmd_shell() -> None:
	argv, kind = build_shell_argv("echo hi")
	assert os.name != "nt" or kind in ("pwsh", "powershell")
	if os.name == "nt":
		assert argv[0].lower().endswith(("pwsh.exe", "powershell.exe"))
		assert "-NonInteractive" in argv and "-Command" in argv
		# 杜绝 cmd 套壳：不允许 cmd.exe 出现在调用链
		assert "cmd.exe" not in argv[0].lower()


def test_run_command_smoke() -> None:
	r = run_command("echo hello-runner", cwd=os.getcwd(), timeout_ms=30_000)
	assert r.code == 0
	assert "hello-runner" in r.stdout


# ---- 晋升阈值 ----

def test_promote_threshold_env(monkeypatch) -> None:
	monkeypatch.delenv("XEYO_BASH_PROMOTE_MS", raising=False)
	assert promote_threshold_ms() == 300_000
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "300")
	assert promote_threshold_ms() == 300
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "bogus")
	assert promote_threshold_ms() == 300_000
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "0")
	assert promote_threshold_ms() == 0


def test_promote_threshold_scales_below_command_timeout(monkeypatch) -> None:
	"""晋升阈值必须严格小于命令自身超时——否则命令先被超时杀掉、永远进不了后台。"""
	monkeypatch.delenv("XEYO_BASH_PROMOTE_MS", raising=False)
	# 默认 120s 超时 → 0.8×120s = 96s（小于超时）
	assert promote_threshold_for("echo hi", 120_000) == 96_000
	# 命令族 300s → 0.8×300s = 240s
	assert promote_threshold_for("make -j4", 300_000) == 240_000
	# cargo 420s → 上限 300s 生效（仍小于超时）
	assert promote_threshold_for("cargo build", 420_000) == 300_000
	# 极短超时 → 下限兜底，但不得超过超时本身之外的语义由调用方保证
	assert promote_threshold_for("echo hi", 1_000) == 5_000
	# env 显式覆盖优先
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "1000")
	assert promote_threshold_for("make -j4", 300_000) == 1_000
	# env 关闭
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "0")
	assert promote_threshold_for("make -j4", 300_000) == 0


def test_fast_command_not_promoted(monkeypatch, tmp_path: Path) -> None:
	# pwsh 冷启动 ~0.35s，阈值必须远大于它，否则快命令也会被误晋升。
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "5000")
	tool = BashTool(cwd=str(tmp_path))
	out = tool.call(
		BashInput(command="echo quick", timeout_ms=30_000), cwd=str(tmp_path)
	)
	assert not out.promoted
	assert not out.timed_out
	assert "quick" in out.stdout


def test_promote_disabled_zero(monkeypatch, tmp_path: Path) -> None:
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "0")
	tool = BashTool(cwd=str(tmp_path))
	out = tool.call(
		BashInput(command="echo nopro", timeout_ms=30_000), cwd=str(tmp_path)
	)
	assert not out.promoted


def test_slow_command_auto_promotes_to_log(monkeypatch, tmp_path: Path) -> None:
	# 阈值须 > pwsh 冷启动(~0.35s，保证 PROMOTE_ME 已输出) 且 < sleep 3s 总时长。
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "1500")
	tool = BashTool(cwd=str(tmp_path))
	out = tool.call(BashInput(command=SLEEP_CMD, timeout_ms=60_000), cwd=str(tmp_path))
	assert out.promoted, "slow foreground command must auto-promote"
	assert out.promoted_after_ms >= 1500
	assert out.background_task_id
	# 无 registry 会话 → 落回日志文件后台
	assert out.background_log_path and not out.background_job
	log = Path(out.background_log_path)
	assert log.is_file()
	log_text = log.read_text(encoding="utf-8", errors="replace")
	# 已累积输出随晋升返回 / 落盘（进程不重启：同一进程的输出连续可见）
	assert ("PROMOTE_ME" in (out.stdout or "")) or ("PROMOTE_ME" in log_text)
	# 等 3s sleep 自然结束 → 状态行落盘
	deadline = time.time() + 15
	while time.time() < deadline:
		text = log.read_text(encoding="utf-8", errors="replace")
		if "# status:" in text and "running" not in text.split("# status:")[-1]:
			break
		time.sleep(0.2)
	final = log.read_text(encoding="utf-8", errors="replace")
	assert "completed exit=0" in final


def test_map_promoted_content_mentions_job_and_partial(monkeypatch, tmp_path: Path) -> None:
	monkeypatch.setenv("XEYO_BASH_PROMOTE_MS", "400")
	tool = BashTool(cwd=str(tmp_path))
	out = tool.call(BashInput(command=SLEEP_CMD, timeout_ms=60_000), cwd=str(tmp_path))
	assert out.promoted
	content = tool.map_tool_result_to_content(out)
	assert "auto-moved" in content
	assert out.background_task_id in content


# ---- registry 收编通道（42 号 adopt）----

def test_adopt_registry_job_settles(tmp_path: Path) -> None:
	from server.job_registry import get_job_registry
	from tools.bash_tool.jobs_bridge import adopt_registry_job

	cmd = 'python -c "import time; time.sleep(1)"'
	h = spawn_streaming(cmd, cwd=str(tmp_path))
	assert h.spawn_error is None
	bridged = adopt_registry_job(
		handle=h,
		command=cmd,
		cwd=str(tmp_path),
		description="adopt-test",
		session_id="sess-adopt-test",
	)
	assert bridged is not None
	job_id, err = bridged
	assert job_id, err
	reg = get_job_registry()
	deadline = time.time() + 20
	status = "running"
	while time.time() < deadline:
		_文本, _cur, status, _trunc = reg.read(job_id, "sess-adopt-test")
		if status in ("succeeded", "failed", "killed"):
			break
		time.sleep(0.2)
	assert status == "succeeded"


# ---- pwsh7 内置引导器 ----

def test_pwsh7_parse_hashes() -> None:
	from tools.bash_tool.pwsh7 import PINNED_VERSION, _parse_hashes_txt

	zip_name = f"PowerShell-{PINNED_VERSION}-win-x64.zip"
	digest = "a" * 64
	text = f"{digest}  {zip_name}\n{'b' * 64}  other.zip\n"
	assert _parse_hashes_txt(text, zip_name) == digest
	assert _parse_hashes_txt(text, "missing.zip") is None
	assert _parse_hashes_txt("short  bad", zip_name) is None


def test_pwsh7_zip_slip_blocked(tmp_path: Path) -> None:
	from tools.bash_tool.pwsh7 import _extract_zip_safe

	zip_path = tmp_path / "evil.zip"
	dest = tmp_path / "dest"
	dest.mkdir()
	with zipfile.ZipFile(zip_path, "w") as zf:
		zf.writestr("pwsh.exe", "fake")
		zf.writestr("../evil.txt", "nope")
	written = _extract_zip_safe(zip_path, dest)
	assert "pwsh.exe" in written
	assert not (tmp_path / "evil.txt").exists()
	assert (dest / "pwsh.exe").is_file()


def test_pwsh7_install_hash_mismatch(tmp_path: Path) -> None:
	import pytest

	from tools.bash_tool.pwsh7 import install_from_zip

	zip_path = tmp_path / "pwsh.zip"
	with zipfile.ZipFile(zip_path, "w") as zf:
		zf.writestr("pwsh.exe", "fake")
	with pytest.raises(ValueError, match="hash mismatch"):
		install_from_zip(zip_path, expected_sha256="0" * 64)


def test_pwsh7_locate_non_windows_or_none() -> None:
	from tools.bash_tool.pwsh7 import locate

	if os.name != "nt":
		assert locate() is None
	# Windows：不设 env、无缓存、无 PATH → 允许 None（落回 5.1），不允许抛
	else:
		locate()  # smoke
