"""冻结头落盘的两条契约：**封印不成立就绝不复用** / **状态丢了也得是前缀扩展**。

背景（生产实测）：`wsc_projection._STATE` 是进程内存（FIFO 64 槽）。进程重启、或第 65 个
会话进来，冻结头字节就没了 ⇒ 那一枪由 `synaptic.project` 从头重排 ⇒ 发出的 prompt 与上一枪
逐字无关 ⇒ 厂商侧整段 miss。这里量的是"不再重排"这个行为本身，不是 token 数。
"""

from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("synaptic")

from tests.wsc._fixtures import synth_session  # noqa: E402


class _W:
	"""最小 ``WorkingSnapshot``：活路径只读这三个字段。"""

	def __init__(self, cursor: int, sid: str = "s") -> None:
		self.session_id = sid
		self.compact_cursor = cursor
		self.c1_frozen_until = 0


def _body(msgs) -> str:
	return "\n".join(str(m.get("content") or "") for m in msgs)


@pytest.fixture
def store(monkeypatch, tmp_path):
	HS = importlib.import_module("memory.wsc_head_store")
	WP = importlib.import_module("memory.wsc_projection")
	WP._STATE.clear()
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "1")
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path))
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))
	monkeypatch.setattr(HS, "_pruned", False)
	yield HS, WP
	WP._STATE.clear()


def _pair() -> list[dict]:
	return [
		{"role": "user", "content": "u" * 40},
		{"role": "assistant", "content": "a" * 40},
	]


def test_every_seal_refuses_on_its_own(store) -> None:
	"""ver/cwd/cursor/越界/改写 —— 每条单独坏掉都必须拒（拒 = 走重建，方向永远更保守）。"""
	HS, _ = store
	msgs = _pair()
	key = "seal"
	HS.save(key, text="HEAD", cwd="/x", cursor=2, region_end=2, messages=msgs)

	fh = HS.load(key, cwd="/x", cursor=2, messages=msgs)
	assert fh is not None and fh.text == "HEAD" and fh.region_end == 2

	assert HS.load(key, cwd="/y", cursor=2, messages=msgs) is None, "cwd 变了还复用"
	assert HS.load(key, cwd="/x", cursor=3, messages=msgs) is None, "cursor 变了（期间真折叠过）还复用"
	assert HS.load(key, cwd="/x", cursor=2, messages=msgs[:1]) is None, "回滚/越界还复用"

	rewritten = [dict(msgs[0], content="u" * 41)] + msgs[1:]
	assert HS.load(key, cwd="/x", cursor=2, messages=rewritten) is None, "历史被改写还复用"


def test_off_never_touches_disk(store, monkeypatch) -> None:
	"""旗标关 ⇒ 不写也不读（新机制默认不动发射形状，关掉要能干净回到旧行为）。"""
	HS, _ = store
	monkeypatch.setattr(HS, "enabled", lambda: False)
	msgs = _pair()
	HS.save("off", text="HEAD", cwd="/x", cursor=2, region_end=2, messages=msgs)
	assert not HS.path_for("off").exists()
	assert HS.load("off", cwd="/x", cursor=2, messages=msgs) is None


def test_corrupt_record_is_fail_open(store) -> None:
	"""半截文件 / 空 text / ver 不符 ⇒ 当没有，绝不抛。"""
	HS, _ = store
	msgs = _pair()
	p = HS.path_for("bad")
	p.parent.mkdir(parents=True, exist_ok=True)

	p.write_text("{not json", encoding="utf-8")
	assert HS.load("bad", cwd="/x", cursor=2, messages=msgs) is None

	p.write_text(json.dumps({"ver": 1, "cwd": "/x", "cursor": 2, "region_end": 2,
	                         "seal": HS.region_seal(msgs, 2), "text": ""}), encoding="utf-8")
	assert HS.load("bad", cwd="/x", cursor=2, messages=msgs) is None

	p.write_text(json.dumps({"ver": 99, "cwd": "/x"}), encoding="utf-8")
	assert HS.load("bad", cwd="/x", cursor=2, messages=msgs) is None


def test_lost_state_reuses_bytes_and_rewrite_forces_rebuild(store, monkeypatch) -> None:
	"""状态丢失后那一枪**不许再重排**；但历史被改写时必须重排（宁重建不发错头）。"""
	HS, WP = store
	SP = importlib.import_module("synaptic.project")
	from engine.compact import keep_tail_cut

	real = SP.project
	n = [0]

	def spy(*a, **kw):
		n[0] += 1
		return real(*a, **kw)

	monkeypatch.setattr(SP, "project", spy)

	msgs = synth_session(turns=26, error_turn=4)
	cut = int(keep_tail_cut(msgs))

	# ① 首次折叠：真调 project，并落盘
	first = WP.project_c2_messages(msgs, _W(cut), cwd=None)
	assert first is not None, "合成会话没被接管 ⇒ 先确认收益门/区域尺寸"
	assert n[0] == 1

	# ② 等价于进程重启（/ 第 65 个会话把状态槽顶掉），历史未动
	WP._STATE.clear()
	second = WP.project_c2_messages(msgs, _W(cut), cwd=None)
	assert second is not None
	assert n[0] == 1, "状态丢了就走重排 ⇒ 那一枪与上一枪逐字无关（厂商侧整段 miss）"
	assert _body(second).startswith(_body(first)), "接回来的头没构成前缀扩展"

	# ③ 历史被改写 + 状态丢失：seal 必须拒，重排（即使重排结果是另一个头）
	rewritten = [dict(msgs[0], content=str(msgs[0].get("content")) + " 改写")] + msgs[1:]
	WP._STATE.clear()
	third = WP.project_c2_messages(rewritten, _W(cut), cwd=None)
	assert third is not None
	assert n[0] == 2, "历史变了还复用旧头 ⇒ 发出的 prompt 与历史不一致"
