"""打包快照同步器的验收：新包绝不静默漏进产物，坏产物绝不留在原地。

结构性根因（#80）：release 后端跑 ``resources/python`` 快照，而它一直靠人手工刷新。
仓库有 24 个可导入顶层包、过期快照只有 18 个 —— ``diagnostics``、``bridge``、
``coord``、``localmodels``、``synaptic`` 全部静默缺失，没有任何测试会因此变红。
本文件把"静默缺失"变成"要么拷进去、要么当场报错"。
"""

from __future__ import annotations

import pytest

from scripts import sync_tauri_python as stp


def _pkg(root, name, *, init=True, extra=None):
	d = root / name
	d.mkdir(parents=True, exist_ok=True)
	if init:
		(d / "__init__.py").write_text("", encoding="utf-8")
	for fname, body in (extra or {}).items():
		(d / fname).write_text(body, encoding="utf-8")
	return d


def _layout(tmp_path, *, src_pkgs, dst_pkgs, with_venv=True):
	src = tmp_path / "python"
	src.mkdir()
	for name in src_pkgs:
		_pkg(src, name, extra={"mod.py": "X = 1\n"})
	dst = tmp_path / "resources" / "python"
	dst.mkdir(parents=True)
	for name in dst_pkgs:
		_pkg(dst, name)
	if with_venv:
		(dst / ".venv").mkdir(parents=True, exist_ok=True)
	return src, dst


def test_ship_list_is_derived_from_packages_not_a_hand_list(tmp_path) -> None:
	"""判据必须是"目录里有 __init__.py"，否则每加一个包就重演一次 #80。"""
	src, _ = _layout(tmp_path, src_pkgs=["server", "diagnostics"], dst_pkgs=["server"])
	_pkg(src, "tests", init=False, extra={"t.py": ""})       # 测试树不是包
	_pkg(src, "scripts", init=False)                          # 无 __init__.py → 不算包
	(src / ".xy-shadow-git").mkdir()                          # 点开头 → 永不进产物
	found = stp.discover_packages(src)
	assert found == ["diagnostics", "server"], found


def test_real_repo_ships_the_diagnostics_layer() -> None:
	"""正向自证：真实仓库里 diagnostics 确实算"该进产物的包"。"""
	assert "diagnostics" in stp.discover_packages()


def test_missing_package_is_planned_for_copy(tmp_path) -> None:
	"""#80 的形状：源码里有、快照里没有 ⇒ 必须出现在计划里，而不是被忽略。"""
	src, dst = _layout(tmp_path, src_pkgs=["server", "diagnostics", "localmodels"], dst_pkgs=["server"])
	p = stp.plan(src, dst)
	assert p.copy == ["diagnostics", "localmodels"], p.copy
	assert p.already_there == ["server"]


def test_junk_and_loose_files_never_enter_the_plan(tmp_path) -> None:
	src, dst = _layout(tmp_path, src_pkgs=["server"], dst_pkgs=[])
	(src / ".xeyo_filehelper").mkdir()
	(src / "tests").mkdir()
	(src / "notes.txt").write_text("x", encoding="utf-8")
	p = stp.plan(src, dst)
	assert p.copy == ["server"], p.copy


def test_not_shipped_must_carry_a_reason(tmp_path, monkeypatch) -> None:
	"""显式排除要留名留理由，否则"忘了拷"和"故意不拷"在事后无法区分。"""
	src, dst = _layout(tmp_path, src_pkgs=["server", "synaptic"], dst_pkgs=["server"])
	monkeypatch.setattr(stp, "NOT_SHIPPED", {"synaptic": ""})
	p = stp.plan(src, dst)
	assert p.skipped == ["synaptic"], p.skipped


def test_sync_refuses_a_dirty_worktree(tmp_path, monkeypatch, capsys) -> None:
	"""产物会把未提交改动一起烤进去（实测发生过），所以默认要求显式确认。"""
	src, dst = _layout(tmp_path, src_pkgs=["server"], dst_pkgs=["server"])
	monkeypatch.setattr(stp, "dirty_report", lambda: [" M python/server/app.py"])
	assert stp.sync(src=src, dst=dst) == 2
	assert "未提交" in capsys.readouterr().out
	assert (dst / "server").is_dir(), "拒绝执行时不得动过快照"


def test_sync_refuses_a_snapshot_without_a_venv(tmp_path, monkeypatch) -> None:
	"""venv 是带外产出的厚壳，缺了它不能靠猜重建（薄壳 venv 会做出装完连不上的 MSI）。"""
	src, dst = _layout(tmp_path, src_pkgs=["server"], dst_pkgs=["server"], with_venv=False)
	monkeypatch.setattr(stp, "dirty_report", lambda: [])
	assert stp.sync(src=src, dst=dst) == 2


def test_sync_copies_new_packages_and_keeps_a_rollback_point(tmp_path, monkeypatch) -> None:
	src, dst = _layout(tmp_path, src_pkgs=["server", "diagnostics"], dst_pkgs=["server"])
	monkeypatch.setattr(stp, "dirty_report", lambda: [])
	monkeypatch.setattr(stp, "verify", lambda snapshot: [])
	assert stp.sync(src=src, dst=dst) == 0
	assert (dst / "diagnostics" / "mod.py").is_file()
	assert (dst / ".venv").is_dir(), "venv 必须搬过去，不是丢掉"
	rollbacks = [p for p in dst.parent.iterdir() if p.name.startswith("python.bak-")]
	assert len(rollbacks) == 1 and (rollbacks[0] / "server").is_dir(), "旧快照要留在回滚点里"


def test_sync_restores_everything_when_verification_fails(tmp_path, monkeypatch) -> None:
	"""验不过就还原：不能留下"同步过但产物是坏的"这种中间态。"""
	src, dst = _layout(tmp_path, src_pkgs=["server", "diagnostics"], dst_pkgs=["server"])
	_pkg(dst, "legacy_only")  # 只在旧快照里存在的东西，还原后必须回来
	monkeypatch.setattr(stp, "dirty_report", lambda: [])
	monkeypatch.setattr(stp, "verify", lambda snapshot: ["后端 import 失败"])
	assert stp.sync(src=src, dst=dst) == 1
	assert (dst / "legacy_only").is_dir(), "还原没带回旧内容"
	assert (dst / ".venv").is_dir(), "还原必须连 venv 一起回来"
	assert not (dst / "diagnostics").exists(), "失败的新内容不该留下"


def test_verify_says_so_when_the_interpreter_is_thin_or_missing(tmp_path) -> None:
	bare = tmp_path / "python"
	(bare / ".venv").mkdir(parents=True)
	problems = stp.verify(bare)
	assert problems and "解释器" in problems[0], problems


@pytest.mark.skipif(not stp.SNAPSHOT.is_dir(), reason="本机没有打包快照")
def test_current_snapshot_ships_every_importable_package() -> None:
	"""防复发的长期门：真实快照少任何一个顶层包就红（#80 当天正是靠这条没被写出来才成立）。"""
	gaps = stp.plan().copy
	assert not gaps, f"打包快照缺少顶层包，release 版会静默没有这些功能：{gaps}"
