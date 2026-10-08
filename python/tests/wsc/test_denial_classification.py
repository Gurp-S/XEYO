"""拒绝分类契约：权限层拒绝 = 限制事实，既不进 [UNRESOLVED]，也不许当"已解决"。

口径（本会话用户约束，逐条对应）：

- 「⑥拒绝分类可以做，**拒绝结果不能直接等同目标终态**」⇒ 拒绝节点仍 ``is_error``，
  ``[UNRESOLVED]`` 里不再挂它，且行里不得出现成功标记；
- 「移出错误段后，必须保留仍有效的限制事实及其来源」⇒ 进 ``[CONSTRAINTS]``，
  行内带 ``source=#idx``（稳定引用，可回读原文）；
- 「`engine`、`tools`、短文件名也可能是真实目标，不能仅凭长度或通用词过滤」⇒
  判据只认拒绝措辞本身，不做长度/通用词裁剪。
"""

from __future__ import annotations

from synaptic.assemble import H_CONSTRAINTS, build_pins, pin_group
from synaptic.graph import build_graph
from synaptic.seeds import collect_seeds
from synaptic.verdicts import is_terminal_denial, partition_signatures
from wsc._fixtures import msg_asst_use, msg_tool, msg_user

_DENIED_IDX = 2


def _mixed_session() -> tuple[object, list[dict]]:
	"""一条被拒的写 + 一条普通失败（正控）。"""
	msgs = [
		msg_user("修登录超时"),
		msg_asst_use("w1", "Write", {"path": "src/legacy.ts", "content": "x"}),
		msg_tool("w1", "Write", "write failed: path_denied", is_error=True),
		msg_asst_use("b1", "Bash", {"command": "npm test"}),
		msg_tool("b1", "Bash", "AssertionError: expected 1000 got 3000", is_error=True),
	]
	return build_graph(msgs), msgs


def test_denial_leaves_unresolved_and_keeps_its_signature() -> None:
	graph, msgs = _mixed_session()
	denied = graph.node(_DENIED_IDX)
	assert denied is not None and denied.error_sig, "前提失效：拒绝结果没有签名可分类"
	assert is_terminal_denial(denied.error_sig), "path_denied 未被判成拒绝族"

	seeds = collect_seeds(graph, msgs, {})
	assert not any("path_denied" in s for s in seeds.unresolved_errors), (
		"权限层拒绝仍挂在 [UNRESOLVED] 里（每次恢复都要人工重裁）"
	)
	assert any("path_denied" in d for d in seeds.denials), "限制事实被丢弃了"
	assert seeds.denial_sources == (_DENIED_IDX,), "限制事实没有稳定来源引用"


def test_denial_renders_under_constraints_with_source() -> None:
	graph, msgs = _mixed_session()
	pins = [p for p in build_pins(collect_seeds(graph, msgs, {})) if p.key.startswith("denial:")]
	assert len(pins) == 1, f"限制条目数不对：{[p.key for p in pins]}"
	pin = pins[0]
	assert pin_group(pin) == H_CONSTRAINTS, "限制事实没落在 [CONSTRAINTS]"
	assert f"source=#{_DENIED_IDX}" in pin.text, "限制事实丢了来源引用"
	assert "path_denied" in pin.text, "限制事实的原文签名被改写"


def test_denial_is_never_reported_as_resolved() -> None:
	"""反证：分类不得升级成"已解决"——标记是禁止的，节点事实是硬证据。"""
	graph, msgs = _mixed_session()
	pin = next(p for p in build_pins(collect_seeds(graph, msgs, {})) if p.key.startswith("denial:"))
	low = pin.text.lower()
	assert not any(m in low for m in ("passed", "success", "已解决", "通过", "ok")), (
		f"限制事实被写成了成功语气：{pin.text!r}"
	)
	denied = graph.node(_DENIED_IDX)
	assert denied is not None and denied.is_error, "拒绝节点的事实被改写了"


def test_ordinary_error_stays_unresolved() -> None:
	"""正控：判据收窄不得把普通失败一起移出 [UNRESOLVED]。"""
	graph, msgs = _mixed_session()
	seeds = collect_seeds(graph, msgs, {})
	assert any("AssertionError" in s for s in seeds.unresolved_errors), (
		"普通失败被误判成限制事实"
	)
	assert not any("AssertionError" in d for d in seeds.denials)


def test_judgement_is_text_based_and_fail_open() -> None:
	"""(a) 只认措辞本身，不靠长度/通用词；(b) 异常输入不抛（fail-open 回未解决侧）。"""
	assert is_terminal_denial("write failed: path_denied")
	assert is_terminal_denial("Permission denied: protected_metadata")
	assert is_terminal_denial("Access is denied") or is_terminal_denial("Access to the path 'x' is denied")
	assert not is_terminal_denial("engine")
	assert not is_terminal_denial("tools")
	assert not is_terminal_denial("")
	assert not is_terminal_denial("AssertionError: 1 != 2")

	unresolved, denials = partition_signatures(["path_denied", "AssertionError: x"])
	assert unresolved == ["AssertionError: x"] and denials == ["path_denied"]
	assert partition_signatures([]) == ([], [])
