"""Bash 读证据：``missing_read`` 的第三种事实 + 弱基线（默认关的旁路）。

事故形态（2026-10-08 本会话）：用 Bash 读了文件（Get-Content）后 Edit 被拒，
报错只有一句"没读过"——模型无法判断该重读同段、从头读、还是先 Read 一次。

方向性都钉：
- 从没读过 / 基线被淘汰 / 只在 Bash 里读过 ⇒ 三种措辞分开；
- 只有"整文件读 + 输出未截断"才算证据（``cat a.py | head`` 不算）；
- 弱基线**默认关**：开关开才放行，且 mtime 变了即失效（弱基线不得变成"陈旧内容通行证"）。
"""

from __future__ import annotations

from tools.bash_tool.read_evidence import paths_in_output, whole_file_read_paths
from tools.fileio.read_state import (
	bash_baseline_hash,
	bash_read_evidence,
	missing_read_detail,
	record_bash_read,
)

_ENV = "XEYO_READ_BASELINE_BASH_EVIDENCE"


def _mtime_ms(path) -> int:
	return int(path.stat().st_mtime * 1000)


def test_never_read_detail(tmp_path) -> None:
	assert missing_read_detail(str(tmp_path / "a.py")) == "never read in this session"


def test_bash_evidence_is_reported_as_third_state(tmp_path) -> None:
	p = tmp_path / "a.py"
	p.write_text("x\n" * 5, encoding="utf-8")
	record_bash_read(str(p), mtime_ms=_mtime_ms(p), whole_file=True, lines=5)
	detail = missing_read_detail(str(p))
	assert "bash read on record" in detail
	assert "full file" in detail and "5 lines" in detail


def test_truncated_bash_read_is_not_a_baseline(tmp_path, monkeypatch) -> None:
	p = tmp_path / "a.py"
	p.write_text("x\n" * 50, encoding="utf-8")
	record_bash_read(str(p), mtime_ms=_mtime_ms(p), whole_file=False, lines=3)
	monkeypatch.setenv(_ENV, "1")
	assert bash_baseline_hash(str(p)) == ""
	assert "truncated output" in missing_read_detail(str(p))


def test_full_file_bash_read_is_a_baseline_only_when_switch_on(tmp_path, monkeypatch) -> None:
	p = tmp_path / "a.py"
	p.write_text("hello\n", encoding="utf-8")
	record_bash_read(str(p), mtime_ms=_mtime_ms(p), whole_file=True, lines=1)
	monkeypatch.delenv(_ENV, raising=False)
	assert bash_baseline_hash(str(p)) == ""
	monkeypatch.setenv(_ENV, "1")
	assert bash_baseline_hash(str(p)).startswith("sha256:")


def test_mtime_change_voids_the_weak_baseline(tmp_path, monkeypatch) -> None:
	p = tmp_path / "a.py"
	p.write_text("hello\n", encoding="utf-8")
	record_bash_read(str(p), mtime_ms=_mtime_ms(p) - 5_000, whole_file=True, lines=1)
	monkeypatch.setenv(_ENV, "1")
	assert bash_baseline_hash(str(p)) == ""


def test_evidence_registry_roundtrip(tmp_path) -> None:
	p = tmp_path / "a.py"
	p.write_text("hello\n", encoding="utf-8")
	assert bash_read_evidence(str(p)) is None
	record_bash_read(str(p), mtime_ms=_mtime_ms(p), whole_file=True, lines=1)
	row = bash_read_evidence(str(p))
	assert row is not None and row["whole_file"] is True and row["lines"] == 1


def test_detector_accepts_only_simple_whole_file_reads(tmp_path) -> None:
	cwd = str(tmp_path)
	expected = [str(tmp_path / "a.py")]
	assert whole_file_read_paths("cat a.py", cwd=cwd) == expected
	assert whole_file_read_paths("Get-Content a.py", cwd=cwd) == expected
	assert whole_file_read_paths("type a.py", cwd=cwd) == expected
	# 管道 / 重定向 / 串联 / 只抽局部的命令：不保证看到全文
	assert whole_file_read_paths("cat a.py | head -40", cwd=cwd) == []
	assert whole_file_read_paths("cat a.py > b.py", cwd=cwd) == []
	assert whole_file_read_paths("rg x a.py", cwd=cwd) == []
	assert whole_file_read_paths("cat *.py", cwd=cwd) == []


def test_truncated_output_is_not_evidence(tmp_path) -> None:
	assert paths_in_output(
		"cat a.py", cwd=str(tmp_path), content="x\n[output truncated, full at /tmp/x]"
	) == []
	assert paths_in_output("cat a.py", cwd=str(tmp_path), content="x\n") == [
		str(tmp_path / "a.py")
	]
