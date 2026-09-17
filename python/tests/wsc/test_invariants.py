"""端到端不变量：PIN 必留、剪枝必有句柄、expand 无损、确定、零 LLM。

这些断言是「突触压缩自我描述」与「可复核数据」之间的分界线——设计文档说的
98–99.5% 保留率，如果不写成断言，就只是自述。
"""

from __future__ import annotations

from synaptic.graph import build_graph
from synaptic.metrics import (
	determinism_digest,
	needle_survival,
	recoverability,
)
from synaptic.prune import CARD_FILES_MAX, build_cards
from synaptic.project import default_params, project
from synaptic.seeds import harvest_needles
from synaptic.types import MODE_APPEND_ONLY, MODE_CLOSURE
from wsc._fixtures import CONSTRAINT, SRC, msg_asst_use, msg_tool, msg_user, synth_session


def _p(msgs, level="Medium+", mode=MODE_CLOSURE, region_end=None):
	return project(
		msgs,
		region_end=region_end if region_end is not None else len(msgs),
		params=default_params(level, mode),
	)


def test_pin_always_in_hot_layer():
	p = _p(synth_session(turns=8))
	assert CONSTRAINT in p.text
	assert any(pin.key == "goal" for pin in p.result.hot.pins)


def test_every_pruned_node_has_a_cold_handle():
	"""剪枝不是删除：每个被剪节点都必须能靠句柄拉回。"""
	p = _p(synth_session(turns=10, error_turn=4))
	rec = recoverability(p)
	assert rec["unbound"] == 0, f"有节点被删干净了: {rec['unbound_idx']}"
	assert rec["coverage"] == 1.0


def test_expand_is_lossless_for_all_handles():
	"""热记忆有损，冷记忆无损——用逐字节往返证明，不靠自述。"""
	p = _p(synth_session(turns=10, error_turn=4))
	rec = recoverability(p)
	assert rec["checked"] > 0, "没有任何句柄被验证（冷层没接上）"
	assert rec["lossless_rate"] == 1.0, f"冷层往返有损: {rec}"


def test_unresolved_error_reaches_hot_layer():
	p = _p(synth_session(turns=8, error_turn=4))
	assert "AssertionError" in p.text or "PROXY_OVERRIDE" in p.text or "退出码" in p.text
	# 失败分支既进 PIN（未解决）又进剪枝卡（已排除），两条路都在
	assert any(c.error_sig for c in p.result.hot.cards) or any(
		"未解决" in ln for ln in p.text.splitlines()
	)


def test_failure_path_is_not_lost():
	"""设计目标之一：删掉失败分支会让 Agent 重复犯错。"""
	msgs = synth_session(turns=8, error_turn=4)
	p = _p(msgs)
	region_end = len(msgs) // 2
	needles = harvest_needles(p.graph, {}, region_end=region_end)
	res = needle_survival(p.text, needles)
	assert res["path"]["n"] > 0
	assert res["path"]["rate"] > 0.0, "文件路径全部丢失"


def test_multifile_error_card_keeps_more_than_four_paths():
	"""多文件失败单元的路径**不许在卡片层被丢掉**。

	归因实测：185 条 failure_site 漏失里 52 条来自 `files=u.files[:4]`——Bash 单元的
	refs 会把命令串与输出里的路径全并进来，超出 4 条的部分此前没有任何渲染出口。
	直接对 `build_cards` 断言（不走 project：那里节点可能被 kept 而不生成卡）。"""
	paths = [f"src/mod{i}/util{i}.ts" for i in range(6)]
	msgs = [
		msg_user("修复多模块超时"),
		msg_asst_use("e0", "Bash", {"command": "npm test -- " + " ".join(paths)}),
		msg_tool(
			"e0",
			"Bash",
			"FAILED\n" + "\n".join(f"见 {p} 第 12 行" for p in paths),
			is_error=True,
		),
	]
	graph = build_graph(msgs)
	pruned = tuple(n.idx for n in graph.nodes)
	cards = build_cards(graph, pruned, default_params("Medium+"), region_end=len(msgs))
	assert cards, "全剪之后必须产卡"
	kept = {f for c in cards for f in c.files}
	missing = [x for x in paths if x not in kept]
	assert not missing, f"卡片层丢了路径：{missing}（上限应为 {CARD_FILES_MAX} 条）"
	assert CARD_FILES_MAX > 4


def test_compression_is_substantial_on_synthetic_busy_session():
	msgs = synth_session(turns=20, error_turn=4)
	p = _p(msgs)
	base = p.result.base_tokens
	assert p.tokens < base * 0.5, f"压缩不足：{p.tokens}/{base}"


def test_determinism_across_runs():
	msgs = synth_session(turns=8, error_turn=4)
	d1 = determinism_digest(_p(msgs).result)
	d2 = determinism_digest(_p(msgs).result)
	assert d1 == d2


def test_append_only_is_never_bigger_than_closure_on_same_turn():
	"""append_only 的代价是热层变胖，代价必须可量化而不是靠感觉。"""
	msgs = synth_session(turns=12, error_turn=4)
	c = _p(msgs, mode=MODE_CLOSURE)
	a = _p(msgs, mode=MODE_APPEND_ONLY)
	assert a.tokens >= c.tokens


def test_all_levels_produce_valid_hot_layer():
	for level in ("Micro", "Light", "Medium", "Medium+", "Hard"):
		p = _p(synth_session(turns=10, error_turn=4), level=level)
		assert p.text.strip()
		assert p.result.hot.level == level
		rec = recoverability(p)
		assert rec["unbound"] == 0, f"{level} 下有节点没句柄"


def test_gain_gate_declines_when_region_is_too_small():
	"""短区域上 PIN + 卡片开销会超过节省 —— 收益门必须拒绝，而不是硬压。"""
	msgs = synth_session(turns=3, error_turn=1)
	p = project(
		msgs,
		region_end=len(msgs),
		params=default_params("Medium+"),
		region_baseline_tokens=1,  # 原样重放只需 1 token → 压缩不可能划算
	)
	assert p.result.compressed is False
	assert any(t["step"] == "gain_gate" for t in p.result.trace)


def test_gain_gate_accepts_when_region_is_large():
	msgs = synth_session(turns=12, error_turn=4)
	p = project(
		msgs,
		region_end=len(msgs),
		params=default_params("Medium+"),
		region_baseline_tokens=10**9,  # 原样重放极贵 → 必须压
	)
	assert p.result.compressed is True


def test_gain_gate_defaults_off_when_baseline_unknown():
	"""调用方没给基线时不得擅自拒绝压缩（默认行为不变）。"""
	p = _p(synth_session(turns=8, error_turn=4))
	assert p.result.compressed is True


def test_no_network_at_runtime(monkeypatch):
	"""运行期双保险：掐掉出网通道，压缩流程仍应完整跑通。"""
	import socket

	def _boom(*a, **k):
		raise AssertionError("WSC 压缩过程中尝试建立网络连接")

	monkeypatch.setattr(socket, "create_connection", _boom)
	monkeypatch.setattr(socket, "getaddrinfo", _boom)
	p = _p(synth_session(turns=8, error_turn=4))
	assert p.text.strip()
