"""留痕可见面（管道 2 去重）与下标空间：缺陷已闭合，契约钉在这里。

历史：`MessageStore.note_fingerprints(start=…)` 的口径曾是"投影下标"，
而唯一生产调用点 `engine/query_loop.py` 传的是 `snap.compact_cursor`（**历史**下标）；
两者隔着投影裁剪（同 note_key 只留最新版 / A 闸逐出 / 孤儿 tool 行丢弃）⇒
历史上出现过一次"同 key 更新"后，用历史游标切投影会**多跳 k 行**，
把"明明已在模型输入里"的留痕算成不可见 ⇒ 折叠后（最需要去重的时刻）被重发。

**闭合方式（2026-10-04，重构所选路线）**：不再靠下标猜可见性——
生产改为传**实际投影行**：`store.note_fingerprints(projected=projected)`
（`engine/query_loop.py` 调用点），按 (note_key, note_fp) + 角色 + 完整正文按身份匹配；
`start` 只保留为**非压缩调用方的 API（投影）下标兼容口径**，生产不再使用。
（旧版本的回归用例是 strict xfail；走 `projected=` 路线后已按本文件"修好即摘牌"的约定转绿。）

本文件分工：前提守卫 / **生产契约（投影身份匹配，绿）** / 反向对照（旧版不得可见） /
兼容口径的边界。任何一条变红都说明上面这段契约被改动了——先回读 `session/message_store.py`
与该调用点，再决定是改契约还是改测试。
"""

from __future__ import annotations

from msgtypes.message import Message
from session.message_store import MessageStore


def _note(key: str, fp: str, text: str) -> Message:
	return Message(role="system", content=text, note_kind="P3", note_key=key, note_fp=fp)


def _store_with_one_folded_row() -> tuple[MessageStore, Message]:
	"""构造：同 key 的两版留痕 ⇒ 投影比历史少一行；返回 store 与"活跃留痕"那条。"""
	store = MessageStore()
	store.append(Message(role="user", content="问题 1"))
	store.append(_note("ledger/mode", "fp-v1", "模式合同 v1"))
	store.append(_note("ledger/mode", "fp-v2", "模式合同 v2"))
	live = _note("ledger/active", "fp-live", "活跃便签")
	store.append(live)
	store.append(Message(role="assistant", content="回答 1"))
	return store, live


def test_projection_is_shorter_than_history_after_a_key_update() -> None:
	"""前提守卫：投影确实比历史短，且活跃留痕的位置在两个空间里不同号。

	这条必须**绿**。它一旦变红，说明"同 key 只留最新版"的裁剪不再发生
	⇒ 下面"投影身份匹配"那些用例的前提消失，应当重写它们而不是放宽断言。
	"""
	store, live = _store_with_one_folded_row()
	hist = list(store.items)
	proj = store.as_api_messages()
	assert len(proj) < len(hist), "投影没裁掉任何一行 ⇒ 本文件的缺陷前提不成立"

	h_idx = next(i for i, m in enumerate(hist) if m is live)
	p_idx = next(i for i, r in enumerate(proj) if r.get("note_key") == "ledger/active")
	assert p_idx == h_idx - 1, f"期望两个空间差 1 行：历史={h_idx} 投影={p_idx}"


def test_visible_note_set_uses_the_actual_projection() -> None:
	"""生产契约：传**实际投影行**，按身份匹配 ⇒ 两个下标空间的错位整体消失。

	（旧缺陷回归：这里曾是 strict xfail——"活跃留痕明明在投影里却没进可见面"。
	走 `projected=` 路线后转绿；不要再退回"拿游标猜可见性"。）
	"""
	store, live = _store_with_one_folded_row()
	proj = store.as_api_messages()
	visible = store.note_fingerprints(projected=proj)
	assert ("ledger/active", "fp-live") in visible, (
		f"活跃留痕在投影里却没进可见面 ⇒ C2 折叠后会被重发（visible={sorted(visible)}）"
	)
	assert live.note_key in {k for k, _fp in visible}
	# 被顶掉的旧版不得顺带混进来（去重的背面是"永不重发"，同样要防）
	assert ("ledger/mode", "fp-v1") not in visible
	assert ("ledger/mode", "fp-v2") in visible


def test_superseded_note_must_stay_invisible() -> None:
	"""反向对照：可见面不许把被顶掉的那版也算进来（否则去重变成"永不重发"）。"""
	store, _live = _store_with_one_folded_row()
	proj = store.as_api_messages()
	fps = {r.get("note_fp") for r in proj if r.get("note_key") == "ledger/mode"}
	assert fps == {"fp-v2"}, f"投影里同 key 应只剩最新版，实际 {fps}"
	assert ("ledger/mode", "fp-v1") not in store.note_fingerprints(start=0)
	assert ("ledger/mode", "fp-v1") not in store.note_fingerprints(projected=proj)


def test_mapping_boundaries_do_not_lose_or_invent_entries() -> None:
	"""兼容口径（`start`，API 下标）的边界：start=0 给出全部；越界为空；负数按 0。

	防的是"修成反向过度"——映射写错时最容易一边漏一边多。
	"""
	store, _live = _store_with_one_folded_row()
	all_visible = store.note_fingerprints(start=0)
	assert all_visible == {("ledger/mode", "fp-v2"), ("ledger/active", "fp-live")}, all_visible

	assert store.note_fingerprints(start=len(store.items) + 5) == set()
	assert store.note_fingerprints(start=-3) == all_visible, "负数按 0 处理，不得倒着切"
