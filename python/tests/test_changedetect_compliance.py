"""Compliance 扫描器：散文豁免不得把真分支一起放过（2026-10-07）。

背景：规则原先对新增行一律 `re.search`，于是"注释里描述同一条通道"与"按评测
环境分支"共用同一个正则——实测 3 条 R2 fail 全落在 `#` 注释上。豁免散文之后，
本文件钉住两件相反的事：散文不报，**真分支与字符串字面量照报**。
"""

from __future__ import annotations

from pathlib import Path

from evals.changedetect import compliance


def _diff(*added: str, where: str = "b/python/x.py") -> str:
	body = "".join(f"+{ln}\n" for ln in added)
	return f"--- a/{where[2:]}\n+++ {where}\n@@ -0,0 +1,{len(added)} @@\n{body}"


def test_pure_comment_is_exempt() -> None:
	"""注释不执行、也不进模型可见文本 ⇒ 不该判（本条正是原假阳的形状）。"""
	hits = compliance.scan_added_lines(_diff("# 容器路由：分支在 tools/fileio/text.py 汇聚"))
	assert hits == [], [h.to_dict() for h in hits]


def test_real_branch_is_still_caught() -> None:
	"""对照：同一类词只要落在代码分支上，R2 必须照样报。

	注意规则词是 `container_rout`（不是项目里的 `_routed_container()` 那种倒装）——
	测试用规则词本身，免得把"规则没覆盖某个命名"误当成"豁免生效"。
	"""
	hits = compliance.scan_added_lines(_diff("if container_routed(path):"))
	assert [h.rule for h in hits] == ["R2"], [h.to_dict() for h in hits]


def test_inline_comment_is_not_exempt() -> None:
	"""方向性：宁可多报不可漏报——行尾注释照报。"""
	hits = compliance.scan_added_lines(_diff("x = 1  # 容器路由"))
	assert [h.rule for h in hits] == ["R2"], [h.to_dict() for h in hits]


def test_doc_file_is_exempt() -> None:
	"""docs/ 里的散文不是模型可见文本。"""
	hits = compliance.scan_added_lines(_diff("建议你先读 README", where="b/docs/x.md"))
	assert hits == [], [h.to_dict() for h in hits]


def test_docstring_is_exempt_but_string_literal_is_not(tmp_path: Path) -> None:
	""".py 里按 ast 取 docstring 行号：docstring 豁免，字符串字面量不豁免。"""
	# 触发词分片拼接：本文件自身不得含连续触发词，否则会被自己的规则误报（自指噪声）。
	phrase = "必" + "须先" + "物理解析"
	(tmp_path / "m.py").write_text(
		f'"""模块说明：{phrase}。"""\n\nX = "{phrase}"\n',
		encoding="utf-8",
	)
	doc = compliance.scan_added_lines(
		f'--- a/m.py\n+++ b/m.py\n@@ -0,0 +1,1 @@\n+"""模块说明：{phrase}。"""\n',
		root=tmp_path,
	)
	assert doc == [], [h.to_dict() for h in doc]
	lit = compliance.scan_added_lines(
		f'--- a/m.py\n+++ b/m.py\n@@ -0,0 +3,1 @@\n+X = "{phrase}"\n',
		root=tmp_path,
	)
	assert [h.rule for h in lit] == ["R3"], [h.to_dict() for h in lit]


def test_iter_added_tracks_new_file_line_numbers() -> None:
	"""行号是新文件行号：上下文行推进、删除行不推进（否则 docstring 判定错位）。"""
	diff_text = (
		"--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,4 @@\n"
		" import os\n-b = 1\n+# c\n+A = 1\n+B = 2\n"
	)
	assert [
		(lineno, text) for _, lineno, text in compliance._iter_added(diff_text)
	] == [(2, "# c"), (3, "A = 1"), (4, "B = 2")]


# -- 行内自豁免（X1/#12）------------------------------------------------------


def test_inline_allow_with_reason_is_exempt() -> None:
	"""带理由的行内豁免：该行不报，且理由被记进 exempted（可见即约束）。"""
	phrase = "容器" + "路由"
	exempted: list[dict] = []
	hits = compliance.scan_added_lines(
		_diff(f'ROUTE = "{phrase}"  # compliance: allow(规则词表，不是分支)'),
		exempted=exempted,
	)
	assert hits == [], [h.to_dict() for h in hits]
	assert [e["reason"] for e in exempted] == ["规则词表，不是分支"]


def test_inline_allow_without_reason_still_reports() -> None:
	"""理由非空才生效：空括号是空账 ⇒ 照报、且不计入豁免。"""
	phrase = "容器" + "路由"
	exempted: list[dict] = []
	hits = compliance.scan_added_lines(
		_diff(f'ROUTE = "{phrase}"  # compliance: allow()'),
		exempted=exempted,
	)
	assert [h.rule for h in hits] == ["R2"], [h.to_dict() for h in hits]
	assert exempted == []


def test_exemption_is_line_scoped() -> None:
	"""只豁免所在那一行：下一行同样命中仍要报。"""
	phrase = "容器" + "路由"
	exempted: list[dict] = []
	hits = compliance.scan_added_lines(
		_diff(f'A = "{phrase}"  # compliance: allow(词表)', f'B = "{phrase}"'),
		exempted=exempted,
	)
	assert [h.rule for h in hits] == ["R2"], [h.to_dict() for h in hits]
	assert len(exempted) == 1


def test_exempted_count_visible_and_schema_stable() -> None:
	"""计数可见；不给 exempted 时 summary 的 schema 与改动前逐键一致。"""
	with_exempt = compliance.summarize(
		[], exempted=[{"where": "b/x.py", "line": 1, "reason": "r"}]
	)
	assert with_exempt["exempted_count"] == 1
	assert with_exempt["hit_count"] == 0
	assert "exempted_count" not in compliance.summarize([])
