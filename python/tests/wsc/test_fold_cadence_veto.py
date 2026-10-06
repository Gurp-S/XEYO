"""折叠冷却否决闸的接线契约：A1 默认开 = 冷却窗口内真拦（只收紧、零写入、留痕）；A1=0 = 回到只记账。

生产缺口（2026-09-30 账本）：``try_extend_c2`` 记的 ``c2_gap_shots``（实测回本枪数，
中位 21）从不拦下一次折叠 —— 相邻折叠间隔中位 4 枪，98 对里 87 对落在上一折的冷却
窗口内；折叠枪厂商命中 77.12% vs 其后平枪 92.28%（当日 470 枪 90.09%）。

两个旗标分开测，因为它们的收益要分开量（``_wsc_out/_fold_veto_ab.py``）：
A1 ``XEYO_WSC_FOLD_COOLDOWN_VETO``（实测档）/ A2 ``XEYO_WSC_FOLD_MIN_INTERVAL``（常数档）。
"""

from __future__ import annotations

import json

import pytest
from types import SimpleNamespace

from memory.working import WorkingSnapshot


@pytest.fixture(autouse=True)
def _clean_veto_env(monkeypatch):
	"""两旗标一律从"未设"起跑：A1 默认开（未设=拦）、A2 默认关（未设=不拦），机器级残留不许污染单测。"""
	monkeypatch.delenv("XEYO_WSC_FOLD_COOLDOWN_VETO", raising=False)
	monkeypatch.delenv("XEYO_WSC_FOLD_MIN_INTERVAL", raising=False)


def _big_msgs(n: int, size: int = 6000) -> list[dict]:
	return [{"role": "user", "content": "x" * size} for _ in range(n)]


def _decide(action: str, *, hardtop: bool = False) -> SimpleNamespace:
	return SimpleNamespace(
		a_star=action,
		hardtop=hardtop,
		branches={
			"keep": SimpleNamespace(x="K"),
			"C1": SimpleNamespace(x="C"),
			"C2": SimpleNamespace(x="C2"),
		},
	)


def _extend(
	monkeypatch,
	*,
	flag: str | None = None,
	value: str = "1",
	turns: int = 999,
	gap_shots: int = 0,
	force: bool = False,
):
	"""直接打 ``try_extend_c2``（绕过 decide/窗口派生），只测闸本身。"""
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	if flag:
		monkeypatch.setenv(flag, value)
	w = WorkingSnapshot()
	w.session_id = "s_veto_contract"
	w.compact_cursor = 8
	w.c1_frozen_until = 8
	w.turns_since_c2 = turns
	w.c2_gap_shots = gap_shots
	msgs = _big_msgs(40)
	acct: dict = {}
	ok = try_extend_c2(
		w, msgs, len(msgs) - 4, Params(window_tokens=128_000), force=force, account=acct
	)
	return ok, acct, w


def _press(monkeypatch, mem_switch, *, turns: int, gap_shots: int, action: str = "C2", hardtop: bool = False):
	"""把活路径打到「已压缩态 + decide 点了 action」这一枪，返回 working。"""
	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: _decide(action, hardtop=hardtop))
	w = WorkingSnapshot()
	w.session_id = "s_veto_contract"
	w.compact_cursor = 8
	w.c1_frozen_until = 8
	w.turns_since_c2 = turns
	w.c2_gap_shots = gap_shots
	project_for_model(
		_big_msgs(40), w, remaining_turns=30, context_limit=1_000_000,
		include_memory_index=False,
	)
	return w


def _rows(path) -> list[dict]:
	if not path.is_file():
		return []
	out = []
	for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = line.strip()
		if line:
			try:
				out.append(json.loads(line))
			except json.JSONDecodeError:
				pass
	return out


def _fold_rows() -> list[dict]:
	from usage.ledger import fold_events_path

	return _rows(fold_events_path())


def test_default_on_vetoes_within_the_recorded_gap(monkeypatch):
	"""旗标未设 = A1 默认开（2026-09-30 落实）：同一夹具必须被拦，且一个字都不写。"""
	ok, acct, w = _extend(monkeypatch, turns=3, gap_shots=12)
	assert ok is False, f"默认开却放行了折叠：{acct}"
	assert acct.get("reason") == "cooldown_veto"
	assert w.compact_cursor == 8, "拦下就不许动游标"
	assert w.c2_gap_shots == 12, "拦下就不许改写冷却实测"


def test_flag_off_restores_the_old_behavior(monkeypatch):
	"""回退开关（=0）：同一夹具照旧批准、照旧写态 —— 关掉即逐字回到"只记账"。"""
	ok, acct, w = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_COOLDOWN_VETO", value="0", turns=3, gap_shots=12
	)
	assert ok is True, f"A1 关掉后仍拦了折叠：{acct}"
	assert acct.get("reason") == "worth_fold"
	assert w.compact_cursor == 36, "批准路径必须照旧推进游标"
	assert int(w.c2_gap_shots) > 0, "批准路径必须照旧回填冷却"
	assert "veto_min_interval" not in acct, "关掉时不该多出否决字段"


def test_cooldown_veto_blocks_within_recorded_gap(monkeypatch):
	"""A1：since < c2_gap_shots ⇒ 拒绝，且在任何写之前返回。"""
	ok, acct, w = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_COOLDOWN_VETO", turns=3, gap_shots=12
	)
	assert ok is False, "冷却窗口内不许折叠"
	assert acct.get("reason") == "cooldown_veto"
	assert acct.get("fold") is False and acct.get("forced") is False
	assert acct.get("turns_since_c2") == 3 and acct.get("c2_gap_shots") == 12
	assert acct.get("region_tokens") and acct.get("economics_basis") == "not_measured_cadence_veto"
	assert w.compact_cursor == 8, "否决不许动游标"
	assert w.c2_gap_shots == 12, "否决不许改写冷却实测（它这次的账根本没发生）"
	assert w.turns_since_c2 == 3 and w.c2_summary_text == "", "否决不许写任何状态"


def test_cooldown_veto_passes_after_all_future_reuses(monkeypatch):
	"""since 包含折叠枪：N 次后续复用后，since=N+1 才放行。"""
	ok, acct, _ = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_COOLDOWN_VETO", turns=12, gap_shots=12
	)
	assert ok is False and acct["reason"] == "cooldown_veto"
	ok, acct, w = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_COOLDOWN_VETO", turns=13, gap_shots=12
	)
	assert ok is True, f"到点仍被拦：{acct}"
	assert w.compact_cursor == 36


def test_cooldown_veto_without_measurement_fails_open(monkeypatch):
	"""没实测过（c2_gap_shots=0，例如只发生过 force 折）⇒ 不拦（与旧行为逐字一致）。"""
	ok, acct, _w = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_COOLDOWN_VETO", turns=1, gap_shots=0
	)
	assert ok is True and acct.get("reason") == "worth_fold"


def test_min_interval_blocks_until_n_and_passes_at_n(monkeypatch):
	"""A2 常数档：固定间隔 N 内拒绝、到 N 放行；理由与 A1 可分辨（A1 显式关掉，单量 A2）。"""
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "0")
	ok, acct, _w = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_MIN_INTERVAL", value="6", turns=5, gap_shots=99
	)
	assert ok is False and acct.get("reason") == "min_interval_veto"
	assert acct.get("veto_min_interval") == 6 and acct.get("turns_since_c2") == 5
	ok2, acct2, _w2 = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_MIN_INTERVAL", value="6", turns=6, gap_shots=99
	)
	assert ok2 is True and acct2.get("reason") == "worth_fold"


def test_min_interval_garbage_is_off(monkeypatch):
	"""写坏参数不许放大折叠（fail-open 方向固定）：非数 / 0 / 负数一律 = 关（A1 也关掉以单量 A2）。"""
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "0")
	for raw in ("abc", "0", "-3", ""):
		ok, acct, _w = _extend(
			monkeypatch, flag="XEYO_WSC_FOLD_MIN_INTERVAL", value=raw, turns=1, gap_shots=0
		)
		assert ok is True, f"min_interval={raw!r} 不该拦：{acct}"


def test_force_fold_ignores_the_veto(monkeypatch):
	"""硬顶（必要性）通道不受节奏约束 —— 与 cooling 对 hardtop 的豁免同一口径。"""
	ok, acct, w = _extend(
		monkeypatch, flag="XEYO_WSC_FOLD_COOLDOWN_VETO", turns=0, gap_shots=30, force=True
	)
	assert ok is True and acct.get("reason") == "forced", f"force 被拦：{acct}"
	assert w.c2_gap_shots == 30, "force 不参与冷却记账（既有的单向约定）"


def test_hardtop_can_fold_through_active_cooldown(monkeypatch, mem_switch):
	"""从生产调度入口验证容量必要性可以越过尚未结束的冷却。"""
	w = _press(monkeypatch, mem_switch, turns=0, gap_shots=30, hardtop=True)
	assert w.compact_cursor > 8
	assert w.c2_gap_shots == 30
	assert any(r.get("forced") and r.get("fold") for r in _fold_rows())


def test_rollback_drops_cooldown_of_discarded_head():
	from memory.working import flush, hydrate, reset_after_rollback
	w = WorkingSnapshot(session_id="s_rollback_cooldown", compact_cursor=8,
	                    c1_frozen_until=8, c2_gap_shots=30, turns_since_c2=2)
	flush(w.session_id, w)
	reset_after_rollback(w.session_id)
	restored = hydrate(w.session_id)
	assert restored.compact_cursor == 0
	assert restored.turns_since_c2 == 0
	assert restored.c2_gap_shots == 0


def test_both_flags_are_distinguishable(monkeypatch):
	"""同开时行上能分辨哪一刀先拦（A1 优先）；关掉 A1 就露出 A2。"""
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "1")
	monkeypatch.setenv("XEYO_WSC_FOLD_MIN_INTERVAL", "6")
	ok, acct, _w = _extend(monkeypatch, turns=2, gap_shots=20)
	assert ok is False and acct.get("reason") == "cooldown_veto"
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "0")
	ok2, acct2, _w2 = _extend(monkeypatch, turns=2, gap_shots=20)
	assert ok2 is False and acct2.get("reason") == "min_interval_veto"


def test_decoupled_branch_obeys_the_veto_and_writes_a_row(monkeypatch, mem_switch):
	"""生产真正的折叠驱动支（decoupled，不读 cooling）也必须被拦，且留痕可查。"""
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "1")
	w = _press(monkeypatch, mem_switch, turns=3, gap_shots=12, action="keep")
	assert w.compact_cursor == 8, "decoupled 支绕过了冷却否决 ⇒ 那一枪的折叠没被拦住"
	rows = _fold_rows()
	veto_rows = [r for r in rows if r.get("reason") == "cooldown_veto"]
	assert veto_rows, f"否决没有落进 fold_events：{[r.get('reason') for r in rows]}"
	assert veto_rows[-1].get("fold") is False
	assert veto_rows[-1].get("arm") == "wsc", "发射面由 WSC 接管时 arm 必须是 wsc"


def test_c2_branch_obeys_the_veto_too(monkeypatch, mem_switch):
	"""另一条调用点（decide 点 C2 且冷却已过）走的是同一道闸。"""
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "1")
	w = _press(monkeypatch, mem_switch, turns=4, gap_shots=12, action="C2")
	assert w.compact_cursor == 8, "C2 支绕过了冷却否决"
	assert [r for r in _fold_rows() if r.get("reason") == "cooldown_veto"], "C2 支没留痕"
