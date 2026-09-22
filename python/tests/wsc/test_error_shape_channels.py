"""错误判定的**形状通道**夹具（回归锚）。

覆盖两条此前漏判的真实形状，以及它们各自的假阳性护栏：

1. **回执信封的结构化退出码**（Codex 形态）：``Script completed`` + 正文
   ``{"chunk_id":…,"exit_code":1,…,"output":"…"}``。头部 ``completed`` 说的是"信封送达"，
   不是命令退出状态 ⇒ 真码在 JSON 里。实测两批语料里该形状漏判 13 条。
2. **``apply_patch verification failed:``**：写**没落地**这件事本身是模型最不该丢的事实。
   实测漏判 5 条（``workspace_window_layout``）。

护栏与既有判据同源：头部 ``Process exited with code N`` 仍是最高权威；被运行程序自己
打印的 ``exit_code``（在 ``"output"`` 之后）不算回执。
"""

from __future__ import annotations

from typing import Any

from synaptic.graph import (
	Graph,
	_HARD_ERR_MARKERS,
	_STRONG_ERR_MARKERS,
	_receipt_verdict,
	_status_verdict,
	build_graph,
)
from synaptic.types import KIND_TOOL_RESULT
from tests.wsc._fixtures import msg_asst_use, msg_tool, msg_user

# ---- 真实语料形状（逐字取自 TerminalBench evidence / codex_holdout_v1）-----------

RECEIPT_FAIL = (
	"Script completed\nWall time 1.1 seconds\nOutput:\n\n"
	'{"chunk_id":"87d11d","wall_time_seconds":0.3659815,"exit_code":1,'
	'"original_token_count":107,"output":"Mockito is currently self-attaching"}'
)

RECEIPT_OK = (
	"Script completed\nWall time 0.4 seconds\nOutput:\n\n"
	'{"chunk_id":"a1","wall_time_seconds":0.4,"exit_code":0,'
	'"original_token_count":12,"output":"all good"}'
)

#: 顶层 exit_code=0，但**被运行的程序自己**在 output 里打了一层含 exit_code 的 JSON。
#: 那属于正文内容，按 `_status_verdict` 同源的理由不得当判据。
RECEIPT_INNER_PAYLOAD = (
	"Script completed\nWall time 0.5 seconds\nOutput:\n\n"
	'{"chunk_id":"b2","wall_time_seconds":0.5,"exit_code":0,"original_token_count":9,'
	'"output":"{\\"concurrency\\":1000,\\"exit_code\\":1,\\"ok\\":41}"}'
)

APPLY_PATCH_FAIL = (
	"apply_patch verification failed: Failed to find expected lines in "
	"D:\\repo\\cli\\src\\index.css:\n.xy-perm-allow:hover {\n  background: var(--xy-accent);\n}"
)


def _result_node(g: Graph) -> Any:
	hits = [n for n in g.nodes if n.kind == KIND_TOOL_RESULT]
	assert hits, "图里没有 tool_result 节点"
	return hits[-1]


def _one(name: str, inp: dict[str, Any], output: str, *, flag: bool | None) -> Any:
	msgs: list[dict[str, Any]] = [msg_user("跑一下"), msg_asst_use("c1", name, inp)]
	if flag is None:
		msgs.append({
			"role": "user",
			"name": name,
			"content": [{"type": "tool_result", "tool_use_id": "c1", "content": output}],
		})
	else:
		msgs.append(msg_tool("c1", name, output, is_error=flag))
	return _result_node(build_graph(msgs))


# ---- 通道 1：回执信封 ----------------------------------------------------------

def test_receipt_nonzero_exit_is_error_despite_explicit_false_flag():
	"""Codex 把每条输出都标 is_error:false，信封里的 exit_code:1 必须把它抬回失败。"""
	for flag in (False, None):
		n = _one("exec_command", {"cmd": "npm test"}, RECEIPT_FAIL, flag=flag)
		assert n.is_error, f"flag={flag} 时信封退出码漏判"
		# 签名必须是**可读的语义前缀形态**：`[UNRESOLVED]` 只收 `is_error and error_sig`
		# 的节点，签名落成裸 `1` 或空串都等于这条失败仍然隐形。
		assert n.error_sig == "退出码 1", n.error_sig


def test_receipt_zero_exit_is_not_error():
	assert _receipt_verdict(RECEIPT_OK) is False
	assert not _one("exec_command", {"cmd": "pytest"}, RECEIPT_OK, flag=False).is_error


def test_inner_payload_exit_code_is_not_a_verdict():
	"""程序自己打印的同名键在 `"output"` 之后 ⇒ 不是回执，不得据此判失败。"""
	assert _receipt_verdict(RECEIPT_INNER_PAYLOAD) is False
	assert not _one("exec_command", {"cmd": "bench"}, RECEIPT_INNER_PAYLOAD, flag=False).is_error


def test_head_status_line_outranks_receipt_envelope():
	"""次序契约：头部 `Process exited with code 0` 是最高权威，信封正文的 exit_code:1 不得越过它。"""
	text = (
		"Process exited with code 0\nWall time: 0.4 seconds\nOriginal token count: 30\nOutput:\n"
		+ RECEIPT_FAIL[RECEIPT_FAIL.find('{"chunk_id"'):]
	)
	assert _status_verdict(text) is False
	assert _one("exec_command", {"cmd": "cat log.txt"}, text, flag=False).is_error is False


def test_receipt_channel_does_not_demote_an_earlier_detection():
	"""新通道只会补判，不得把已判出的失败抹成成功（两条语料 base=280 → new=298，反减必须为 0）。"""
	assert _status_verdict("Process exited with code 2\nboom") is True
	assert _one("exec_command", {"cmd": "rg"}, "Process exited with code 2\nboom", flag=False).is_error


# ---- 通道 2：apply_patch 写失败 -------------------------------------------------

def test_apply_patch_verification_failed_promoted_despite_false_flag():
	for flag in (False, None):
		n = _one("apply_patch", {"input": "*** Update File: index.css"}, APPLY_PATCH_FAIL, flag=flag)
		assert n.is_error, f"flag={flag} 时 apply_patch 写失败漏判"
		assert "verification failed" in n.error_sig.lower(), n.error_sig


# ---- 假阳性护栏（既有事故回归锚：成功输出里引用错误文本）---------------------

def test_quoted_permission_denied_source_under_code_0_stays_clean():
	text = (
		"Process exited with code 0\nOutput:\n"
		'if os.path.isdir(p):\n    raise PermissionError("permission denied")\n'
	)
	assert _status_verdict(text) is False
	assert _one("exec_command", {"cmd": "cat gate.py"}, text, flag=False).is_error is False


def test_hard_markers_are_subset_of_strong_markers():
	"""两份名单的一致性：升格通道用的硬标记必须也是文本通道认得的（否则同一形状两套口径）。"""
	assert set(_HARD_ERR_MARKERS) <= set(_STRONG_ERR_MARKERS), (
		set(_HARD_ERR_MARKERS) - set(_STRONG_ERR_MARKERS)
	)
