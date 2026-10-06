"""shell 身份行里的正典解释器事实（首个成功 Bash 结果，一次/会话）。

现场（sess_musrbw08_n9tly2）：解释器有两个——模型用 ``py -3.11``，项目脚本头注
写 ``.venv\\Scripts\\python.exe``——"哪个是正典、依赖装在哪边"在模型面上没有答案。
"""

from __future__ import annotations

import os

from tools.bash_tool.bash_tool import BashTool


def _venv_rel() -> str:
	return (
		os.path.join(".venv", "Scripts", "python.exe")
		if os.name == "nt"
		else os.path.join(".venv", "bin", "python")
	)


def test_venv_fact_line_reports_canonical_python(tmp_path):
	rel = _venv_rel()
	p = tmp_path / rel
	p.parent.mkdir(parents=True)
	p.write_text("x", encoding="utf-8")
	line = BashTool(cwd=str(tmp_path))._venv_fact_line()
	assert line == f" [python: {rel.replace(os.sep, '/')}]"


def test_venv_fact_line_absent_without_venv(tmp_path):
	assert BashTool(cwd=str(tmp_path))._venv_fact_line() == ""
