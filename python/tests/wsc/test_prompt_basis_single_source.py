"""折叠账行的 prompt 量：唯一口径 + 来源标签（``memory.prompt_basis``）。

事故（10 倍）：账行 ``input_tokens`` 原落 ``token_len(json.dumps(messages))``——**投影前原史**，
与"实发 prompt"同名却不同源。实测同一会话同一时刻账上 265k、厂商 receipt 27k。
同类事故第一例是 ``_extension_prompt_tokens`` 的 2.5~5 倍（靠口径旗标修，见
``test_emitted_basis_and_prune``）。本文件锁三条：实发优先、无 receipt 时带标回退且 fail-open、
账行不再出现无来源标签的裸 ``input_tokens``。
"""

from __future__ import annotations

import json
from pathlib import Path

from memory import prompt_basis
from memory.working import WorkingSnapshot

REPO_PY = Path(__file__).resolve().parents[2]

RECEIPT = 27_252  # 本会话厂商最后一枪实发 prompt_tokens（usage/events.jsonl）


def _msgs(n: int, size: int) -> list[dict]:
	return [{"role": "user", "content": f"{i}:" + "x" * size} for i in range(n)]


def test_receipt_wins_and_is_labelled() -> None:
	from memory.runtime import _prompt_account

	w = WorkingSnapshot(session_id="sess_basis_receipt", last_prompt_tokens=RECEIPT)
	account = _prompt_account(_msgs(30, 6000), w)
	assert account["input_tokens"] == RECEIPT
	assert account["prompt_basis"] == prompt_basis.LAST_PROMPT_TOKENS


def test_no_receipt_falls_back_with_label_and_never_raises() -> None:
	"""首枪 / 离线重放没有 receipt ⇒ 退回估算并打标；绝不抛、绝不把量清零。"""
	from memory.runtime import _prompt_account

	w = WorkingSnapshot(session_id="sess_basis_first", last_prompt_tokens=0)
	msgs = _msgs(30, 6000)
	account = _prompt_account(msgs, w)
	assert account["prompt_basis"] == prompt_basis.ESTIMATE_MESSAGES
	assert account["input_tokens"] > 0
	# 回退量仍指向真历史（不是 0、也不是被截断的小数）
	assert account["input_tokens"] >= sum(len(m["content"]) for m in msgs) // 4


def test_extension_prompt_tokens_still_prefers_receipt(monkeypatch) -> None:
	"""口径档语义不变：有实发用实发，拿不到仍回落全历史口径（本次改动不碰判定）。"""
	from memory import runtime, wsc_projection

	monkeypatch.setenv("XEYO_WSC_GATE_EMITTED_BASIS", "1")
	monkeypatch.setattr(wsc_projection, "live_enabled", lambda: True)
	msgs = _msgs(30, 6000)
	w = WorkingSnapshot(session_id="sess_basis_ext", last_prompt_tokens=37_750)
	assert runtime._extension_prompt_tokens(None, msgs, w) == (37_750, "last_prompt_tokens")
	w.last_prompt_tokens = 0
	tokens, basis = runtime._extension_prompt_tokens(None, msgs, w)
	assert basis == "region_raw" and tokens > 0


def test_ledger_rows_never_write_bare_input_tokens() -> None:
	"""结构不变量：账行不许再出现无来源标签的裸 ``input_tokens``（改名即红）。"""
	src = (REPO_PY / "memory" / "runtime.py").read_text(encoding="utf-8")
	assert '"input_tokens": token_len(' not in src


def test_unlabelled_input_tokens_is_stamped_not_dropped(monkeypatch, tmp_path) -> None:
	"""结构性兜底：缺标签的 ``input_tokens`` 落账时静默补 ``unlabelled``（不拒绝、不改数值）。"""
	import usage.ledger as ledger

	from memory.runtime import _note_fold_attempt

	monkeypatch.setattr(ledger, "usage_dir", lambda: tmp_path)
	_note_fold_attempt(WorkingSnapshot(session_id="sess_unlabelled"), {"input_tokens": 123})
	row = json.loads((tmp_path / "fold_events.jsonl").read_text(encoding="utf-8").splitlines()[0])
	assert row["input_tokens"] == 123
	assert row["prompt_basis"] == prompt_basis.UNLABELLED


def test_keep_assessment_rows_carry_prompt_basis(monkeypatch, tmp_path) -> None:
	"""端到端：两条 keep 账路（WSC 关 / WSC 接管发射面）都带 ``prompt_basis``。"""
	import usage.ledger as ledger

	from memory.runtime import project_for_model

	monkeypatch.setattr(ledger, "usage_dir", lambda: tmp_path)
	for native in (False, True):
		monkeypatch.setenv("XEYO_WSC", str(int(native)))
		monkeypatch.setenv("XEYO_C2_MARGIN", "0.01" if native else "1000")
		w = WorkingSnapshot(session_id="basis-row-" + str(native), last_prompt_tokens=RECEIPT)
		project_for_model(_msgs(30, 6000), w, context_limit=1_000_000, include_memory_index=False)
	rows = [
		json.loads(line)
		for line in (tmp_path / "fold_events.jsonl").read_text(encoding="utf-8").splitlines()
		if line.strip()
	]
	assert [r["arm"] for r in rows] == ["c2", "wsc"], rows
	for row in rows:
		# 主策略恒定生效 ⇒ ``project_for_model`` 的账行来自 ``wsc_timing.measure``
		# （本次发射面估算 + 匹配 receipt 的 overhead），**不是**厂商实发、也不是投影前原史
		# ⇒ 标签必须是估算类，且绝不留 ``unlabelled``（读侧据此分辨同名不同义的 input_tokens）。
		assert row["prompt_basis"] == prompt_basis.ESTIMATE_EMISSION, row
		assert row["input_tokens"] > 0, row
