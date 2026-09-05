"""契约：记忆开关「GUI 显示 == 运行时行为」同源（memory_switches 唯一权威）。

红线：
- 任何**注册在册**开关的运行时读取必须走 ``memory_switches.get_value``
  （settings.memory 唯一权威，env 不参与）。历史上 ``search`` / ``memindex``
  直接读 os.environ、sidecar 走 promote 回退默认开，造成「GUI 显示关、运行时开」。
- **已固化开关**（收益明确后出册恒开）：settings/env 均不可修改，只能改源码。
  第一批 A4/ω/⑮，第二批 F4/C2 引用锚点/C2 逃生舱/A2 还原/A5 差分（各自模块恒 True）。

锁定读取点：
- ``memory.search.query_reweight_enabled``（固化）
- ``memory.memindex.sqlite_index_enabled``（固化）/ ``restore_enabled``（固化）
- ``memory.simulator.cache_model.cooldown_enabled``（固化）
- ``memory.rerank_preference_shadow.enabled``（固化）
- ``engine.aging.aging_enabled``（注册键，默认关）
- ``sidecar.policy.side_enabled``（注册键严格 get_value；未注册键保留 env/promote 语义）

运行：``py -3.11 -m pytest tests/test_memory_switch_authority.py -q``
"""

from __future__ import annotations

import importlib

import pytest

from memory import memory_switches

search_mod = importlib.import_module("memory.search")


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
	"""隔离 XEYO_HOME / XEYO_CWD：settings 只看 tmp，绝不读开发者真实配置。"""
	home = tmp_path / "home"
	ws = tmp_path / "ws"
	home.mkdir()
	ws.mkdir()
	monkeypatch.setenv("XEYO_HOME", str(home))
	monkeypatch.setenv("XEYO_CWD", str(ws))
	return ws


def test_registered_switch_runtime_accessors_follow_settings(isolated):
	"""settings 显式指定 → 运行时访问器同向翻转（含默认口径快照）。"""
	from engine.aging import aging_enabled

	# 默认口径（settings 未指定）
	assert aging_enabled() is False  # T27 默认关

	memory_switches.save({"XEYO_TOOL_AGING": "1"}, cwd=str(isolated))
	assert aging_enabled() is True


def test_env_cannot_leak_into_runtime(isolated, monkeypatch):
	"""settings 未指定时，残留/手动 env 一律不参与（get_value 语义）。"""
	from engine.aging import aging_enabled

	monkeypatch.setenv("XEYO_TOOL_AGING", "1")
	monkeypatch.setenv("XEYO_C2_GATE", "1")
	assert aging_enabled() is False


def test_fixed_on_switches_ignore_settings_and_env(isolated, monkeypatch):
	"""固化开关全家桶：注册表已删键，settings/env 均不可修改。"""
	from engine.aging import aging_enabled  # noqa: F401 — 语义对照（注册键仍可切）
	from memory import memindex
	from memory.rerank_preference_shadow import enabled as rerank_enabled
	from memory.simulator.cache_model import cooldown_enabled

	# env 残留不参与
	monkeypatch.setenv("XEYO_MEMORY_SQLITE_INDEX", "0")
	monkeypatch.setenv("XEYO_CACHE_COOLDOWN_OMEGA", "0")
	monkeypatch.setenv("XEYO_MEMORY_RERANK_PREFERENCE", "0")
	monkeypatch.setenv("XEYO_MEMORY_QUERY_REWEIGHT", "0")
	monkeypatch.setenv("XEYO_C2_CITATION", "0")
	monkeypatch.setenv("XEYO_C2_ESCAPE_HATCH", "0")
	monkeypatch.setenv("XEYO_SESSION_MD_DELTA", "0")
	# settings 旧残留值也忽略（且 save 已拒绝这些键）
	assert memindex.sqlite_index_enabled() is True
	assert cooldown_enabled() is True
	assert rerank_enabled() is True
	assert search_mod.query_reweight_enabled() is True
	# 注册表确无固化键（GUI 不再显示）
	keys = {k for k, *_ in memory_switches.MEMORY_SWITCHES}
	fixed = {
		"XEYO_MEMORY_SQLITE_INDEX", "XEYO_CACHE_COOLDOWN_OMEGA",
		"XEYO_MEMORY_RERANK_PREFERENCE", "XEYO_MEMORY_QUERY_REWEIGHT",
		"XEYO_C2_CITATION", "XEYO_C2_ESCAPE_HATCH",
		"XEYO_MEMORY_RESTORE", "XEYO_SESSION_MD_DELTA",
		"XEYO_C2_TAIL_FORMULA",
	}
	assert not fixed & keys


def test_side_enabled_unregistered_key_keeps_env_and_promote(monkeypatch):
	"""未注册键保持原语义：专用 env > 全局 promote 回退。

	2026-09-06：XEYO_C2_PRESSURE_FORMULA 等 Path A 键已删除（v61 默认开启后冗余），
	转入"未注册"路径——由本测试覆盖；side_enabled 对它们不再保证恒 True。
	"""
	from sidecar.policy import side_enabled

	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")
	assert side_enabled("XEYO_C2_PRESSURE_FORMULA") is False  # 已删键：promote 关 → False
	monkeypatch.setenv("XEYO_C2_PRESSURE_FORMULA", "1")
	assert side_enabled("XEYO_C2_PRESSURE_FORMULA") is True  # 专用 env 显式开 → True
	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "1")
	assert side_enabled("XEYO_NOT_A_REGISTERED_SWITCH") is True
	monkeypatch.setenv("XEYO_NOT_A_REGISTERED_SWITCH", "0")
	assert side_enabled("XEYO_NOT_A_REGISTERED_SWITCH") is False


def test_side_enabled_unregistered_key_keeps_env_and_promote(monkeypatch):
	"""未注册键保持原语义：专用 env > 全局 promote 回退。"""
	from sidecar.policy import side_enabled

	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")
	assert side_enabled("XEYO_NOT_A_REGISTERED_SWITCH") is False
	monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "1")
	assert side_enabled("XEYO_NOT_A_REGISTERED_SWITCH") is True
	monkeypatch.setenv("XEYO_NOT_A_REGISTERED_SWITCH", "0")
	assert side_enabled("XEYO_NOT_A_REGISTERED_SWITCH") is False


def test_index_live_switch_registered_and_default_on():
	"""XEYO_MEMORY_INDEX_LIVE 已注册且默认开（用户决策 2026-09；settings 写 0 可关）。"""
	assert any(k == "XEYO_MEMORY_INDEX_LIVE" for k, *_ in memory_switches.MEMORY_SWITCHES)
	assert memory_switches.get_value("XEYO_MEMORY_INDEX_LIVE") == "1"
