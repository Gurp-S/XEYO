"""`evals/bash_write_probe.write_targets` 的形状夹具。

这个判据决定问答集 A1–A3 有没有分母（容器任务的改盘全走 bash 重定向），所以它的
**假阳性与假阴性一样要钉住**：把 `sed -n '10,20p' f` 判成写，会污染文件状态表的
写序列；把 `cat > f <<EOF` 判成非写，A 组就又回到 0/0。
"""

from __future__ import annotations

import pytest

from evals.bash_write_probe import write_targets

# (命令, 期望被写路径) —— 全部取自两条真实语料里踩过的形状。
CASES: list[tuple[str, tuple[str, ...]]] = [
	# ① 基本重定向
	("echo hi > out.txt", ("out.txt",)),
	("echo hi >> out.txt", ("out.txt",)),
	("cd /app && cat > a.py <<'EOF'\nprint(1)\nEOF", ("a.py",)),
	("cat > /tmp/dt/harness2.py <<'PYEOF'\nROOT=\"/tmp/dt2\"\nPYEOF", ("/tmp/dt/harness2.py",)),
	("printf 'x' > b.txt && printf 'y' >> c.txt", ("b.txt", "c.txt")),
	# ② 多重定向 + heredoc 之后再写（必须都抓到，不能只取第一个）
	("cat > f <<EOF\nline\nEOF\necho done > g", ("f", "g")),
	# ③ 不改盘的形状（假阳性护栏）
	("ls /nope 2>/dev/null", ()),
	("cat x | grep y > /dev/null", ()),
	("command 2>&1", ()),
	("pwsh -Command 'Write-Host 1' > $null", ()),
	# ④ 正文里的 `>` 不是重定向（这一族把纯正则方案打爆过）
	("sed -i '28d' p4.cbl", ()),
	("sed -n '470,520p' /app/convert_masks.py", ()),
	("python3 -c \"f = 1 if x > 0 else 0; print(f)\"", ()),
	("$html = @'\n<!doctype html>\n<html lang=\"zh-CN\">\n<svg><path d='M0 0h24'/>\n'@\nSet-Content -Path $html -Value 1", ()),
	("cat > f <<'EOF'\n@'noise'\nEOF", ("f",)),
	("# note: use > to redirect\ntrue", ()),
	# ⑤ 静态判不出的目标 ⇒ 不猜（宁可漏，不可错）
	("cat x > $out", ()),
	("cat x > ${BUILD}/f.txt", ()),
	("cat x > %TEMP%\\f.txt", ()),
]


@pytest.mark.parametrize("command,expected", CASES, ids=[c[0][:34] for c in CASES])
def test_write_targets_shapes(command: str, expected: tuple[str, ...]) -> None:
	assert write_targets(command) == expected, command


def test_non_string_and_empty_are_silent() -> None:
	for bad in (None, 3, "", "   "):
		assert write_targets(bad) == ()


def test_probe_is_off_by_default_in_the_algorithm_layer() -> None:
	"""未注册时 WSC 必须逐字节维持现行为（旁路上线，不是默认开启）。"""
	from synaptic import textutil
	from synaptic.textutil import classify_tool

	assert textutil._BASH_WRITE_PROBE is not write_targets  # 默认槽不由本模块常驻占用
	textutil.set_bash_write_probe(write_targets)
	try:
		assert classify_tool("Bash", {"command": "cat > f\nEOF\n"})[0] is True
	finally:
		textutil.set_bash_write_probe(None)
		assert classify_tool("Bash", {"command": "cat > f"})[0] is False
		assert classify_tool("Bash", {"command": "cat /etc/hosts"})[0] is False
