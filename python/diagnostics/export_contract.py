"""把诊断层的机器枚举导出成 TS 契约，供界面做"每个值都有中文说法"的门禁。

为什么要生成文件而不是各写各的：

- ``collect.BOUNDARIES`` 与 GUI ``model.ts`` 的 ``BOUNDARY_ORDER`` 是同一份清单的两份手抄；
- ``GAP_REASON_LABEL`` 的键要覆盖 ``collect.add_gap(...)`` 的第二个参数，而那些码散在
  采集器各处 —— 本会话就已经"撞上才补"过两次（recovered_outside_window、
  not_found_in_full_file）。真实载荷冒烟测试里的机器码清单也是手抄的，
  加了新码不会变红。

这里把"生产者到底会发出哪些值"变成一份提交进仓库的清单：
python 侧有 freshness 测试（改了枚举没重导就红），GUI 侧有 ratchet 测试
（新增枚举值而界面没有中文说法就红）。扫描而非另立常量表是刻意的 ——
再写一份"权威清单"就等于再造一个会忘记更新的地方。

用法（在 ``python/`` 目录下）::

    py -3.11 -m diagnostics.export_contract
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from diagnostics import collect, fault_split, rules

_PKG_DIR = Path(__file__).resolve().parent
# python/diagnostics -> python -> 仓库根
_REPO_ROOT = _PKG_DIR.parents[1]
_OUTPUTS: tuple[Path, ...] = (_REPO_ROOT / "gui" / "src" / "generated" / "diagContract.ts",)

# 生产者发出但界面必须能说的东西，全部从代码里扫出来：
_GAP_CALL_RX = re.compile(r"\badd_gap\(")
_REASON_LITERAL_RX = re.compile(r"[\"']([a-z][a-z0-9_]{2,})[\"']")
_STR_CONST_RX = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*[\"']([a-z][a-z0-9_]{2,})[\"']", re.M)
_BARE_IDENT_RX = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_SHOWN_STATE_RX = re.compile(r"\"state\"\]\s*==\s*[\"']([a-z_]+)[\"']")
# 投影不变量旗标：产生方在引擎里，读取方在诊断层。两边各写各的就会静默漏结论 ——
# ``canonical_unpaired_tool_calls`` 就被漏过（2026-09-25 对照两张清单才发现：引擎每次
# 投影都在算它，规则集里没有任何一条读它，界面上于是永远显示"没有这类问题"）。
_ENGINE_MANIFEST_SRC = _REPO_ROOT / "python" / "engine" / "projection_manifest.py"
_INVARIANT_APPEND_RX = re.compile(r"invariant_errors\.append\(\s*f?[\"']([a-z][a-z0-9_]{3,})")
# 读过但生产者已经不再写的名字：只能是判据改版前留在磁盘上的旗标。
LEGACY_INVARIANT_NAMES = frozenset({"spill_reference_mismatch"})


def _top_level_args(text: str, open_index: int) -> list[str]:
	"""从 ``(`` 的下标起，按顶层逗号切参数（括号、方括号、引号内不切）。"""
	args: list[str] = []
	depth = 1  # 已经站在那个 `(` 里面
	start = open_index + 1
	i = start
	quote = ""
	while i < len(text):
		ch = text[i]
		if quote:
			if ch == "\\":
				i += 2
				continue
			if ch == quote:
				quote = ""
		elif ch in "\"'":
			quote = ch
		elif ch in "([{":
			depth += 1
		elif ch in ")]}":
			depth -= 1
			if depth == 0:
				args.append(text[start:i])
				return args
		elif ch == "," and depth == 1:
			args.append(text[start:i])
			start = i + 1
		i += 1
	return []


def _string_constants() -> dict[str, str]:
	"""``NAME = "value"`` 形式的模块级字符串常量（原因码常以常量传入，如 NOT_CAPTURED）。"""
	table: dict[str, str] = {}
	for path in _py_sources():
		text = path.read_text(encoding="utf-8", errors="replace")
		for name, value in _STR_CONST_RX.findall(text):
			table.setdefault(name, value)
	return table


def scan_gap_reasons() -> list[dict[str, str]]:
	"""``add_gap(boundary, reason, ...)`` 会发出的全部原因码（按边界去重排序）。

	第二个参数**整段**里既取字面量也取字符串常量名：
	- ``("a" if found else "b")`` 这种条件写法必须两个都扫到 —— 只看"字面量直接当参数"
	  的版本会静默漏掉原因码，而那正是这道门要防的事（本会话就是这么漏了
	  ``not_found_in_full_file``）；
- ``add_gap("adapter", NOT_CAPTURED, ...)`` 用常量传值，光扫字面量同样会漏。
	"""
	constants = _string_constants()
	seen: dict[tuple[str, str], dict[str, str]] = {}
	for path in _py_sources():
		text = path.read_text(encoding="utf-8", errors="replace")
		for match in _GAP_CALL_RX.finditer(text):
			args = _top_level_args(text, match.end() - 1)
			if len(args) < 2:
				continue
			boundary = _REASON_LITERAL_RX.search(args[0])
			if boundary is None:
				continue
			reasons = set(_REASON_LITERAL_RX.findall(args[1]))
			reasons.update(constants[name] for name in _BARE_IDENT_RX.findall(args[1]) if name in constants)
			for reason in reasons:
				seen.setdefault((boundary.group(1), reason), {"boundary": boundary.group(1), "reason": reason})
	return [seen[k] for k in sorted(seen)]


def _py_sources() -> list[Path]:
	return sorted(p for p in _PKG_DIR.glob("*.py") if p.name != "export_contract.py")


def scan_shown_states() -> list[str]:
	"""``_shown_to_model`` 会返回的 state 值：以 ``_SHOWN_TEXT`` 为正本。

	刻意只取正本，不并入代码里比较用的字面量 —— 后者还混着 `_required_action_unmet`
	那套另一码事的状态（action_missing / blocked_by_permission …），它们不进界面标签表。
	"有分支比较某个 state 却不在正本里"这种不一致交给 python 侧的测试钉。
	"""
	return sorted(fault_split._SHOWN_TEXT)


def scan_invariant_names() -> dict[str, list[str]]:
	"""投影旗标两份清单：引擎写下的名字、诊断层读到的名字。

	刻意扫描而不是另立常量表：常量表就是又一个会忘记更新的地方。
	"""
	written: list[str] = []
	if _ENGINE_MANIFEST_SRC.exists():
		text = _ENGINE_MANIFEST_SRC.read_text(encoding="utf-8", errors="replace")
		written = sorted(set(_INVARIANT_APPEND_RX.findall(text)))
	diag_text = "\n".join(
		path.read_text(encoding="utf-8", errors="replace") for path in _py_sources()
	)

	def _read(name: str) -> bool:
		return f'"{name}"' in diag_text or f"'{name}'" in diag_text

	read = sorted({n for n in written if _read(n)})
	return {
		"written": written,
		"read": read,
		"unclaimed": sorted({n for n in written if n not in set(read)}),
		# 生产者已不再写、诊断层仍在读的旧旗标（判据改版前留在磁盘上的那些）。
		"legacy_read": sorted({n for n in LEGACY_INVARIANT_NAMES if _read(n)}),
	}


def scan_payload_keys() -> dict[str, list[str]]:
	"""后端**会给**的字段名（按分组），供界面侧棘轮保证"给了就有人读"。

	为什么活取而不是正则：这些字典里有一半是按运行内容条件添加的，
	只看源码字面量会漏；所以直接构造一次最小 payload 取回真实键。
	空运行 + 一条已确认发现 + 一个带结果的模型请求，两次的键取并集。
	"""
	from diagnostics import report
	from diagnostics.collect import RunEvidence
	from diagnostics.identity import CONFIRMED_FAULT, EvidenceRef, Finding

	finding = Finding(
		rule_id="gate_probe",
		rule_version=1,
		phenomenon="探针",
		boundary="model_request",
		component="探针",
		status=CONFIRMED_FAULT,
		evidence=[EvidenceRef(source="audit", locator="audit.jsonl", ref_id="L1", detail="probe")],
		impact="探针",
		coverage_gap="探针",
		allowed_conclusion="探针",
	)
	groups: dict[str, set[str]] = {
		"finding": set(finding.to_dict()),
		"evidence": set((finding.to_dict().get("evidence") or [{}])[0]),
		"fault": set(),
		"attribution": set(),
		"usage_summary": set(),
	}
	for run in (
		RunEvidence(session_id="probe", turn_id="t1"),
		RunEvidence(session_id="probe", turn_id="t1"),
	):
		doc = report.build_report(run, [] if not groups["fault"] else [finding])
		groups["fault"] |= set(doc.get("fault") or {})
		groups["attribution"] |= set(doc.get("attribution") or {})
		groups["usage_summary"] |= set(doc.get("usage_summary") or {})
	return {name: sorted(keys) for name, keys in sorted(groups.items())}


def collect_contract() -> dict[str, Any]:
	return {
		"boundaries": [{"name": n, "label": l} for n, l in collect.BOUNDARIES],
		"ruleIds": [r.rule_id for r in rules.RULES],
		"gapReasons": scan_gap_reasons(),
		"shownStates": scan_shown_states(),
		"parties": sorted(fault_split.PARTY_LABEL),
		"payloadKeys": scan_payload_keys(),
	}


def render(contract: dict[str, Any]) -> str:
	boundaries = "\n".join(
		f"\t{{name: {b['name']!r}, label: {b['label']!r}}},".replace("'", "'") for b in contract["boundaries"]
	)
	gap = "\n".join(f"\t{{boundary: {g['boundary']!r}, reason: {g['reason']!r}}}," for g in contract["gapReasons"])
	rule_ids = "\n".join(f"\t{r!r}," for r in contract["ruleIds"])
	shown = "\n".join(f"\t{s!r}," for s in contract["shownStates"])
	parties = "\n".join(f"\t{p!r}," for p in contract["parties"])
	payload = "\n".join(
		f"\t{name}: [" + ", ".join(repr(k) for k in keys) + "]," for name, keys in contract["payloadKeys"].items()
	)
	return (
		"/**\n"
		" * 由 `py -3.11 -m diagnostics.export_contract` 生成 —— 不要手改。\n"
		" *\n"
		" * 内容是诊断层生产者**实际会发出**的枚举值（扫描 add_gap 调用、BOUNDARIES、\n"
		" * RULES、_SHOWN_TEXT 得到）。界面的 ratchet 测试用它保证：新增枚举值而没有\n"
		" * 中文说法时，构建期就红，而不是等用户看到 `recovered_outside_window`。\n"
		" */\n"
		"\n"
		"export type DiagContractGapReason = {boundary: string; reason: string};\n"
		"\n"
		"export const DIAG_BOUNDARIES: ReadonlyArray<{name: string; label: string}> = [\n"
		f"{boundaries}\n"
		"];\n"
		"\n"
		"export const DIAG_RULE_IDS: readonly string[] = [\n"
		f"{rule_ids}\n"
		"];\n"
		"\n"
		"export const DIAG_GAP_REASONS: ReadonlyArray<DiagContractGapReason> = [\n"
		f"{gap}\n"
		"];\n"
		"\n"
		"export const DIAG_SHOWN_STATES: readonly string[] = [\n"
		f"{shown}\n"
		"];\n"
		"\n"
		"export const DIAG_PARTIES: readonly string[] = [\n"
		f"{parties}\n"
		"];\n"
		"\nexport const DIAG_PAYLOAD_KEYS: Readonly<Record<string, readonly string[]>> = {\n"
		f"{payload}\n"
		"};\n"
	)


def main() -> None:
	contract = collect_contract()
	text = render(contract)
	for path in _OUTPUTS:
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(text, encoding="utf-8", newline="\n")
		print(f"wrote {path} ({len(text)} chars)")


if __name__ == "__main__":
	main()
