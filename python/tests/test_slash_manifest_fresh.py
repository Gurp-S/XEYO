"""slash manifest 的新鲜度必须由 pytest 执法，不能只写在 AGENTS.md 里。

事实：``slash/export_manifest.py::main()`` 早就实现了 ``--check``（漂移返回退出码 1），
但**没有任何一档门跑它**——提交门是 tsc+vitest+pytest，所以这条"改 registry 后重跑导出"
的规矩只靠人记。记漏一次的后果是确定性的：GUI 的 Composer 补全与 TUI 的 typeahead
会展示后端没有的命令（或藏起新命令），用户敲下去才收到"unknown command"。

本文件不新生成任何东西：只把 ``_render()`` 与两处已提交的 TS 逐字比对，
并证明"确实会报漂移"（否则这条门是装饰）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slash import export_manifest as em  # noqa: E402


def _committed_pairs() -> list[tuple[Path, str]]:
    return [(path, surface) for path, surface in em._OUTPUTS]


def test_manifest_files_exist() -> None:
    """前置自证：比对不能对着空气比。"""
    pairs = _committed_pairs()
    assert pairs, "export_manifest._OUTPUTS 空了"
    for path, _surface in pairs:
        assert path.is_file(), f"生成的 manifest 不在册：{path}"


def test_committed_manifests_match_registry() -> None:
    """核心门：两处 TS 必须与 registry 渲染结果逐字一致。"""
    code = em._render()
    stale = [
        str(path)
        for path, _surface in _committed_pairs()
        if path.read_text(encoding="utf-8") != code
    ]
    assert not stale, (
        "slash manifest 已过期，重跑：py -3.11 -m slash.export_manifest\n过期文件：" + "; ".join(stale)
    )


def test_check_mode_exits_zero_when_in_sync(tmp_path: Path, capsys) -> None:
    """`--check` 在当前头必须是 0（否则本档一上线就假红）。"""
    monkey_ok = importlib.import_module("slash.export_manifest")
    argv = sys.argv
    sys.argv = ["export_manifest", "--check"]
    try:
        rc = monkey_ok.main()
    finally:
        sys.argv = argv
    assert rc == 0, capsys.readouterr().out


def test_check_mode_detects_drift(tmp_path: Path, monkeypatch, capsys) -> None:
    """牙齿证明：把产物指到一份"少一条命令"的副本，--check 必须报漂移并退 1。"""
    good = em._render()
    doctored = good.replace('name: "help"', 'name: "help_RENAMED"', 1)
    assert doctored != good, "夹具没改动到内容"
    stale_dir = tmp_path / "gen"
    stale_dir.mkdir()
    for name in ("gui.ts", "tui.ts"):
        (stale_dir / name).write_text(doctored, encoding="utf-8")
    monkeypatch.setattr(
        em, "_OUTPUTS", ((stale_dir / "gui.ts", "gui"), (stale_dir / "tui.ts", "tui"))
    )
    argv = sys.argv
    sys.argv = ["export_manifest", "--check"]
    try:
        rc = em.main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "drift" in out, out
    # 不许顺手写盘：--check 只报告
    assert (stale_dir / "gui.ts").read_text(encoding="utf-8") == doctored


def test_render_is_deterministic() -> None:
    """同一次调用两次渲染必须逐字相同（否则比对本身不可信）。"""
    assert em._render() == em._render()


@pytest.mark.parametrize("needle", ["export const SURFACES", "export const slashCommands"])
def test_render_contains_both_tables(needle: str) -> None:
    assert needle in em._render()
