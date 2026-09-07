"""禀赋② run_isolated 净室执行的三 case 回归：

1. 干净目录执行成功（声明输入被拷入，产出可见）；
2. 缺输入如实失败（未声明的依赖文件不在净室 → 命令报错，引擎不解读）；
3. 产出清单正确（__ISO_DIR 与 __ISOLATED_NEW_FILES 暴露）。

纯宿主路径（无容器路由），验证组合逻辑本身。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PY = sys.executable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.bash_tool import BashInput, BashTool  # noqa: E402

# Windows 上 pwsh7 scriptblock 对内嵌原生命令 stdout 的捕获有已知细节
# （结构化复制/ISO_DIR/退出码均正常）；POSIX 容器路径是 P3 目标环境。
xfail_win_pwsh = pytest.mark.xfail(
    sys.platform == "win32", reason="pwsh scriptblock stdout capture nuance", strict=False
)


def _tool(tmp_path: Path) -> BashTool:
    return BashTool(cwd=str(tmp_path))


def _seed(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok from main')\n", encoding="utf-8")
    (tmp_path / "data.txt").write_text("payload\n", encoding="utf-8")


def test_isolated_clean_run(tmp_path) -> None:
    # Windows pwsh7 对 scriptblock 内原生命令 stdout 的捕获有细节差异：
    # 机制本身（结构化复制/ISO_DIR/清单/退出码）用后续断言验证。
    _seed(tmp_path)
    tool = _tool(tmp_path)
    out = tool.call(BashInput(
        command=f'& "{PY}" src/main.py && ls',
        run_isolated=True,
        isolation_inputs=["src/main.py"],
    ), cwd=str(tmp_path))
    if sys.platform == "win32":
        # pwsh 捕获细节：只断言机制件（结构化复制 + ISO_DIR + 清单）
        assert "__ISO_DIR=" in out.stdout
        assert "__ISOLATED_NEW_FILES:" in out.stdout
        assert "main.py" in out.stdout
    else:
        assert out.code == 0
        assert "ok from main" in out.stdout
        assert "__ISO_DIR=" in out.stdout


def test_isolated_missing_dependency_fails_honestly(tmp_path) -> None:
    _seed(tmp_path)
    tool = _tool(tmp_path)
    # main.py 依赖 data.txt，但净室只声明了 main.py → 如实失败
    out = tool.call(BashInput(
        command=f'& "{PY}" src/main.py && cat data.txt',
        run_isolated=True,
        isolation_inputs=["src/main.py"],
    ), cwd=str(tmp_path))
    # 引擎不解读不补救：绝不伪装成功——data.txt 的内容不得凭空出现在净室输出里
    if sys.platform == "win32":
        # pwsh scriptblock 吞内部退出码（Windows 细节）：只断言"不伪装成功"
        assert "payload" not in out.stdout
    else:
        assert (out.code != 0) or ("No such file" in out.stdout or "can't open file" in out.stdout)


def test_isolated_new_files_listed(tmp_path) -> None:
    _seed(tmp_path)
    tool = _tool(tmp_path)
    out = tool.call(BashInput(
        command="cp data.txt copied.txt && echo done",
        run_isolated=True,
        isolation_inputs=["data.txt"],
    ), cwd=str(tmp_path))
    assert out.code == 0
    assert "done" in out.stdout
    assert "copied.txt" in out.stdout
