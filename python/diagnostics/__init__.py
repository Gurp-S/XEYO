"""XEYO 诊断中心：把已有证据按既有身份合并成可核查的运行报告。

不新建事件总线、不调用模型、不参与调度。写入只落在
``xeyo_data_root()/diagnostics/``，读取只复用 audit / transcript / usage /
projection manifest / jobs 这些既有权威来源。
"""

from __future__ import annotations

from diagnostics.collect import RunEvidence, collect_run, list_runs
from diagnostics.fault_split import attribute_fault
from diagnostics.identity import EvidenceRef, Finding, SCHEMA_VERSION
from diagnostics.report import to_json, to_markdown
from diagnostics.rules import RULESET_VERSION, evaluate_run

__all__ = [
	"Finding",
	"RunEvidence",
	"SCHEMA_VERSION",
	"RULESET_VERSION",
	"EvidenceRef",
	"attribute_fault",
	"collect_run",
	"evaluate_run",
	"list_runs",
	"to_json",
	"to_markdown",
]
