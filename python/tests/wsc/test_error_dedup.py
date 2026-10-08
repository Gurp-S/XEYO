"""同签名去重契约：同一失败不在 ``[UNRESOLVED]`` 与 ``[DECISIONS]`` 各付一份注意力。

现场（本会话热摘要实测）：``ParameterBindingException: …`` 同时出现在
``[UNRESOLVED] 未解决: …`` 与 ``[DECISIONS] 错误结果: Bash 失败：…``，连
``Read(file_path=…)`` 句柄都一样——信息量 1 份，注意力付 2 份（``[PRUNED]`` 里还有第 3 份）。

口径：去重只去**签名正文**；``{tool} 对 {target} 失败`` 的现场归属、``files=`` 清单、
可恢复句柄一律保留（合并后仍要保留有效事实及其来源）。
"""

from __future__ import annotations

from synaptic.assemble import render_decisions
from synaptic.types import PruneCard

_SIG = "AssertionError: expected 1000 got 3000"


def _card() -> PruneCard:
	return PruneCard(
		card_id="c1",
		conclusion=f"Bash 对 src/auth.ts 失败：{_SIG}",
		# 多文件卡：结论只内联 ``files[0]``，第二个路径靠 ``files=`` 补出（既有口径，
		# 见 ``render_decisions`` 的 docstring）——去重不得把这条通道一并掐掉。
		files=("src/auth.ts", "src/proxy.ts"),
		error_sig=_SIG,
		nodes=(7,),
	)


def _line(pairs: list[tuple[str, str]]) -> str:
	assert len(pairs) == 1, f"卡片行数不对：{pairs}"
	return pairs[0][1]


def test_signature_is_not_repeated_when_already_unresolved() -> None:
	line = _line(render_decisions((_card(),), dup_sigs=frozenset({_SIG})))
	assert _SIG not in line, f"签名被重复渲染了：{line!r}"
	assert "dup=unresolved" in line, "没有留下去重事实标记（无法归因）"
	assert "files=" in line, "files 清单被一起删掉了"


def test_increment_and_handle_survive_the_merge() -> None:
	"""增量（现场归属）与可恢复句柄不得因去重而消失。"""
	line = _line(render_decisions((_card(),), dup_sigs=frozenset({_SIG})))
	assert "Bash 对 src/auth.ts 失败" in line, "tool/target 的现场归属丢了"
	assert ("Read(" in line) or ("expand(" in line), f"可恢复句柄丢了：{line!r}"


def test_positive_control_keeps_the_signature() -> None:
	"""正控：不在 ``[UNRESOLVED]`` 里的签名必须照常带正文，别把去重做成永久删除。"""
	line = _line(render_decisions((_card(),)))
	assert _SIG in line
	assert "dup=unresolved" not in line


def test_only_the_matching_signature_is_deduped() -> None:
	"""按签名精确去重：另一条签名不受影响。"""
	other = PruneCard(
		card_id="c2",
		conclusion="Bash 对 src/other.ts 失败：ImportError: cannot import name 'X'",
		files=("src/other.ts",),
		error_sig="ImportError: cannot import name 'X'",
		nodes=(9,),
	)
	pairs = render_decisions((other,), dup_sigs=frozenset({_SIG}))
	line = _line(pairs)
	assert "ImportError: cannot import name 'X'" in line
	assert "dup=unresolved" not in line
