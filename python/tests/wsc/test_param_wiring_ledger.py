"""参数接线台账：每个 ``WscParams`` 字段必须声明「谁读它 / 默认是否生效 / 生产是否接线」。

存在理由（2026-09-21 事故）：我把 ``fold_cadence`` 当成"生产语义"写进评测口径并让用户据此
裁定，而生产侧**没有任何模块读它**（只有 ``replay.py`` 读）。这类"名字像生产、其实只活在
器具里"的旋钮，靠读代码注释和默认值是看不出来的——必须有一条测试逼每个字段表态。

本测试同时防两种腐坏：
* 新增字段不进台账 ⇒ 红（强制表态）。
* 台账里声明的读取点与实际不符 ⇒ 红（声明会随重构过期）。
"""

from __future__ import annotations

import dataclasses
import re
import pathlib

from synaptic.types import WscParams

PKG = pathlib.Path(__file__).resolve().parents[2] / "synaptic"

#: 只有器具层（评测台 / 报告 / CLI）读的字段 —— 生产路径不读，引用其数字必须标口径。
HARNESS_ONLY: frozenset[str] = frozenset({
	"fold_cadence",        # 只被 replay.py 读；活路径自行决定折叠时机
	"fold_margin",
	"fold_price_ratio",
})

#: 默认值下不产出任何行为差（旁路档 / 未并入主链）的字段。
DARK_BY_DEFAULT: frozenset[str] = frozenset({
	"soft_dag",
	"include_next",
	"freeze_working_set",
	"freeze_main_chain",
	"auto_rehydrate_working_set",
})


def _fields() -> list[str]:
	return [f.name for f in dataclasses.fields(WscParams)]


def _readers(name: str) -> set[str]:
	pat = re.compile(rf"\b{re.escape(name)}\b")
	out = set()
	for p in sorted(PKG.glob("*.py")):
		if p.name == "types.py":
			continue
		if pat.search(p.read_text(encoding="utf-8", errors="replace")):
			out.add(p.name)
	return out


def test_every_field_is_declared() -> None:
	missing = [n for n in _fields()
	           if n not in HARNESS_ONLY and n not in DARK_BY_DEFAULT and not _readers(n)]
	assert not missing, (
		f"这些字段既没进 HARNESS_ONLY / DARK_BY_DEFAULT，也没有任何读者：{missing}"
		"——要么接线，要么删掉，不要留「看起来在用」的参数"
	)


def test_ledger_sets_are_valid_and_disjoint() -> None:
	names = set(_fields())
	assert HARNESS_ONLY <= names, f"台账里有不存在的字段：{HARNESS_ONLY - names}"
	assert DARK_BY_DEFAULT <= names, f"台账里有不存在的字段：{DARK_BY_DEFAULT - names}"
	assert not (HARNESS_ONLY & DARK_BY_DEFAULT), (
		f"同一字段被声明成两类：{HARNESS_ONLY & DARK_BY_DEFAULT}"
	)


def test_harness_only_claims_stay_true() -> None:
	for name in HARNESS_ONLY:
		rs = _readers(name)
		assert rs, f"{name} 现在有读者了吗？台账需更新（声明是 HARNESS_ONLY）"
		assert all(r in {"replay.py", "report.py", "__main__.py"} for r in rs), (
			f"{name} 被生产/算法模块读了：{sorted(rs)} —— 它不再「只活在器具里」，"
			f"请把 HARNESS_ONLY 的声明改掉并同步评测口径"
		)


def test_dark_by_default_really_is_dark() -> None:
	p = WscParams()
	for name in DARK_BY_DEFAULT:
		v = getattr(p, name)
		assert v in (False, 0, "", None), f"{name} 默认值变成 {v!r} ⇒ 不再是旁路档，台账需更新"


def test_no_field_is_read_only_by_types() -> None:
	for name in _fields():
		if name in {"level", "mode"}:
			continue
		assert _readers(name) or name in HARNESS_ONLY | DARK_BY_DEFAULT, (
			f"{name} 有定义无读者：它不会改变任何输出，属可删项"
		)


#: 实测零收益、2026-09-22 已删的旋钮（墓碑）。上面两条只拦"新增无读者参数"；
#: 墓碑拦的是另一半：**有人把它带回来并给它加个读者**，那时通用规则就放行了。
RETIRED_KNOBS = (
	"card_raw_anchor_tokens",     # 卡面原文锚点：实测不改变任何一次折叠选择
	"error_pin_age_nodes",        # "错误老化"是误诊（age 中位数=2，正卡着而非堆积）
	"pin_exemption_max_tokens",   # 豁免帽：--pin-cap 400/600 与基线逐字节相同 ⇒ 收益恒为 0
)


def test_retired_knobs_stay_retired() -> None:
	names = set(_fields())
	came_back = [n for n in RETIRED_KNOBS if n in names]
	assert not came_back, (
		f"这些旋钮已被实测证明零收益并删除，重新出现要先给出收益数字：{came_back}"
	)
	metric = (PKG / "metrics.py").read_text(encoding="utf-8")
	assert "class TurnMetric" not in metric, "死代码 TurnMetric（全仓无构造点）被复活"
