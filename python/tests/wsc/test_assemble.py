"""热层组装测试：段落排序（规则 2）、日志布局（规则 8）、双组装模式的前缀语义、[NEXT] 默认关闭。

注意：``journal_layout`` 默认开，本文件的**分段布局**断言（rebuild 判据 / 追加预算 /
次序）都以 ``journal_layout=False`` 显式进入 OFF 路径 —— 那条路径仍然是被支持的
A/B 对照臂，必须继续被锁死，而不是随默认值漂移。
"""

from __future__ import annotations

from synaptic.assemble import (
	H_CONSTRAINTS,
	H_DECISIONS,
	H_MAIN,
	H_NEXT,
	H_REQUESTS,
	H_TODO,
	H_UNRESOLVED,
	H_WORKING,
	SegStat,
	order_segments,
	pick_level,
	render_decisions,
)
from synaptic.graph import build_graph
from synaptic.metrics import lcp_tokens
from synaptic.project import Projection, project
from synaptic.textutil import node_token_len
from synaptic.types import KIND_USER, MODE_APPEND_ONLY, MODE_CLOSURE, PruneCard, WscParams
from wsc._fixtures import CONSTRAINT, SRC, synth_session


def _proj(msgs, params=None, prev=None, region_end=None) -> Projection:
	return project(
		msgs,
		region_end=region_end if region_end is not None else len(msgs),
		params=params,
		prev=prev,
	)


def test_constraints_section_carries_goal_and_constraint():
	msgs = synth_session(turns=6)
	p = _proj(msgs)
	assert H_CONSTRAINTS in p.text
	assert "修复登录超时" in p.text
	assert CONSTRAINT in p.text, "用户硬约束没进 PIN"


def test_instruction_lines_are_not_in_hot_layer():
	"""规则 1：后继用户消息（原「指令」段）不得出现在热层。

理由：未被保护的尾部本来就逐字带着最近的消息；再钉进 PIN 既重复计费，又因为
逐轮必变而让其后全部稳定内容每轮失去 KV 前缀。
	"""
	msgs = synth_session(turns=8, error_turn=4)
	p = _proj(msgs)
	assert "指令:" not in p.text, "后继用户消息仍被钉进热层"
	assert not any(p_.key.startswith("update:") for p_ in p.result.hot.pins)



def test_working_set_marks_file_stale_after_write():
	"""规则 5：写后必须标 STALE，而不是继续把旧 read 当有效内容。

用 turns=5 / error_turn=4：写发生在最后一轮，之后没有新的 read —— 这正是
「最后一次 read 已经过期」的形态。若写之后又有 read，则不应标 STALE。
	"""
	msgs = synth_session(turns=5, error_turn=4)
	p = _proj(msgs)
	assert H_WORKING in p.text
	assert "STALE" in p.text, "文件被改后未标记过期"
	stale = [s for s in p.result.hot.file_states if s.stale]
	assert stale, "文件状态表里没有过期条目"


def test_file_not_stale_when_read_after_write():
	"""反向断言：写之后又读过，就不该继续标 STALE。"""
	msgs = synth_session(turns=7, error_turn=2)
	p = _proj(msgs)
	stale_paths = {s.path for s in p.result.hot.file_states if s.stale}
	assert SRC not in stale_paths, "写之后有新 read，却仍标 STALE"


def test_closure_mode_reports_rebuild_when_pin_changes():
	"""closure 的代价点：中途出现新的未解决错误 → PIN 变 → 前缀必断。

注意 rebuilt 的判据是「旧全文是否仍是新全文的字节前缀」，而不是「是否重排」。
closure 每轮都在重排，但只要新全文恰好以旧全文为前缀，KV 前缀就不会 miss ——
这是实测会发生的（区域只增长、PIN 不变时，新内容自然追加在尾部）。
	"""
	msgs = synth_session(turns=9, error_turn=7)
	# 先找失败节点下标，构造「之前没有错误 / 之后出现错误」两个时刻
	g = build_graph(msgs)
	err_idx = next(n.idx for n in g.nodes if n.is_error)
	before = msgs[: err_idx - 1]
	assert not any(build_graph(before).nodes[i].is_error for i in range(len(before)))

	first = _proj(before, WscParams(mode=MODE_CLOSURE, journal_layout=False))
	assert first.result.rebuilt is False, "首次压缩没有旧前缀，不应记重建"
	second = _proj(
		msgs, WscParams(mode=MODE_CLOSURE, journal_layout=False), prev=first.state
	)
	assert second.result.rebuilt is True, "PIN 中途变化却未记前缀失效"


def test_append_only_never_breaks_prefix_across_many_growth_steps():
	"""逐步增长的多轮里，append_only 每一轮都必须保住冻结前缀。

closure 是「可能保住也可能不保住」（取决于改动落在尾部还是中段），所以那个
结论由回放实测给出；append_only 是**结构性**保证，必须每轮成立。
	"""
	msgs = synth_session(turns=14, error_turn=4)
	params = WscParams(mode=MODE_APPEND_ONLY, append_budget_tokens=100_000)
	prev = None
	prev_text = ""
	steps = 0
	for back in (20, 16, 12, 8, 5):
		end = len(msgs) - back
		if end <= 4:
			continue
		p = _proj(msgs, params, prev=prev, region_end=end)
		if prev is not None:
			assert p.text.startswith(prev_text), f"第 {steps} 步改写了冻结前缀"
			assert p.result.rebuilt is False
		prev, prev_text = p.state, p.text
		steps += 1
	assert steps >= 3, "增长步数不足，测试没覆盖到"


def test_append_only_preserves_byte_prefix_and_never_rebuilds():
	msgs = synth_session(turns=9)
	wide = WscParams(mode=MODE_APPEND_ONLY, append_budget_tokens=10_000)
	p1 = _proj(msgs, wide, region_end=len(msgs) - 10)
	p2 = _proj(msgs, wide, prev=p1.state, region_end=len(msgs) - 5)
	assert p2.result.rebuilt is False
	assert p2.text.startswith(p1.text), "append_only 却改写了冻结前缀"
	assert lcp_tokens(p2.text, p1.text) == p1.tokens, "公共前缀应等于上一轮全文"


def test_append_only_falls_back_to_rebuild_when_budget_blown():
	msgs = synth_session(turns=9)
	p1 = _proj(
		msgs,
		WscParams(mode=MODE_APPEND_ONLY, append_budget_tokens=10_000, journal_layout=False),
		region_end=len(msgs) - 10,
	)
	p2 = _proj(
		msgs,
		WscParams(mode=MODE_APPEND_ONLY, append_budget_tokens=1, journal_layout=False),
		prev=p1.state,
		region_end=len(msgs) - 5,
	)
	assert p2.result.rebuilt is True, "追加预算被打爆却未记整层重建"


# ---------------------------------------------------------------------------
# 规则 8：日志布局
# ---------------------------------------------------------------------------

def test_journal_layout_never_breaks_prefix_while_growing():
	"""日志布局的核心不变量：增长过程里每一轮投影都是上一轮的**字节前缀**。

这是规则 2 的结构性解：分段布局下只要还有一个「会长」的段排在别人前面，
一次追加就斩断其后全部内容的缓存（实测 199 回合里中位 LCP 只剩 324 token）。
日志布局把所有条目按首现顺序追加、永不重排 ⇒ 单调性由结构保证。
	"""
	msgs = synth_session(turns=14, error_turn=4)
	params = WscParams(mode=MODE_CLOSURE, journal_growth_tokens=10_000_000)
	prev = None
	prev_text = ""
	steps = 0
	for back in (24, 20, 16, 12, 8, 5):
		end = len(msgs) - back
		if end <= 4:
			continue
		p = _proj(msgs, params, prev=prev, region_end=end)
		if prev is not None:
			assert p.text.startswith(prev_text), f"第 {steps} 步日志被改写（非纯追加）"
			assert p.result.rebuilt is False, f"第 {steps} 步不应重冻结"
			assert p.result.journal_refroze is False
			assert lcp_tokens(p.text, prev_text) == node_token_len(prev_text), (
				"公共前缀应等于上一轮全文"
			)
		prev, prev_text = p.state, p.text
		steps += 1
	assert steps >= 4, "增长步数不足，测试没覆盖到"


def test_journal_refreezes_when_growth_budget_exceeded():
	"""日志胖过阈值 → 追加新头与旧头句柄，但不能打断已发前缀。"""
	msgs = synth_session(turns=12, error_turn=4)
	prev = None
	refroze = 0
	for back in range(20, 3, -3):
		end = len(msgs) - back
		if end <= 4:
			continue
		p = _proj(
			msgs,
			WscParams(mode=MODE_CLOSURE, journal_growth_tokens=1),
			prev=prev,
			region_end=end,
		)
		if prev is not None and p.result.journal_refroze:
			refroze += 1
			assert p.result.rebuilt is False, "append-only 换头不应记为前缀失效"
			assert p.text.startswith(prev.full_text), "换头改写了已发出的前缀"
		prev = p.state
	assert refroze > 0, "阈值设到 1 仍从未重冻结"


def test_region_user_messages_are_rendered_via_requests():
	"""规则 1 的信息空洞：区域内用户原话必须有渲染通道。

背景：规则 1 删掉 ``指令`` 段后，``render_main`` 跳过 ``pin_nodes``，而 ``pin_nodes``
含全部实质用户节点 ⇒ 区域内用户原话一度完全没有渲染通道，且因为是 pin 不被剪，
连 expand 句柄都没有（= 不可恢复）。聚合签名：user 针存活率 94.6% → 71.0%。
	"""
	msgs = synth_session(turns=10, error_turn=4, user_every=2)
	g = build_graph(msgs)
	region_end = len(msgs) - 6
	want = [n for n in g.nodes if n.idx < region_end and n.kind == KIND_USER]
	assert len(want) >= 2, "夹具里区域内用户消息太少，测不出空洞"

	p = _proj(msgs, region_end=region_end)
	assert H_REQUESTS in p.text, "区域内用户原话没有渲染通道"
	# 分子分母同源（seeds.user_nodes）：覆盖率必须满，否则就是信息空洞。
	assert p.result.user_requests_total == len(want)
	assert p.result.user_requests_rendered == len(want), (
		"覆盖率不为 100%：首个用户节点走 目标 pin，其余必须逐条出现在 [REQUESTS]"
	)
	for n in want[1:]:
		head = " ".join(n.text.split())[:40]
		assert head in p.text, f"用户原话 {head!r} 未出现在热层"


def test_requests_entries_carry_lossless_handle():
	"""截断的摘要必须配真句柄：否则「无损可恢复」被截断悄悄破坏。"""
	msgs = synth_session(turns=10, error_turn=4, user_every=2)
	region_end = len(msgs) - 6
	p = _proj(msgs, region_end=region_end)
	for line in p.text.splitlines():
		if line.startswith(H_REQUESTS):
			idx = int(line.split("#", 1)[1].split(" ", 1)[0])
			handle = f"node://{idx}"
			assert handle in line, f"{line!r} 缺句柄"
			node = p.graph.node(idx)
			assert node is not None
			assert tuple(p.cold.expand(handle)) == (node.text,), "句柄往返不无损"


def test_segstats_describe_final_text_under_append_only():
	"""自检口径修正：统计必须落在**最终投影文本**上，而不是冻结前的重渲染文本。

旧实现里两个组装模式报出的 churn 表逐字相同，而 append_only 是字节冻结语义
—— 那是自相矛盾的，说明统计对象错了。修好后 append_only 的段前缀失稳率必须是 0。
	"""
	msgs = synth_session(turns=12, error_turn=4)
	params = WscParams(
		mode=MODE_APPEND_ONLY,
		append_budget_tokens=1_000_000,
		journal_layout=False,
	)
	prev = None
	seen_obs = False
	for back in (20, 16, 12, 8, 5):
		end = len(msgs) - back
		if end <= 4:
			continue
		p = _proj(msgs, params, prev=prev, region_end=end)
		prev = p.state
		if p.result.front_break:
			seen_obs = True
			assert max(p.result.front_break.values()) == 0.0, (
				f"append_only 下段文本只追加，却报出前缀失稳: {p.result.front_break}"
			)
	assert seen_obs, "没采到任何有观测的回合"


def test_next_section_is_off_by_default():
	msgs = synth_session(turns=6)
	off = _proj(msgs, WscParams())
	assert H_NEXT not in off.text
	on = _proj(msgs, WscParams(include_next=True))
	assert H_NEXT in on.text, "显式开启后 [NEXT] 仍未出现"


def test_sections_are_ordered_and_unique():
	msgs = synth_session(turns=8, error_turn=4)
	p = _proj(msgs)
	idx = {h: p.text.find(h) for h in (H_CONSTRAINTS, H_UNRESOLVED, H_WORKING, H_MAIN, H_DECISIONS)}
	present = {h: i for h, i in idx.items() if i >= 0}
	assert list(present.values()) == sorted(present.values()), f"段落顺序错乱: {idx}"
	# 首轮无历史 → 必须落在先验序上
	assert list(p.text.find(h) for h in (H_CONSTRAINTS, H_UNRESOLVED, H_WORKING)) == sorted(
		p.text.find(h) for h in (H_CONSTRAINTS, H_UNRESOLVED, H_WORKING)
	)


def test_order_by_churn_puts_unstable_segment_last():
	"""规则 2：前缀失稳率高的段落必须排到后面。"""
	stats = {
		H_CONSTRAINTS: SegStat(obs=10, changed=0, front_break=0),
		H_MAIN: SegStat(obs=10, changed=10, front_break=0),  # 只追加 → 变动高但前缀稳
		H_TODO: SegStat(obs=10, changed=10, front_break=9),
	}
	order = order_segments(
		{H_CONSTRAINTS, H_MAIN, H_TODO},
		stats,
		(H_CONSTRAINTS, H_MAIN, H_TODO),
		WscParams(churn_margin=0.15),
	)
	assert order.index(H_CONSTRAINTS) < order.index(H_MAIN) < order.index(H_TODO), order


def test_order_hysteresis_keeps_order_when_gap_is_small():
	"""滞回：差距不显著时不许改次序 —— 改次序本身就是一次前缀失效。"""
	stats = {
		H_CONSTRAINTS: SegStat(obs=10, changed=2, front_break=2),
		H_MAIN: SegStat(obs=10, changed=3, front_break=2),  # 差 0.0 < margin
	}
	order = order_segments(
		{H_CONSTRAINTS, H_MAIN},
		stats,
		(H_CONSTRAINTS, H_MAIN),
		WscParams(churn_margin=0.15),
	)
	assert order == (H_CONSTRAINTS, H_MAIN)


def test_order_inserts_new_segment_at_prior_position():
	"""新出现的段落插回先验位置，而不是被挤到末尾。"""
	stats = {
		H_CONSTRAINTS: SegStat(obs=0, changed=0, front_break=0),
		H_WORKING: SegStat(obs=0, changed=0, front_break=0),
		H_UNRESOLVED: SegStat(obs=0, changed=0, front_break=0),
	}
	order = order_segments(
		{H_CONSTRAINTS, H_WORKING, H_UNRESOLVED},
		stats,
		(H_CONSTRAINTS, H_WORKING),
		WscParams(),
	)
	assert order == (H_CONSTRAINTS, H_UNRESOLVED, H_WORKING), order


def test_ordering_can_be_disabled_for_ab():
	stats = {H_TODO: SegStat(obs=10, changed=9, front_break=9)}
	off = order_segments(
		{H_CONSTRAINTS, H_TODO}, stats, (H_TODO, H_CONSTRAINTS),
		WscParams(stable_prefix_ordering=False),
	)
	assert off == (H_CONSTRAINTS, H_TODO), "关闭开关后应回退固定先验序"


def test_churn_self_check_warns_above_threshold():
	"""自检项：某段逐轮变动率 > 50% 时必须留下告警。"""
	msgs = synth_session(turns=10, error_turn=4)
	params = WscParams(mode=MODE_CLOSURE, churn_min_obs=1, churn_warn_rate=0.0)
	prev = None
	warned = []
	for back in range(14, -1, -2):
		end = len(msgs) - back
		if end <= 4:
			continue
		p = _proj(msgs, params, prev=prev, region_end=end)
		warned.extend(p.result.churn_warnings)
		prev = p.state
	assert warned, "变动率超阈却没有任何告警"
	assert any("变动率" in w for w in warned)



def test_prune_card_not_duplicated_across_decisions_and_pruned():
	"""同一条卡不在 [DECISIONS] 与 [PRUNED] 各出现一次（纯重复计费）。"""
	msgs = synth_session(turns=8, error_turn=4)
	p = _proj(msgs)
	handles = [c.handle for c in p.result.hot.cards]
	for h in handles:
		assert p.text.count(h) == 1, f"{h} 在热层出现多次"


def test_decisions_row_carries_extra_files_without_duplicating_first():
	"""`[DECISIONS]` 行必须带 ``files=``（只发射 ``files[1:]``）。

	归因实测：185 条 failure_site 漏失里 17 条是「卡里已有这条路径、就是没渲染」。
	`_conclusion` 只内联 `files[0]`；其余路径此前在热层没有任何出口。"""
	cards = (
		PruneCard(
			card_id="B7",
			conclusion="Bash 对 src/a.ts 失败：FAILED",
			files=("src/a.ts", "src/b.ts", "src/c.ts"),
			error_sig="FAILED",
			replay="npm test",
			nodes=(7,),
			tokens=10,
		),
	)
	row = render_decisions(cards)[0][1]
	assert "src/b.ts" in row and "src/c.ts" in row, f"DECISIONS 行漏了 files[1:]：{row}"
	assert row.count("src/a.ts") == 1, "files[0] 已在结论里，不得重复发射"
	assert "branch://B7" in row


def test_level_watermarks():
	assert pick_level(0.30) == "Micro"
	assert pick_level(0.78) == "Light"
	assert pick_level(0.83) == "Medium+"
	assert pick_level(0.87) == "Medium"
	assert pick_level(0.97) == "Hard"
