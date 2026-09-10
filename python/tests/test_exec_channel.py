"""D1 观测域一致性：`tools/exec_channel.py` 单测 + 收益测量。

纪律（本文件锁死）：
1. **宿主路径字节级等价**——未设路由时与 os/pathlib 同结果；
2. **不可观测即沉默**——None 不退化、不猜测、不编造"不存在"；
3. **收益可量化**——修复前后的误导事实条数（1 → 0）与注入内容正确性。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import first_sniff  # noqa: E402
from tools import exec_channel  # noqa: E402
from tools.todo_write_tool.todo_write_tool import TodoWriteTool  # noqa: E402
from tools.todo_write_tool.types import TodoItem  # noqa: E402


def _item(content: str, status: str, output: str = "") -> TodoItem:
	return TodoItem(
		id=f"id-{abs(hash(content)) % 10000}",
		content=content,
		status=status,  # type: ignore[arg-type]
		active_form=f"doing {content}",
		output=output,
	)


def _as_container(monkeypatch, probe) -> None:
	monkeypatch.setattr(exec_channel, "active_container", lambda: "cid-test")
	monkeypatch.setattr(exec_channel, "_probe", probe)


# ---------------------------------------------------------------- 宿主等价


def test_host_stat_matches_pathlib(tmp_path):
	file = tmp_path / "a.txt"
	file.write_bytes(b"12345")
	assert exec_channel.stat_path(str(file)) == (True, 5)
	assert exec_channel.stat_path(str(tmp_path / "nope.txt")) == (False, 0)
	assert exec_channel.stat_path(str(tmp_path)) == (False, 0)  # 目录不是普通文件


def test_host_list_dir_kinds(tmp_path):
	(tmp_path / "d").mkdir()
	(tmp_path / "f.txt").write_text("x", encoding="utf-8")
	entries = exec_channel.list_dir(str(tmp_path))
	assert entries is not None
	kinds = dict(entries)
	assert kinds.get("d") == "d" and kinds.get("f.txt") == "f"


def test_host_read_text_and_missing(tmp_path):
	file = tmp_path / "r.txt"
	file.write_text("hello-channel", encoding="utf-8")
	assert exec_channel.read_text(str(file)) == "hello-channel"
	assert exec_channel.read_text(str(tmp_path / "nope")) is None


def test_host_list_dir_missing_returns_none(tmp_path):
	assert exec_channel.list_dir(str(tmp_path / "absent")) is None


# ---------------------------------------------------------------- 容器通道


def test_container_stat_three_verdicts(monkeypatch):
	_as_container(monkeypatch, lambda *a, **k: (0, "M\n"))
	assert exec_channel.stat_path("/app/x") == (False, 0)
	_as_container(monkeypatch, lambda *a, **k: (0, "F 4096\n"))
	assert exec_channel.stat_path("/app/x") == (True, 4096)
	_as_container(monkeypatch, lambda *a, **k: (0, "D\n"))
	assert exec_channel.stat_path("/app/x") == (False, 0)


def test_container_unobservable_is_none(monkeypatch):
	_as_container(monkeypatch, lambda *a, **k: None)
	assert exec_channel.stat_path("/app/x") is None
	assert exec_channel.list_dir("/app") is None
	assert exec_channel.read_text("/app/x") is None
	_as_container(monkeypatch, lambda *a, **k: (1, "bash: docker: not found"))
	assert exec_channel.stat_path("/app/x") is None


def test_container_list_dir_parses_find_output(monkeypatch):
	_as_container(
		monkeypatch,
		lambda *a, **k: (0, "f\tmain.py\nd\ttests\nl\tlink\n?\tweird\n"),
	)
	entries = exec_channel.list_dir("/app")
	assert entries is not None
	assert dict(entries) == {
		"main.py": "f",
		"tests": "d",
		"link": "l",
		"weird": "?",
	}


def test_container_model_workspace_uses_container_pwd(monkeypatch):
	def fake_probe(_cid, command, timeout_s=exec_channel.PROBE_TIMEOUT_S):
		if command.strip() == "pwd":
			return (0, "/app\n")
		return (0, "f\tmain.py\n")

	_as_container(monkeypatch, fake_probe)
	display, entries = exec_channel.model_workspace("C:/host/scratch")
	assert display == "/app"
	assert entries == [("main.py", "f")]


# ---------------------------------------------------------------- 收益测量


def test_benefit_todo_misleading_fact_eliminated(tmp_path, monkeypatch):
	"""收益：容器路由下产物真实存在时，误导性"不存在"断言 1 条 → 0 条。"""

	cwd = tmp_path / "ws"
	cwd.mkdir()
	# 旧实现（宿主 Path）的判定：容器内真实存在的 /app/out.json 在宿主看不到
	old_verdict = Path(str(cwd)).joinpath("/app/out.json").exists()
	assert old_verdict is False  # ← 修复前会据此输出"磁盘上不存在"

	_as_container(monkeypatch, lambda *a, **k: (0, "F 4096\n"))
	tool = TodoWriteTool(cwd=str(cwd))
	text = tool._materialization_facts(
		[_item("write result", "completed", "/app/out.json")]
	)
	assert "已存在（4096 B）" in text
	assert "不存在" not in text


def test_benefit_todo_silent_when_unobservable(tmp_path, monkeypatch):
	"""收益：观测不可用时沉默——不注入任何断言（而不是编造一条错误事实）。"""

	cwd = tmp_path / "ws"
	cwd.mkdir()
	_as_container(monkeypatch, lambda *a, **k: None)
	tool = TodoWriteTool(cwd=str(cwd))
	text = tool._materialization_facts(
		[_item("write result", "completed", "/app/out.json")]
	)
	assert text == ""


def test_benefit_first_sniff_stops_injecting_host_scratch(tmp_path, monkeypatch):
	"""收益：容器路由下不再注入宿主空 scratch 的"(空目录)"，改注入容器工作面。

	修复前（旧实现）在容器路由下注入 `cwd: <宿主 scratch>` + `(空目录)`——
	模型看不到那份清单，是纯误导。修复后注入的是容器 pwd 与容器内真实条目。
	"""

	cwd = tmp_path / "ws"
	cwd.mkdir()  # 宿主 scratch 为空（评测/容器场景的常态）

	old_text = first_sniff.build_first_sniff_text(str(cwd))
	assert "(空目录)" in old_text and str(cwd) in old_text  # 宿主路由下这是真的

	def fake_probe(_cid, command, timeout_s=exec_channel.PROBE_TIMEOUT_S):
		if command.strip() == "pwd":
			return (0, "/app\n")
		return (0, "f\tmain.py\nd\ttests\nf\tREADME.md\n")

	_as_container(monkeypatch, fake_probe)
	text = first_sniff.build_first_sniff_text(str(cwd))
	assert "cwd: /app" in text
	assert "main.py" in text and "tests/" in text
	assert "(空目录)" not in text
	assert str(cwd) not in text


def test_benefit_first_sniff_silent_when_unobservable(tmp_path, monkeypatch):
	cwd = tmp_path / "ws"
	cwd.mkdir()
	_as_container(monkeypatch, lambda *a, **k: None)
	assert first_sniff.build_first_sniff_text(str(cwd)) == ""


def test_no_route_branch_in_source():
	"""红线自查：信息正确性路径不得出现评测/容器特判分支。"""

	source = Path(exec_channel.__file__).read_text(encoding="utf-8")
	assert "BENCH_MINIMAL" not in source
	assert "is_benchmark" not in source
