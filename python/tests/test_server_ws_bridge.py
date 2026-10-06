"""`server/__main__.py` 启动桥的工作区解析回归（2026-10-05 "R3/R4 从未生效" 事故）。

事故形态：`.env` 给 `XEYO_CWD=.`，服务进程 cwd 被 pushd 到 `python/`，旧代码把 "."
原样交给 `apply_to_environ` ⇒ 工作区 settings 解析成 `python/.xeyo/settings.json`（不存在）
⇒ 桥只合并 home 段 ⇒ R3/R4 等**工作区级开关静默失效**（活后端 `GET /v1/settings/memory`
实测两键 source=default 即此形态）。

本文件钉两件事：
1. 正向：`.`（从 python/ cwd 解析）必须回退到仓库根——即 `resolve_bridge_workspace`。
2. 反向守卫：结果既不许是裸"."、也不许落在 python 包根内（旧形态会给出这两个之一）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.__main__ import resolve_bridge_workspace

PY_DIR = Path(__file__).resolve().parents[1]      # python/
REPO_DIR = Path(__file__).resolve().parents[2]    # 仓库根


def test_dot_from_python_cwd_falls_back_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
	"""事故判别子：cwd=python/ + XEYO_CWD=. ⇒ 必须解析回仓库根。"""
	monkeypatch.chdir(PY_DIR)
	res = resolve_bridge_workspace(".")
	assert res == os.path.realpath(str(REPO_DIR)), f"未回退到仓库根: {res!r}"
	# 反向守卫：旧裸读形态给出的两个值都不许出现
	assert res not in (".", str(PY_DIR), os.path.realpath(str(PY_DIR)))


def test_absolute_workspace_passes_through(tmp_path: Path) -> None:
	res = resolve_bridge_workspace(str(tmp_path))
	assert res == os.path.realpath(str(tmp_path))


def test_blank_or_unset_means_home_level(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_CWD", raising=False)
	assert resolve_bridge_workspace("") is None
	assert resolve_bridge_workspace(None) is None


def test_nonexistent_path_means_home_level(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.chdir(PY_DIR)
	assert resolve_bridge_workspace("./__no_such_dir_9f2c__") is None


def test_reading_env_when_raw_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.chdir(PY_DIR)
	monkeypatch.setenv("XEYO_CWD", ".")
	res = resolve_bridge_workspace()
	assert res == os.path.realpath(str(REPO_DIR))


def test_premise_naive_resolution_lands_in_package_root(monkeypatch: pytest.MonkeyPatch) -> None:
	"""事故前提钉：裸解析（无回退）会把 "." 解到 python/ 包根。

	这证明"naive 读法为何必错"，也防环境漂移（如 package 根探测失效）让判别子静默失真。
	"""
	from session.workspace_path import is_python_package_root, resolve_physical_cwd

	monkeypatch.chdir(PY_DIR)
	naive = resolve_physical_cwd(".")
	assert os.path.realpath(naive) == os.path.realpath(str(PY_DIR))
	assert is_python_package_root(naive) is True
