"""生产活路径：没有新折叠事件的枪之间，折叠头必须逐字节不变。

事故（2026-09-21 生产冒烟，会话 ``sess_mubdqg8h_b4z3tx``，全程同一模型）：
活路径 ``project_c2_messages`` 每枪把 ``region_end`` 取成 ``max(keep_tail_cut, cursor)``，
于是头/尾交界每枪前移 ⇒ 交界之后的字节全部重排。厂商账本实测：折叠后
cache_hit 从 **99.8% 掉到 55.6%**、每请求成本 **¥9.23m → ¥21.11m（2.3 倍）**；
离线连打四枪看到头发射量在 38k→34k→28k→36k 之间来回摆（对话在长、发射量在缩）。
``fold_cadence`` 只在回放台被读，生产侧无人读 ⇒ 节奏没人守，就得由"交界只能由折叠事件
推进"这条不变量来守。
"""

from __future__ import annotations

import importlib
import json

import pytest

from tests.wsc._fixtures import msg_asst_text, msg_tool, msg_asst_use, synth_session

pytest.importorskip("synaptic")


class _W:
	"""最小 ``WorkingSnapshot``：活路径只读这三个字段。"""

	def __init__(self, cursor: int, frozen: int = 0, sid: str = "s") -> None:
		self.session_id = sid
		self.compact_cursor = cursor
		self.c1_frozen_until = frozen


def _body(msgs) -> str:
	return "\n".join(str(m.get("content") or "") for m in msgs)


@pytest.fixture
def live(monkeypatch, tmp_path):
	"""开活路径 + 把冷层视图写进 tmp（别污染测试工作区）+ 数真实投影次数。"""
	import importlib

	WP = importlib.import_module("memory.wsc_projection")
	# ``synaptic/__init__.py`` 把同名函数导出成了 ``synaptic.project`` ⇒ 必须走
	# ``importlib`` 拿模块对象，否则 ``import synaptic.project as SP`` 拿到的是函数。
	SP = importlib.import_module("synaptic.project")

	WP._STATE.clear()
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.delenv("XEYO_WSC_FROZEN_HEAD", raising=False)
	monkeypatch.delenv("XEYO_WSC_CADENCE_ABSORB", raising=False)
	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path))
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))
	real = SP.project
	n = [0]

	def spy(*a, **kw):
		n[0] += 1
		return real(*a, **kw)

	monkeypatch.setattr(SP, "project", spy)
	yield WP, n
	WP._STATE.clear()


def _folded_msgs(live):
	"""造一次真折叠：返回 (消息, 头, 右界, 投影次数)。"""
	WP, n = live
	from engine.compact import keep_tail_cut

	msgs = synth_session(turns=26, error_turn=4)
	cut = int(keep_tail_cut(msgs))
	out = WP.project_c2_messages(msgs, _W(cut), cwd=None)
	assert out is not None, "合成会话没被接管 ⇒ 先确认收益门/区域尺寸"
	assert n[0] == 1
	return msgs, out, cut


def test_head_is_byte_identical_when_not_absorbing(live, monkeypatch) -> None:
	"""不吸收（节奏判据关 ⇒ 纯冻结语义）⇒ 头字节原样复用，且整份发射是前缀扩展。"""
	WP, n = live
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	msgs, out, cut = _folded_msgs(live)
	more = msgs + [
		msg_asst_use("t9", "Bash", {"command": "ls -la src"}),
		msg_tool("t9", "Bash", "README.md\nauth.ts\n" + ("listing " * 40)),
		msg_asst_text("继续。" + ("新增正文 " * 30)),
	]
	second = WP.project_c2_messages(more, _W(cut), cwd=None)
	assert second is not None
	assert n[0] == 1, (
		"cursor 没动（= 没有新折叠事件）却重新投影了 ⇒ 头会被重写，"
		"厂商缓存从交界之后整段失效（生产实测 2.3 倍成本）"
	)
	assert second[0]["content"] == out[0]["content"], "折叠头字节变了"
	assert _body(second).startswith(_body(out)), "发射不是上一枪的前缀扩展 ⇒ 前缀仍被打断"


def test_absorb_keeps_head_append_only(live, monkeypatch) -> None:
	"""节奏判据开：允许折，但**新头必须以旧头开头**——这正是生产今晚破掉的契约。"""
	WP, n = live
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "1")
	msgs, out, cut = _folded_msgs(live)
	old_head = out[0]["content"]
	prev_n = n[0]
	body_prev = _body(out)
	grown = msgs + [
		msg_asst_use(f"t{i}", "Bash", {"command": f"sed -n '{i},{i+400}p' src/mod{i}.ts"})
		for i in range(12)
	] + [
		msg_tool(f"t{i}", "Bash", ("区域正文 " * 260) + f"MARK_{i}")
		for i in range(12)
	]
	second = WP.project_c2_messages(grown, _W(cut), cwd=None)
	assert second is not None
	new_head = second[0]["content"]
	if n[0] == prev_n:
		assert new_head == old_head, "没重新投影却换了头"
	else:
		assert new_head.startswith(old_head), (
			"吸收后头被**重写**（不是追加）⇒ 头之后的字节全重排，缓存整段失效"
		)
	assert _body(second).startswith(body_prev) or new_head.startswith(old_head), (
		"既重写了头又打断了发射前缀 ⇒ 两条不变量同时破"
	)


def test_declined_fold_keeps_frozen_head(live, monkeypatch) -> None:
	"""折叠尝试被收益门拒 ⇒ 必须仍发冻结头。返回 None = 调用方回退 C2 本体 = 前缀整段作废。

	⚠️ 桩必须打在**模块属性**上：`import synaptic.project as SP` 拿到的是 `synaptic/__init__.py`
	重导出的那个**函数**，对函数对象赋值 `SP.project = ...` 静默无效 —— 第一版就这么写了，
	结果"收益门拒折"这条分支根本没被测到（用例靠冻结语义自己绿了）。
	"""
	WP, n = live
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "1")
	msgs, out, cut = _folded_msgs(live)
	old_head = out[0]["content"]

	class _Decline:
		compressed = False
		rebuilt = False

	class _P:
		text = ""
		state = cold = None
		result = _Decline()

	SP = importlib.import_module("synaptic.project")
	seen = []

	def _decline(*a, **kw):
		seen.append(1)
		return _P()

	monkeypatch.setattr(SP, "project", _decline)
	# 拒折分支只在**真去折**的时候才可达：cursor 不动 ⇒ 走"没折叠事件 ⇒ 直接复用冻结头"，
	# 连投影都不发起（第一版把桩修对了以后就暴露在这里）。要测收益门，就得给一次折叠事件。
	more = msgs + [msg_asst_text("又长了 " * 400)]
	second = WP.project_c2_messages(more, _W(cut + 2), cwd=None)
	assert seen, "桩没被调到 ⇒ 这条用例什么都没测（第一版的失效形状）"
	assert second is not None, "收益门拒折时返回 None ⇒ 生产会回退 C2，前缀全废"
	assert second[0]["content"] == old_head, "拒折却换了头"


def test_cursor_advance_refolds(live) -> None:
	"""扩展事件必须重新投影，否则这条不变量会退化成"永远不再折叠"。"""
	WP, n = live
	msgs, _out, cut = _folded_msgs(live)
	more = msgs + [
		msg_asst_use("t9", "Bash", {"command": "grep -rn foo src"}),
		msg_tool("t9", "Bash", "src/a.ts:12:foo\n" + ("hit " * 60)),
	]
	second = WP.project_c2_messages(more, _W(cut + 2), cwd=None)
	assert second is not None
	assert n[0] == 2, "调用方推进了 cursor 却没重新投影 ⇒ 头永久停更"


def test_legacy_switch_cannot_rewrite_frozen_head(live, monkeypatch) -> None:
	WP, n = live
	monkeypatch.setenv("XEYO_WSC_FROZEN_HEAD", "0")
	msgs, _out, cut = _folded_msgs(live)
	more = msgs + [msg_asst_text("第二条" + ("正文 " * 30))]
	assert WP.project_c2_messages(more, _W(cut), cwd=None) is not None
	assert n[0] == 1, "ordinary requests preserve the frozen head"


def test_rollback_invalidates_frozen_head(live) -> None:
	"""消息变少（回滚/重开）⇒ 冻结的头必须作废，不许留在上下文里。"""
	WP, n = live
	msgs, _out, cut = _folded_msgs(live)
	short = msgs[:-12]
	second = WP.project_c2_messages(short, _W(cut), cwd=None)
	assert n[0] == 2, "回退后仍复用旧头 ⇒ 头里带着已经不存在的历史"
	assert second is None or len(_body(second)) < len(_body(msgs))


def test_index_age_counts_shots_since_the_head_was_built(live, monkeypatch) -> None:
	"""头的年龄必须当场可读：旧口径「索引占比」把"索引瘦"和"头根本没重建"混成一件事。

	实测（GUI 流量）125 枪才折一次 ⇒ 占比低几乎总是后者。能据以行动的只有"多少枪没刷"。
	"""
	WP, n = live
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	msgs, _out, cut = _folded_msgs(live)
	assert WP.live_index_age("s", None) == 0, "刚建出头 ⇒ 年龄必须从 0 起算"
	assert WP.live_index_age("no-such-session", None) == 0, "查无此会话 ⇒ 报 0，不许猜"

	grown = msgs + [msg_asst_text("又长了 " * 400)]
	for _ in range(3):
		assert WP.project_c2_messages(grown, _W(cut), cwd=None) is not None
	assert WP.live_index_age("s", None) == 3, "冻结头每过一枪不加龄 ⇒ 这个指标永远是 0"

	# 真折叠事件（cursor 前进）⇒ 头重建 ⇒ 年龄归零
	assert WP.project_c2_messages(grown, _W(cut + 2), cwd=None) is not None
	assert WP.live_index_age("s", None) == 0, "折过之后年龄没归零 ⇒ 读数会一直喊'索引过期'"


def test_handle_usage_is_counted_and_ledgered(live, monkeypatch, tmp_path) -> None:
	"""③：头活着期间被取回几次，必须当场可数。

	这是"句柄面要不要加上限"的唯一终结量：句柄面实测占头的 40%（中位 1,271 tok，
	另 343 tok 是决策卡），但砍它的代价是"被剪节点拉不回来"这条对外承诺。
	所以先记账、不动发射 —— 有分母之前不做裁剪。
	"""
	WP, n = live
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	from engine.compact import keep_tail_cut

	# 26 回合的合成会话**剪不出句柄面**（实测 index_tokens=0）⇒ 用 40 回合，
	# 否则这条用例只验了分子、分母恒 0。
	msgs = synth_session(turns=40, error_turn=4)
	cut = int(keep_tail_cut(msgs))
	assert WP.project_c2_messages(msgs, _W(cut), cwd=None) is not None

	retrieval = msgs + [
		msg_asst_use("t7", "Read", {"file_path": ".xeyo_offload/wsc/view.txt",
		                            "offset": 0, "limit": 40}),
		msg_tool("t7", "Read", "拉回来的正文 " * 40),
		msg_asst_text("继续。" + ("新增正文 " * 30)),
	]
	assert WP.project_c2_messages(retrieval, _W(cut), cwd=None) is not None
	st = next(iter(WP._STATE.values()))
	assert st.handle_refs == 1, "取回形状没被数 ⇒ 上限之争永远没有分母"
	assert st.handle_tokens > 0, "句柄面没入账 ⇒ 分子有了、分母是 0"

	# 噪声调用不得算取回（否则这个数字会虚高到毫无意义）
	noise = retrieval + [msg_asst_use("t8", "Bash", {"command": "ls -la src"}),
	                     msg_tool("t8", "Bash", "README.md")]
	assert WP.project_c2_messages(noise, _W(cut), cwd=None) is not None
	assert next(iter(WP._STATE.values())).handle_refs == 1, "普通工具调用被当成取回"

	# 头被替换 ⇒ 旧头退场时补一条账（这份头活了几枪、多大、被取回几次）
	WP.project_c2_messages(noise + [msg_asst_text("又长了 " * 400)], _W(cut + 2), cwd=None)
	path = tmp_path / "home" / "wsc_index_usage.jsonl"
	rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
	assert rows, "账没落盘 ⇒ 进程一死这个量就没了"
	assert rows[-1]["handle_refs"] == 1 and rows[-1]["handle_tokens"] > 0
	assert rows[-1]["head_shots"] >= 2


def test_junction_retreat_keeps_frozen_head(live, monkeypatch) -> None:
	"""交界下标回退（尾部预算把上界顶回交界之下）不得作废冻结头。

	上界是 `keep_tail_cut` 按**尾部预算现算**的：一根大 tool 结果落进尾部就能把它顶
	回去。旧口径在这条分支上把整份状态（含冻结头）扔掉 ⇒ 本该是"前缀扩展"的一枪变
	成全量重排，厂商侧整段 miss。这就是那批"不该发生的 miss"的机械来源之一。
	"""
	WP, n = live
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	import engine.compact as EC

	ktc = {"v": 79}
	monkeypatch.setattr(EC, "keep_tail_cut", lambda msgs, **kw: ktc["v"])
	msgs = synth_session(turns=26, error_turn=4)
	first = WP.project_c2_messages(msgs, _W(20), cwd=None)
	assert first is not None and n[0] == 1, "合成会话没被接管"
	r0 = next(iter(WP._STATE.values())).region_end
	assert r0 > 25, f"构造成立条件：交界（{r0}）必须明显高于游标（20）"

	ktc["v"] = r0 - 5  # 下一枪：尾部保护区吃掉交界 ⇒ 上界回退到交界之下（游标不动）
	second = WP.project_c2_messages(msgs, _W(20), cwd=None)
	assert second is not None
	assert n[0] == 1, "交界回退却重新投影 ⇒ 冻结头被整段换掉（不该发生的 miss）"
	assert second[0]["content"] == first[0]["content"], "折叠头字节变了"
	assert _body(second).startswith(_body(first)), "发射不是上一枪的前缀扩展"


def test_cwd_flap_does_not_drop_the_frozen_head(live, monkeypatch, tmp_path) -> None:
	"""调用方每枪给的 cwd 抖动不得换槽位，也不得改写发射字节。

	cwd 只用来定一次 offload 路径；冻结点一旦钉住，之后整段只管字节不变（`_pinned`）。
	旧口径把 cwd 拼进状态键 ⇒ 抖一次就落进冷槽位 = 整段重投。
	"""
	import os

	WP, n = live
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	msgs, out, cut = _folded_msgs(live)
	pinned = next(iter(WP._STATE.values())).cwd
	assert pinned == os.environ["XEYO_CWD"], "冻结点没钉住第一次定义它的那个 cwd"
	more = msgs + [msg_asst_text("继续。" + ("正文 " * 30))]

	second = WP.project_c2_messages(more, _W(cut), cwd=str(tmp_path).upper())
	assert second is not None
	assert n[0] == 1, "cwd 抖一次就重新投影 ⇒ 同一会话落进两个槽位"
	assert _body(second).startswith(_body(out)), "cwd 抖动改了发射字节"

	other = tmp_path / "other"
	other.mkdir()
	monkeypatch.setenv("XEYO_CWD", str(other))
	assert WP.project_c2_messages(more, _W(cut), cwd=None) is not None
	assert n[0] == 1, "环境 cwd 变了就重新投影 ⇒ 冻结点没钉死"
	assert next(iter(WP._STATE.values())).cwd == pinned


def test_offline_projections_do_not_pollute_the_head_ledger(live, monkeypatch, tmp_path) -> None:
	"""离线重放/扫描台必须能把自己从生产分母里摘出去。

	真实事故（09-23）：`wsc_index_usage.jsonl` 3,668 行里 3,605 行是我自己的扫描脚本写的，
	于是"头存活枪数 p50=1"说的是探针的行为，不是生产的。同一个原则已经用在
	`fold_events`（不传 account 就不写）——这里补齐。
	"""
	WP, _n = live
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	monkeypatch.setenv("XEYO_WSC_OFFLINE", "1")
	from engine.compact import keep_tail_cut

	msgs = synth_session(turns=40, error_turn=4)
	cut = int(keep_tail_cut(msgs))
	assert WP.project_c2_messages(msgs, _W(cut), cwd=None) is not None
	assert WP.project_c2_messages(msgs + [msg_asst_text("又长了 " * 400)],
	                              _W(cut + 2), cwd=None) is not None
	path = tmp_path / "home" / "wsc_index_usage.jsonl"
	assert not path.exists(), "离线台把生产账本写脏了（分母一旦污染，之前所有率都作废）"
