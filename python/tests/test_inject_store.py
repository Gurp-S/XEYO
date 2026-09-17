"""T_now 去重台账（``prompt/inject_store.py``）契约测试。

冻结口径（T_now v2 管道 2 纪律「值不变不重注」）：
- 默认档 ``on``：同 key 同指纹不重复注入；``off`` 是逐字节旁路逃生档；
- ``shadow``：只记证据（供收益评估），注入照旧；
- ``on``：同 key 同指纹 → 本轮不注入；
- 事件类（管道 3）**永不过台账**——drain 语义下去重 = 静默丢事件；
- fail-open / 有界 / 会话隔离：台账坏了、账满了，可见面不受影响。

落点说明：``on`` 档的充分条件（上一版仍在模型可见面）由留痕面提供，
本文件只冻结台账自身的确定性行为与装配口接线。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt import inject_store
from prompt.inject_store import (
	MAX_KEYS_PER_SESSION,
	MAX_SESSIONS,
	MODE_OFF,
	MODE_ON,
	MODE_SHADOW,
	InjectStore,
	begin_round,
	end_round,
	fingerprint,
)


@pytest.fixture(autouse=True)
def _clean_store(monkeypatch):
	monkeypatch.delenv(inject_store.FLAG_ENV, raising=False)
	inject_store.get_store().clear()
	yield
	inject_store.get_store().clear()
	monkeypatch.delenv(inject_store.FLAG_ENV, raising=False)


# --------------------------------------------------------------------- 档位


def test_mode_defaults_on_with_explicit_escape_hatches(monkeypatch):
	# 默认档 = on（T_now v2 的设计行为：值不变不重注）；off 是逃生门，
	# shadow 是只观测不生效的采集档。
	assert inject_store.mode() == MODE_ON
	monkeypatch.setenv(inject_store.FLAG_ENV, "shadow")
	assert inject_store.mode() == MODE_SHADOW
	monkeypatch.setenv(inject_store.FLAG_ENV, "off")
	assert inject_store.mode() == MODE_OFF
	monkeypatch.setenv(inject_store.FLAG_ENV, "OFF")
	assert inject_store.mode() == MODE_OFF
	# 未设 / 未知值 → 设计行为 on（不静默降级到旧行为）
	monkeypatch.delenv(inject_store.FLAG_ENV, raising=False)
	assert inject_store.mode() == MODE_ON
	monkeypatch.setenv(inject_store.FLAG_ENV, "yes-please")
	assert inject_store.mode() == MODE_ON


def test_fingerprint_stable_under_format_noise():
	a = fingerprint("# 块\nline1\nline2\n")
	b = fingerprint("# 块\r\nline1\r\nline2")  # CRLF + 行尾空白
	assert a == b
	assert fingerprint("# 块\nline1") != a


# ------------------------------------------------------------------- 三档行为


def test_off_mode_is_transparent(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_OFF)
	store = InjectStore()
	token = begin_round("s1")
	try:
		assert store.decide("goal", "同文本") is True
		assert store.decide("goal", "同文本") is True  # 关档不记账、不跳过
	finally:
		end_round(token)
	assert store.stats()["sessions"] == 0


def test_shadow_mode_records_evidence_but_always_injects(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_SHADOW)
	store = InjectStore()
	sid = "s-shadow"
	store.begin(sid)
	token = begin_round(sid)
	try:
		assert store.decide("goal", "目标 A") is True
		assert store.decide("goal", "目标 A") is True  # 照旧注入
		assert store.decide("goal", "目标 B") is True
	finally:
		end_round(token)
	stats = store.stats()
	assert stats["mode"] == MODE_SHADOW
	assert stats["hits"] == 1  # 第二次同值 = 1 次「本可跳过」
	assert stats["misses"] == 2
	assert stats["would_skip"] == {"goal": 1}


def test_on_mode_skips_only_after_commit(monkeypatch):
	"""跳过的前提是**上一版真的进了历史**（commit），不是"我记过一次"。"""
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	sid = "s-on"
	store.begin(sid)
	token = begin_round(sid)
	try:
		assert store.decide("goal", "目标 A") is True  # 首次必注
		# 还没落库 → 绝不跳过（否则历史里其实没有这一版 ⇒ 静默丢信息）
		assert store.decide("goal", "目标 A") is True
		store.commit(sid, "goal", fingerprint("目标 A"))
		assert store.decide("goal", "目标 A") is False  # 已在可见面 → 跳过
		assert store.decide("goal", "目标 B") is True  # 值变了 → 注入
		store.commit(sid, "goal", fingerprint("目标 B"))
		assert store.decide("goal", "目标 B") is False
	finally:
		end_round(token)


def test_no_session_id_never_dedups(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	token = begin_round("")  # 无会话身份 → 不参与去重
	try:
		assert store.decide("goal", "目标 A") is True
		assert store.decide("goal", "目标 A") is True
	finally:
		end_round(token)


# ------------------------------------------------------- 隔离 / 有界 / fail-open


def test_sessions_are_isolated(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	store.begin("a")
	token = begin_round("a")
	try:
		assert store.decide("goal", "同一份状态") is True
	finally:
		end_round(token)
	store.begin("b")
	token = begin_round("b")
	try:
		# 换会话：账本各算各的，同文本仍须注入
		assert store.decide("goal", "同一份状态") is True
	finally:
		end_round(token)


def test_ledger_is_bounded(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	sid = "s-bound"
	store.begin(sid)
	token = begin_round(sid)
	try:
		for i in range(MAX_KEYS_PER_SESSION + 20):
			store.commit(sid, f"block-{i}", fingerprint(f"value-{i}"))
	finally:
		end_round(token)
	assert len(store._ledger[sid]) <= MAX_KEYS_PER_SESSION and len(store._ledger) == 1


def test_sessions_are_bounded_and_lru(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	for i in range(MAX_SESSIONS + 5):
		store.begin(f"s-{i}")
	assert len(store._ledger) <= MAX_SESSIONS
	assert "s-0" not in store._ledger  # 最久未触碰者先淘汰


def test_fail_open_on_broken_ledger(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	store.begin("s-broken")

	class _Boom(dict):
		def get(self, *_a, **_k):  # noqa: D102
			raise RuntimeError("ledger corrupt")

	store._ledger["s-broken"] = _Boom()
	token = begin_round("s-broken")
	try:
		# 台账坏了也必须注入（绝不因台账故障丢模型可见信息）
		assert store.decide("goal", "目标 A") is True
	finally:
		end_round(token)


def test_forget_and_clear(monkeypatch):
	monkeypatch.setenv(inject_store.FLAG_ENV, MODE_ON)
	store = InjectStore()
	store.begin("s1")
	token = begin_round("s1")
	try:
		store.decide("goal", "目标 A")
	finally:
		end_round(token)
	store.forget("s1")
	assert "s1" not in store._ledger
	store.clear()
	assert store.stats()["sessions"] == 0
