"""环境开关唯一登记表（#10 + #14）：两份名单同源、登记项自解释、漂移可机械复现。

原先 `tests/conftest.py`（8 键）与 `evals/changedetect/env_baseline.py` 的 `PINS`（3 键）
各写一份名单、**交集只有 1** ⇒ 新增开关必漏一处，而漏掉的那一处会把"这台机器怎么跑"
报成产品回归。本文件钉住"只登记一次"这件事本身。
"""

from __future__ import annotations

import pytest

from engine.env_switches import SWITCHES, isolation_pins, snapshot_pins, unregistered
from evals.changedetect import env_baseline, surface
from tests.premise import assert_premise


def _tools_fingerprint() -> list[tuple[str, str]]:
	return [(a.name, a.sha) for a in surface.collect(groups={"tools"})]


def test_pins_are_projected_from_one_registry() -> None:
	"""两处名单都是登记表的投影（不是各写一份）。"""
	assert {n for n, _ in env_baseline.PINS} == {
		s.name for s in SWITCHES if s.affects_snapshots
	}
	assert {n for n, _ in isolation_pins()} == {
		s.name for s in SWITCHES if s.affects_tests
	}
	assert dict(snapshot_pins()) == {
		s.name: s.why for s in SWITCHES if s.affects_snapshots
	}


def test_every_switch_states_its_impact() -> None:
	"""登记项必须自解释：说不清影响面的开关不该被静默豁免。"""
	for s in SWITCHES:
		assert s.why.strip(), s.name


def test_host_measured_drift_keys_are_registered() -> None:
	"""宿主实测会漂移 golden 的三键必须在快照名单里（防未来被删）。"""
	assert {"XEYO_TOOL_DENY", "XEYO_TOOL_SURFACE", "XEYO_T_NOW_SKIP"} <= {
		n for n, _ in env_baseline.PINS
	}


def test_conftest_isolates_snapshot_keys_too() -> None:
	"""原先只在 changedetect 名单里的两键，现在套件也兜底清掉（否则宿主设了就红）。"""
	assert {"XEYO_TOOL_SURFACE", "XEYO_T_NOW_SKIP"} <= {n for n, _ in isolation_pins()}


def test_host_measured_red_keys_are_isolated() -> None:
	"""实测让套件恒红的键必须在隔离名单里。

	防的是"回到本会话前 7 批的状态"：10 条红恒为同一集合，每次都要人肉重新归因一遍。
	"""
	# XEYO_WSC_SOFT_WATERMARK 已退场（2026-10-08 用户裁定）：不再登记、不再需隔离。
	assert {"XEYO_WSC_FOLD_MIN_INTERVAL", "XEYO_WSC"} <= {
		n for n, _ in isolation_pins()
	}


@pytest.mark.parametrize(
	"switch", [s for s in SWITCHES if s.drift_probe == "l0"], ids=lambda s: s.name
)
def test_registered_l0_drift_is_real(monkeypatch, switch) -> None:
	"""登记说它漂移 L0 ⇒ 实跑证明：设值面 ≠ 默认面，`pin()` 后逐字节回到默认面。

	`drift_probe == "l1"` 的键不在本测试内复现（要跑 `trace.collect()`，成本高一个量级）；
	登记表已记下层与探针取值，需要时按同一形状补。
	"""
	for s in SWITCHES:
		monkeypatch.delenv(s.name, raising=False)
	clean = _tools_fingerprint()

	monkeypatch.setenv(switch.name, switch.drift_value or "")
	assert_premise(
		_tools_fingerprint() != clean,
		f"登记说 {switch.name} 会漂移 L0，实测没漂（改登记，别改断言）",
	)

	env_baseline.pin()
	assert _tools_fingerprint() == clean


def test_unregistered_lists_only_switch_like_keys() -> None:
	"""未登记清单只收"像产品开关"的键：场地键（落盘位置）与已登记键都不算。"""
	assert unregistered({"XEYO_FOO": "1", "XEYO_HOME": "x", "XEYO_WSC": "1",
	                     "XEYO_SESSIONS_DIR": "d", "PATH": "z"}) == ("XEYO_FOO",)


def test_unregistered_is_empty_on_clean_process() -> None:
	"""干净进程里不产生输出（能静默就不说话）。"""
	assert unregistered({}) == ()
	assert unregistered({"XEYO_WSC": "1", "XEYO_T_NOW_SKIP": "env_facts"}) == ()
