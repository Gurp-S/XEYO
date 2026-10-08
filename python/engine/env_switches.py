"""环境开关的**唯一登记表**（#10 + #14，2026-10-07）。

存在的理由（实测）：同一个开关的影响面原先写在两处——`tests/conftest.py` 的清空名单
（8 键）与 `evals/changedetect/env_baseline.py` 的 `PINS`（3 键），**交集只有 1**。两份
名单各自漂移，后果有数：
- 宿主会话（agent / 受限容器）把项目级开关桥进进程 ⇒ 测试与 golden 按"这台机器怎么跑"
  变红，而这些红被当成产品回归（本会话实测：`XEYO_WSC_SOFT_WATERMARK` 一族恒让 WSC
  10 条红，每次都要重新归因一遍）；
- 新增一个开关时，两份名单里至少漏一处，漏哪一处取决于"是谁加的"。

本模块只声明**事实**：键、影响面、以及**它为什么会漂移**。两个消费方各自投影，不另写名单：
  ``tests/conftest.py``                  → :func:`isolation_pins`
  ``evals/changedetect/env_baseline.py`` → :func:`snapshot_pins`

**只登记"产品开关"**。`XEYO_HOME` / `XEYO_SESSIONS_DIR` / `XEYO_JOURNAL_DIR` 这类"把落盘
钉进 tmp"的路径键**不在此列**：它们不是环境基线，而是测试场地本身（钉错会污染真实主目录，
性质与"按环境换行为"不同）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class EnvSwitch:
	"""一个会按环境改变行为的产品开关。"""

	name: str
	#: 为什么会漂移（实测数字优先）。**非空**是登记的门槛：说不清影响面的开关不该被静默豁免。
	why: str
	#: 宿主带进来会让**测试**按环境红/绿 ⇒ 用例前钉回默认面。
	affects_tests: bool = True
	#: 钉回默认面的取值；``None`` = 直接清掉（未设即默认面）。
	test_value: str | None = None
	#: 会让 **changedetect** 的 L0/L1 golden 漂移 ⇒ 比对前必须清掉。
	affects_snapshots: bool = False
	#: 已实测过的漂移层：``"l0"`` / ``"l1"``（``None`` = 未做探针，测试不实跑）。
	drift_probe: str | None = None
	#: 探针取值：设成它就能复现该层的漂移（``None`` = 无探针）。
	drift_value: str | None = None


SWITCHES: tuple[EnvSwitch, ...] = (
	EnvSwitch("XEYO_WSC_CARD_INDEX_ONLY", "明确任务检查点下以来源索引替代历史卡面；默认关", affects_snapshots=True),
	EnvSwitch("XEYO_WSC_REQUIREMENT_FLOOR", "已退休的全历史原话实验键；保留登记防宿主旧值泄漏，无运行行为"),
	EnvSwitch("XEYO_WSC_FAILURE_FACTS", "失败身份按工具/类别/声明目标，保留全部证据来源；默认关", affects_snapshots=True),
	EnvSwitch("XEYO_WSC_REQUEST_PROJECTION", "人类请求与绑定目标分层旁路，包含不可变状态契约", affects_snapshots=True),
	EnvSwitch("XEYO_WSC_STATE_CONTRACTS", "目标状态/不可变冷层/整代发布旁路改变 WSC 投影", affects_snapshots=True),
	EnvSwitch("XEYO_WSC_TASK_CONTINUITY", "已提交任务检查点与执行回执进入 WSC 投影；默认关", affects_snapshots=True),
	EnvSwitch("XEYO_WSC_MODEL_TIMING", "模型请求容量测量与 Compact 回执旁路；默认关", affects_snapshots=True),
	EnvSwitch("XEYO_EXECUTION_FACT_CONTRACTS", "环境/编辑/执行回执事实旁路改变工具结果", affects_snapshots=True),
	EnvSwitch(
		"XEYO_STALE_GOAL_RETIRE",
		"显式用户关闭声明改变新建 WSC 投影的目标种子；默认关，宿主开启会改变测试与快照",
		affects_snapshots=True,
	),
	EnvSwitch(
		"XEYO_WSC",
		"发射被 WSC 接管 ⇒ 实测全量 12 条红（test_runtime_c2 4 + test_c2_llm_summary_t8 7"
		" + test_c2_escape_hatch 1）；tests/wsc 自身免疫",
	),
	EnvSwitch(
		"XEYO_WSC_SIZE_PRUNE",
		"尺寸侧修剪接主链 ⇒ 实测 test_project_cow_c2_gain 1 条红",
	),
	EnvSwitch(
		"XEYO_WSC_USEFUL_SIG_GATE",
		"[UNRESOLVED] 准入按纯签名挡零信息签名（``退出码 N`` 一类）⇒ 实测开闸后该段 55 行降到"
		" 54 行、head 7941→7831 tok；关时不改主链。宿主开启会改投影文本与快照。",
		affects_snapshots=True,
	),
	EnvSwitch(
		"XEYO_WSC_GATE_EMITTED_BASIS",
		"发射基准换档 ⇒ 与 XEYO_WSC 同族的环境面（同批实测）",
	),
	EnvSwitch(
		"XEYO_WSC_FOLD_MIN_INTERVAL",
		"同族数值参数键（`fold_cadence_veto` 直读 env）⇒ 折叠间隔随机器变",
	),
	EnvSwitch(
		"XEYO_L5",
		"机器级 env 不参与运行时（get_value 语义）；delenv 仅兜底历史直读残留",
	),
	EnvSwitch(
		"XEYO_C2_GATE",
		"生产默认开（用户决策 2026-09）⇒ 测试显式钉 \"0\"，需 gate 开的用例自行 mem_switch",
		test_value="0",
	),
	EnvSwitch(
		"XEYO_TOOL_AGING",
		"T27 起生产默认关 ⇒ 测试显式钉 \"0\" 防机器级泄漏（test_memory_aging 自行开）",
		test_value="0",
	),
	EnvSwitch(
		"XEYO_TOOL_DENY",
		"把命名工具移出工作面 ⇒ 实测 8 文件 18 条红；清掉后同集 69 passed / 0 failed"
		"；同时漂移 L0 golden（实测 4 处）",
		affects_snapshots=True,
		drift_probe="l0",
		drift_value="Agent",
	),
	EnvSwitch(
		"XEYO_TOOL_SURFACE",
		"minimal 面 ⇒ 工具集随环境变（实测 L0 18 处）",
		affects_snapshots=True,
		drift_probe="l0",
		drift_value="minimal",
	),
	EnvSwitch(
		"XEYO_T_NOW_SKIP",
		"块级旁路 ⇒ 注入面随环境变（实测 L1 19 处）",
		affects_snapshots=True,
		drift_probe="l1",
		drift_value="env_facts",
	),
)


#: **已退场**的开关名：代码里已不再读取，但宿主机器 env 里可能仍有残留。
#: 与 :data:`SWITCHES` 分开登记的理由：它们不需要隔离（没人读），却需要**可见**——
#: 否则每次检查都要人肉重判"这个键还算数吗"（实测：11 个"未登记"键里混着两个化石，
#: 每次都被当成可疑项重新归因一遍）。
RETIRED: tuple[tuple[str, str], ...] = (
	("XEYO_WSC_SOFT_WATERMARK", "2026-10-08 退场：软水位恒 0（memory/wsc_watermark.soft_watermark_tokens）"),
	("XEYO_CONTEXT_COMPACT_RATIO", "2026-10-08 退场：压缩比恒 0.85（memory/runtime.context_compact_ratio）"),
)


def retired_names() -> tuple[str, ...]:
	"""已退场开关名（升序）。"""
	return tuple(sorted(name for name, _why in RETIRED))


def retired_present(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
	"""本进程 env 里**仍有残留**的已退场键（宿主带过来的化石）。"""
	env = os.environ if environ is None else environ
	return tuple(name for name in retired_names() if name in env)


def env_buckets(environ: Mapping[str, str] | None = None) -> dict[str, tuple[str, ...]]:
	"""把进程里"像产品开关"的键分三桶：``live`` / ``retired`` / ``unknown``。

	``live`` = 已登记且在本进程 env 里；``retired`` = 已退场但宿主 env 仍有；
	``unknown`` = 没登记过的 ``XEYO_*``（真正需要人看一眼的那桶）。
	"""
	env = os.environ if environ is None else environ
	return {
		"live": tuple(sorted(s.name for s in SWITCHES if s.name in env)),
		"retired": retired_present(env),
		"unknown": unregistered(env),
	}


def isolation_pins() -> tuple[tuple[str, str | None], ...]:
	"""`tests/conftest.py` 的投影：``(键, 钉值)``；``None`` = 清掉该键。

	名字刻意**不带** ``test_`` 前缀：pytest 会把它当测试函数收集（实测 warning
	``PytestReturnNotNoneWarning: … returned <class 'tuple'>``——假绿，且它一旦抛错
	就会变成一条与产品无关的假红）。
	"""
	return tuple((s.name, s.test_value) for s in SWITCHES if s.affects_tests)


def snapshot_pins() -> tuple[tuple[str, str], ...]:
	"""`env_baseline.PINS` 的投影：``(键, 原因)``（与原 `PINS` 形态一致，调用方无需改）。"""
	return tuple((s.name, s.why) for s in SWITCHES if s.affects_snapshots)


#: 场地键后缀：这些 env 只决定"东西落在哪"，不改变行为（不是环境基线）。
_PLACE_TAILS: tuple[str, ...] = ("_DIR", "_HOME", "_ROOT", "_PATH", "_FILE", "_TMP")

_ENV_PREFIX = "XEYO_"


def unregistered(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
	"""本进程里「像是产品开关、却没登记」的键（升序）。

	分类是**文本规则，不是名单**（因此不会自己漂移）：``XEYO_*`` 且不以场地后缀结尾、
	且不在 :data:`SWITCHES` 里 ⇒ 可疑。

	存在理由（#14 前半之后仍开着的缺口）：新开关若没人登记，就仍会按环境漂移，而"没人登记"
	这件事原先**没有任何出口**——只能靠下一次红慢慢二分。这里把它变成一条可见事实。
	措辞刻意只报事实（不写"应该登记"）：可见即约束，判不判由人。
	"""
	env = os.environ if environ is None else environ
	# 已退场键单列一桶（:func:`retired_present`）：它们不是"没人登记的新开关"。
	known = {s.name for s in SWITCHES} | set(retired_names())
	out: list[str] = []
	for key in env:
		if not key.startswith(_ENV_PREFIX):
			continue
		if key in known or key.endswith(_PLACE_TAILS):
			continue
		out.append(key)
	return tuple(sorted(out))
