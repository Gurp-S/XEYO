"""循环熔断（loop_breaker）回归测试。

覆盖 2026-09-14 事故（同签名连续 166 次、越阈静默）的结构性反例：
- L1 同签名连续：第 N 次起每次都拒，**第 N+50 次仍在拒**（永不静默）；
- 输出每次微变**不构成逃逸**（事故真实形态：命令尾挂第二个 rg）；
- L2 周期重复（A→B→A→B）、L3 同签名同结果、L4 同工具无新内容各自命中；
- 半开探针：拒 R 次放 1 次（合法长轮询的自愈出口），且探针拿到新结果才解除；
- 分页续读 / 交互工具 transparent（既不计数也不重置）；
- 措辞禁导演词（理念红线机器执法）+ metadata 契约 + 总开关零行为变化；
- 阈值误配置当场报错（fail-loud，对齐 DSH 立场）。

理念红线执法：禁导演词（应该/建议/请/勿/优先/推荐）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.loop_breaker import (
	CYCLE_LENGTHS,
	LEDGER_NAME,
	LoopBreaker,
	Refusal,
	loop_break_enabled,
)
from engine.repeat_guard import EXEMPT_TOOLS, semantic_key

_FORBIDDEN = ("应该", "建议", "请", "勿", "优先", "推荐")

#: 测试里想固定"永不进探针"的档位（比任何用例的调用次数都大）。
_NO_PROBE = 10**6


def _disabled_probe_breaker(**kwargs) -> LoopBreaker:
	kwargs.setdefault("probe_after", _NO_PROBE)
	return LoopBreaker(**kwargs)


# ====== L1 同签名连续 ======

class TestL1SameSignature:
	def test_refuses_from_threshold_and_never_goes_silent(self):
		lb = _disabled_probe_breaker(same_at=3)
		args = {"command": "rg -n foo"}
		seen = [lb.admit("Bash", args) for _ in range(53)]
		assert seen[0] is None and seen[1] is None
		assert all(r is not None for r in seen[2:]), "第 3 次起必须每次都拒"
		assert seen[-1].kind == "L1"
		assert seen[-1].count == 53, "第 N+50 次仍在报（计数持续增长）"

	def test_output_variation_does_not_escape(self):
		"""事故真实形态：同签名、每次输出都不同（尾挂第二个 rg）→ 仍熔断。"""
		lb = _disabled_probe_breaker(same_at=3)
		args = {"command": 'rg a; echo "=== b ==="; rg b'}
		last = None
		for i in range(10):
			last = lb.admit("Bash", args)
			if last is None:
				lb.observe_result("Bash", args, f"output-{i}")
		assert last is not None and last.kind == "L1"

	def test_different_signatures_do_not_trip(self):
		lb = _disabled_probe_breaker(same_at=3)
		for i in range(8):
			assert lb.admit("Read", {"path": f"f{i}.py"}) is None

	def test_chain_resets_on_different_call(self):
		lb = _disabled_probe_breaker(same_at=3)
		args = {"command": "pytest -q"}
		assert lb.admit("Bash", args) is None
		assert lb.admit("Bash", args) is None
		assert lb.admit("Read", {"path": "x"}) is None  # 换签名 → 链重置
		assert lb.admit("Bash", args) is None
		assert lb.admit("Bash", args) is None
		assert lb.admit("Bash", args) is not None  # 重新连续到 3 → 拒


# ====== L2 周期重复 ======

class TestL2Cycle:
	def test_alternating_cycle_refused(self):
		lb = _disabled_probe_breaker(same_at=99, cycle_at=3)
		calls = [("Read", {"path": "a"}), ("Bash", {"command": "b"})]
		seen = [lb.admit(*calls[i % 2]) for i in range(6)]
		assert all(r is None for r in seen[:5])
		assert seen[5] is not None and seen[5].kind == "L2"
		assert seen[5].count == 2

	def test_cycle_length_declared(self):
		assert 2 in CYCLE_LENGTHS and 1 not in CYCLE_LENGTHS

	def test_distinct_calls_never_form_cycle(self):
		lb = _disabled_probe_breaker(same_at=99, cycle_at=3)
		for i in range(12):
			assert lb.admit("Read", {"path": f"f{i}"}) is None


# ====== L3 同签名同结果 ======

class TestL3Equivalent:
	def test_same_signature_same_result_refused(self):
		lb = _disabled_probe_breaker(same_at=99, equiv_at=2)
		args = {"command": "cat state.json"}
		assert lb.admit("Bash", args) is None
		lb.observe_result("Bash", args, "same")
		assert lb.admit("Bash", args) is None
		lb.observe_result("Bash", args, "same")
		refusal = lb.admit("Bash", args)
		assert refusal is not None and refusal.kind == "L3"

	def test_result_change_disarms(self):
		lb = _disabled_probe_breaker(same_at=99, equiv_at=2)
		args = {"command": "cat state.json"}
		lb.admit("Bash", args)
		lb.observe_result("Bash", args, "same")
		lb.admit("Bash", args)
		lb.observe_result("Bash", args, "changed")  # 结果变化 → 回 1
		assert lb.admit("Bash", args) is None


# ====== L4 同工具无新内容 ======

class TestL4NoNewContent:
	def test_parameter_variation_same_results_refused(self):
		"""换参数、结果全是旧的（本回合已见过）→ 命中（逐字节判据，无启发式）。"""
		lb = _disabled_probe_breaker(same_at=99, equiv_at=99, family_at=2)
		for i in range(3):
			lb.observe_result("Grep", {"pattern": f"p{i}"}, "same-old-content")
		refusal = lb.admit("Grep", {"pattern": "p9"})
		assert refusal is not None and refusal.kind == "L4"

	def test_new_content_clears_streak(self):
		lb = _disabled_probe_breaker(same_at=99, equiv_at=99, family_at=2)
		for i in range(3):
			lb.observe_result("Grep", {"pattern": f"p{i}"}, "same-old-content")
		lb.observe_result("Grep", {"pattern": "p4"}, "brand-new")
		assert lb.admit("Grep", {"pattern": "p5"}) is None


# ====== 半开探针（合法长轮询的出口） ======

class TestProbe:
	def test_l1_probe_keeps_stride_not_escape(self):
		lb = LoopBreaker(same_at=3, probe_after=2)
		args = {"command": "job status"}
		seen = [lb.admit("Bash", args) for _ in range(9)]
		allowed = [i for i, r in enumerate(seen) if r is None]
		assert allowed == [0, 1, 4, 7], "前 2 次放行 + 之后每 3 次一个探针"
		assert all(r is not None for r in (seen[2], seen[3], seen[5], seen[6], seen[8]))

	def test_probe_result_is_new_heals_l3(self):
		lb = LoopBreaker(same_at=99, equiv_at=2, probe_after=1)
		args = {"command": "poll"}
		assert lb.admit("Bash", args) is None
		lb.observe_result("Bash", args, "same")
		assert lb.admit("Bash", args) is None
		lb.observe_result("Bash", args, "same")
		assert lb.admit("Bash", args) is not None  # L3 命中
		assert lb.admit("Bash", args) is None  # 探针放行
		lb.observe_result("Bash", args, "changed")  # 探针拿到新结果 → 解除
		assert lb.admit("Bash", args) is None


# ====== 豁免 ======

class TestTransparency:
	def test_pagination_is_transparent(self):
		lb = _disabled_probe_breaker(same_at=2)
		assert lb.admit("Grep", {"pattern": "p"}) is None
		for offset in range(1, 5):
			assert lb.admit("Grep", {"pattern": "p", "offset": offset}) is None
		assert lb.admit("Grep", {"pattern": "p"}) is not None  # 分页不重置链

	def test_exempt_tools_transparent(self):
		lb = _disabled_probe_breaker(same_at=2)
		exempt = sorted(EXEMPT_TOOLS)[0]
		assert lb.admit("Bash", {"command": "x"}) is None
		for _ in range(5):
			assert lb.admit(exempt, {"question": "?"}) is None
		assert lb.admit("Bash", {"command": "x"}) is not None


# ====== 文案 / 元数据 / 开关 / 取证 ======

class TestContract:
	def _all_kind_texts(self) -> list[str]:
		texts: list[str] = []
		l1 = _disabled_probe_breaker(same_at=2)
		l1.admit("Bash", {"command": "x"})
		texts.append(l1.admit("Bash", {"command": "x"}).text)
		l2 = _disabled_probe_breaker(same_at=99, cycle_at=2)
		calls = [("Read", {"path": "a"}), ("Bash", {"command": "b"})]
		for i in range(4):
			r = l2.admit(*calls[i % 2])
		texts.append(r.text)
		l3 = _disabled_probe_breaker(same_at=99, equiv_at=2)
		l3.admit("Bash", {"command": "c"})
		l3.observe_result("Bash", {"command": "c"}, "same")
		l3.admit("Bash", {"command": "c"})
		l3.observe_result("Bash", {"command": "c"}, "same")
		texts.append(l3.admit("Bash", {"command": "c"}).text)
		l4 = _disabled_probe_breaker(same_at=99, equiv_at=99, family_at=2)
		for i in range(3):
			l4.observe_result("Grep", {"pattern": f"p{i}"}, "old")
		texts.append(l4.admit("Grep", {"pattern": "p9"}).text)
		return texts

	def test_wording_compliance(self):
		for text in self._all_kind_texts():
			for word in _FORBIDDEN:
				assert word not in text, f"熔断文案出现导演词: {word}"
			assert text.startswith("[loop_break] ")
			assert "not executed" in text

	def test_metadata_contract(self):
		lb = _disabled_probe_breaker(same_at=2)
		lb.admit("Bash", {"command": "x"})
		refusal = lb.admit("Bash", {"command": "x"})
		assert isinstance(refusal, Refusal)
		meta = refusal.metadata()
		assert meta["loop_refused"] is True
		assert meta["loop_kind"] == "L1"
		assert meta["loop_count"] == 2
		assert len(meta["loop_sig"]) == 16

	def test_kill_switch_is_noop(self, monkeypatch):
		monkeypatch.setenv("XEYO_LOOP_BREAK", "0")
		assert loop_break_enabled() is False
		lb = LoopBreaker()
		args = {"command": "x"}
		for _ in range(20):
			assert lb.admit("Bash", args) is None
		lb.observe_result("Bash", args, "same")
		assert lb.admit("Bash", args) is None

	def test_invalid_env_threshold_fails_loud(self, monkeypatch):
		monkeypatch.setenv("XEYO_LOOP_BREAK_AT", "abc")
		with pytest.raises(ValueError):
			LoopBreaker()
		monkeypatch.setenv("XEYO_LOOP_BREAK_AT", "1")  # 低于下限 2
		with pytest.raises(ValueError):
			LoopBreaker()

	def test_ledger_row_written(self):
		from usage.ledger import usage_dir

		lb = _disabled_probe_breaker(same_at=2)
		lb.note_turn_tokens(1000)
		lb.admit("Bash", {"command": "x"})
		assert lb.admit("Bash", {"command": "x"}) is not None
		path = usage_dir() / LEDGER_NAME
		row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
		assert row["kind"] == "L1" and row["tool"] == "Bash" and row["count"] == 2
		assert 0.0 <= row["tok_share"] <= 1.0

	def test_token_share_recorded(self):
		lb = _disabled_probe_breaker(same_at=99)
		lb.admit("Bash", {"command": "a"})
		lb.note_turn_tokens(300)
		lb.admit("Read", {"path": "b"})
		lb.note_turn_tokens(100)
		assert lb.token_share(semantic_key("Bash", {"command": "a"})) == pytest.approx(0.75)

	def test_reset_clears_state(self):
		lb = _disabled_probe_breaker(same_at=2)
		args = {"command": "x"}
		lb.admit("Bash", args)
		assert lb.admit("Bash", args) is not None
		lb.reset()
		assert lb.admit("Bash", args) is None


# ====== 装配守卫 ======

class TestWiring:
	def test_engine_wires_all_three_seams(self):
		"""准入 / 结果登记 / token 取证三处都必须在 query_loop 里接线。"""
		src = (
			Path(__file__).resolve().parents[1] / "engine" / "query_loop.py"
		).read_text(encoding="utf-8")
		assert "LoopBreaker(" in src
		assert "loop_breaker.admit" in src
		assert "loop_breaker.observe_result" in src
		assert "loop_breaker.note_turn_tokens" in src
		assert "loop_refused" not in src  # metadata 由 Refusal 产出，不散落在接线点