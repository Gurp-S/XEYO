"""工作区 settings 的**通路**守卫：入口必须发布工作区，否则工作区级开关静默失效。

事故形态（2026-09-21 实测）：``settings.json`` 是 home + workspace 分层合并的，但
下游读配置时拿不到入口的 ``--cwd``，只能读 ``XEYO_CWD``；而全仓**只有** ``cli serve``
会设那个变量（``433`` 个读取点里也只有 1 个显式传 ``cwd``）。于是：

- 走 GUI / TUI（连 server）→ 你在项目里打开的开关生效；
- 走 ``cli chat`` / ``attach`` / ``coord`` / 脚本 / 评测 → 同一份设置**读不到**，
  静默回落 home/默认，界面上还显示"已设置"。

典型牺牲品就是 ``XEYO_WSC``：注册表注释直接教用户
``save({"XEYO_WSC": "1"}, cwd=<工作区>)`` 切换 WSC 生产档——那条指令在非 serve 入口下
从来不成立。本文件把「发布 → 读到」这条链钉死，防的就是以后有人把发布删了。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_KEY = "XEYO_WSC"  # 默认 "0"；工作区写 "1" 后必须被读到


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
	"""隔离 XEYO_HOME 并清空 XEYO_CWD：绝不碰开发者真实配置。

	整份 ``os.environ`` 进出快照。原因不是洁癖：本文件的桥接测试要让
	``apply_to_environ`` 把 ``XEYO_WSC`` **真写进进程环境**（那正是被测行为），
	而 monkeypatch 只还原它自己 set 过的键 ⇒ 开关泄漏给同进程后面的测试。
	实测泄漏后 ``tests/test_runtime_c2.py`` 三条红（C2 被路由进 WSC 活投影，
	``c2_summary_text`` 变空）。
	"""
	snapshot = dict(os.environ)
	home = tmp_path / "home"
	(home / ".xeyo").mkdir(parents=True)
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.delenv("XEYO_CWD", raising=False)
	ws = tmp_path / "ws"
	(ws / ".xeyo").mkdir(parents=True)
	yield home, ws
	os.environ.clear()
	os.environ.update(snapshot)


def _write_ws(ws: Path, value: str) -> None:
	(ws / ".xeyo" / "settings.json").write_text(
		json.dumps({"memory": {_KEY: value}}), encoding="utf-8"
	)


def _get():
	from memory.memory_switches import get_value

	return get_value(_KEY)  # **故意不传 cwd**：只靠入口发布的信道


def test_resolve_cwd_publishes_workspace(_isolate) -> None:
	"""入口解析出工作区后必须广播它——这是整条链唯一的支点。"""
	_, ws = _isolate
	from cli.cwdutil import resolve_cwd

	assert resolve_cwd(str(ws)) == os.path.realpath(os.path.abspath(str(ws)))
	assert (os.environ.get("XEYO_CWD") or "").strip(), "resolve_cwd 没有发布 XEYO_CWD"


def test_workspace_switch_visible_after_publish(_isolate) -> None:
	"""发布之后，不传 cwd 的读取必须看到工作区值（而不是默认值）。"""
	_, ws = _isolate
	from cli.cwdutil import resolve_cwd

	_write_ws(ws, "1")
	resolve_cwd(str(ws))
	assert _get() == "1", "入口已发布工作区，开关仍读不到 ⇒ 通路断在下游"


def test_unpublished_workspace_switch_is_invisible(_isolate) -> None:
	"""反面对照：不发布就读不到。这条不是"期望行为"，是把危害显式钉住——
	它保证「发布」这一步被删掉时测试会红，而不是让危害重新变成静默的。
	"""
	_, ws = _isolate
	_write_ws(ws, "1")
	assert _get() == "0", "未发布时竟能读到工作区值 ⇒ 解析规则又被抄了一份"


def test_workspace_wins_over_home(_isolate) -> None:
	"""分层合并的方向（workspace 更具体者优先）在两值冲突时必须成立。"""
	home, ws = _isolate
	from cli.cwdutil import resolve_cwd

	(home / ".xeyo" / "settings.json").write_text(
		json.dumps({"memory": {_KEY: "0"}}), encoding="utf-8"
	)
	_write_ws(ws, "1")
	resolve_cwd(str(ws))  # 合并方向的前提：两个文件都在解析范围内
	assert _get() == "1"


def test_private_resolvers_forward_the_single_rule(_isolate) -> None:
	"""各消费方不得再抄一份解析规则，必须转发到 ``extension.config``。"""
	from extension.config import resolve_workspace_cwd
	from localmodels.config import _resolve_cwd as lm
	from memory.memory_switches import _resolve_cwd as ms

	_, ws = _isolate
	os.environ["XEYO_CWD"] = str(ws)
	for fn in (ms, lm):
		assert fn(None) == resolve_workspace_cwd(None) == str(ws)
		assert fn("other") == "other"
	assert resolve_workspace_cwd("") == str(ws)


# ── 第二座桥：settings → os.environ（09-22 补）────────────────────────────
# 注册表是开关的唯一权威，但**读开关的下游读 os.environ**（``wsc_projection.live_enabled``
# 等）。中间的 ``apply_to_environ`` 以前只在 ``server/__main__`` 与 ``routers/control`` 里调
# ⇒ GUI 生效、CLI / 脚本 / 离线评测里同一份 ``XEYO_WSC=1`` 静默无效。桥必须跟着工作区一起发布。

def _live() -> bool:
	from memory.wsc_projection import live_enabled

	return live_enabled()


def test_env_reader_sees_workspace_switch_after_publish(_isolate, monkeypatch) -> None:
	"""settings 开、env 未设 ⇒ 走 CLI 入口的读 env 下游必须看到"开"。"""
	_, ws = _isolate
	from cli.cwdutil import resolve_cwd

	monkeypatch.delenv(_KEY, raising=False)
	_write_ws(ws, "1")
	resolve_cwd(str(ws))
	assert _live(), "apply_to_environ 没在入口里跑 ⇒ CLI/评测里 WSC 生产档静默失效"


def test_shell_env_survives_when_settings_is_silent(_isolate, monkeypatch) -> None:
	"""settings 没写这个键 ⇒ 不得用默认值盖掉用户在 shell / .bat 里设的值。"""
	_, ws = _isolate
	from cli.cwdutil import resolve_cwd

	monkeypatch.setenv(_KEY, "1")
	resolve_cwd(str(ws))
	assert os.environ[_KEY] == "1" and _live()


def test_workspace_off_beats_stray_env(_isolate, monkeypatch) -> None:
	"""settings 明确写 0 ⇒ 权威胜出（否则"界面上关了、进程里还开着"）。"""
	_, ws = _isolate
	from cli.cwdutil import resolve_cwd

	monkeypatch.setenv(_KEY, "1")
	_write_ws(ws, "0")
	resolve_cwd(str(ws))
	assert os.environ[_KEY] == "0" and not _live()
