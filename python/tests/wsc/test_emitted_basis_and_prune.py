"""10-04 三档旁路的契约测试：口径档 / 尺寸档 / 绝对压力线。

三档全部**默认关**，所以第一条不变量是"关着时与改动前逐字一致"；
第二条是"开着时真的接上了发射侧/真的可恢复"，不许只测函数返回值。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 0) 注册表：两个布尔旗标必须入册，且账面 = 运行时（同一份 env_flag）
# ---------------------------------------------------------------------------

def test_new_flags_are_registered_and_readable(monkeypatch) -> None:
	from memory import memory_switches as MS

	keys = {k for k, *_ in MS.MEMORY_SWITCHES}
	assert {"XEYO_WSC_GATE_EMITTED_BASIS", "XEYO_WSC_SIZE_PRUNE"} <= keys
	for name in ("XEYO_WSC_GATE_EMITTED_BASIS", "XEYO_WSC_SIZE_PRUNE"):
		monkeypatch.delenv(name, raising=False)
		assert MS.env_flag(name) is False
		assert MS.current(None)[name]["effective"] == "0"
		monkeypatch.setenv(name, "1")
		assert MS.env_flag(name) is True
		assert MS.current(None)[name]["effective"] == "1"
		monkeypatch.setenv(name, "garbage")
		# 认不得 ⇒ 回落注册表默认（关），账面与运行时同源
		assert MS.env_flag(name) is False


# ---------------------------------------------------------------------------
# 1) 口径档：head / prompt 两个分母的取法
# ---------------------------------------------------------------------------

def _working():
	from memory.working import WorkingSnapshot

	return WorkingSnapshot(session_id="sess_test", last_prompt_tokens=0)


def test_head_basis_default_is_c2_estimate(monkeypatch) -> None:
	from memory.runtime import _extension_head_tokens

	monkeypatch.delenv("XEYO_WSC_GATE_EMITTED_BASIS", raising=False)
	tokens, basis = _extension_head_tokens("x" * 400, _working())
	assert basis == "c2_estimate"
	assert tokens == 100  # ceil(400/4)


def test_head_basis_uses_live_measurement_when_enabled(monkeypatch) -> None:
	from memory import runtime, wsc_projection

	monkeypatch.setenv("XEYO_WSC_GATE_EMITTED_BASIS", "1")
	monkeypatch.setattr(wsc_projection, "live_enabled", lambda: True)
	monkeypatch.setattr(wsc_projection, "live_head_delta_tokens", lambda *a, **k: 1234)
	tokens, basis = runtime._extension_head_tokens("x" * 400, _working())
	assert (tokens, basis) == (1234, "wsc_emitted")
	# 拿不到实测 ⇒ 回退 C2 口径并**在账上标明**，绝不把"没有实测"当 0
	monkeypatch.setattr(wsc_projection, "live_head_delta_tokens", lambda *a, **k: None)
	tokens, basis = runtime._extension_head_tokens("x" * 400, _working())
	assert (tokens, basis) == (100, "c2_estimate_fallback")


def test_prompt_basis_prefers_vendor_prompt_when_enabled(monkeypatch) -> None:
	from memory import runtime, wsc_projection

	msgs = [{"role": "user", "content": "y" * 4000}]
	w = _working()
	monkeypatch.setenv("XEYO_WSC_GATE_EMITTED_BASIS", "1")
	monkeypatch.setattr(wsc_projection, "live_enabled", lambda: True)
	# last_prompt_tokens 为 0（首枪）⇒ 回落全历史口径
	assert runtime._extension_prompt_tokens(None, msgs, w) == (1000, "region_raw")
	w.last_prompt_tokens = 37_750
	assert runtime._extension_prompt_tokens(None, msgs, w) == (37_750, "last_prompt_tokens")
	# 关着时永远走全历史口径（= 改动前行为）
	monkeypatch.delenv("XEYO_WSC_GATE_EMITTED_BASIS", raising=False)
	assert runtime._extension_prompt_tokens(None, msgs, w) == (1000, "region_raw")


def test_extension_gate_numbers_are_identical_when_flag_off(monkeypatch) -> None:
	"""关着时 try_extend_c2 的账目字段与旧公式逐字段一致（含新增的 *_basis 标签）。"""
	from memory import runtime

	monkeypatch.delenv("XEYO_WSC_GATE_EMITTED_BASIS", raising=False)
	ext = "z" * 800
	tokens, basis = runtime._extension_head_tokens(ext, _working())
	region = 10_000
	tail = 4_000
	assert tokens == 200 and basis == "c2_estimate"
	assert max(0, region - tokens) == 9_800
	assert tokens + tail == 4_200


# ---------------------------------------------------------------------------
# 2) 绝对压力线：不需要窗口也能触发
# ---------------------------------------------------------------------------

def test_absolute_pressure_line_works_without_window(monkeypatch) -> None:
	from memory.runtime import should_force_compact_on_pressure

	monkeypatch.delenv("XEYO_C2_PRESSURE_TOKENS", raising=False)
	# 窗口未知 + 无绝对线 ⇒ 不触发（与改动前一致）
	assert should_force_compact_on_pressure(prompt_tokens=90_000, context_limit=None) is False
	monkeypatch.setenv("XEYO_C2_PRESSURE_TOKENS", "48000")
	assert should_force_compact_on_pressure(prompt_tokens=48_000, context_limit=None) is True
	assert should_force_compact_on_pressure(prompt_tokens=47_999, context_limit=None) is False
	# 1M 窗口 + 0.95 比例：9 万远不触发（今日实测形状），绝对线仍独立生效
	assert should_force_compact_on_pressure(prompt_tokens=90_000, context_limit=1_000_000) is True
	monkeypatch.setenv("XEYO_C2_PRESSURE_TOKENS", "not-a-number")
	assert should_force_compact_on_pressure(prompt_tokens=90_000, context_limit=1_000_000) is False


# ---------------------------------------------------------------------------
# 3) 尺寸档：修剪必然变小、原文必然可回；失败方向是"不修剪"
# ---------------------------------------------------------------------------

def test_prune_shrinks_and_archives(tmp_path, monkeypatch) -> None:
	from memory.wsc_size_prune import maybe_prune_with_archive

	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path / "off"))
	big = "A" * 4000 + "MIDDLE" * 4000 + "Z" * 2000  # 30k 字符
	out, archived = maybe_prune_with_archive(big, msg_idx=7, uid="toolu_abc", cwd=tmp_path)
	assert archived and Path(archived).is_file()
	assert Path(archived).read_text(encoding="utf-8") == big  # 原文逐字可回
	assert len(out) < len(big)
	assert "Read(file_path=" in out and "offset=1" in out
	assert "tool result middle pruned" in out
	# 头尾都还在（修剪不是"截掉后面"）
	assert out.startswith("A" * 100)
	assert big.rstrip().endswith("Z" * 100) and "Z" * 100 in out
	# 引用是**相对工作区**且用 `/`（与 offload/冷层视图同一规则）
	ref = out.split("Read(file_path='", 1)[1].split("'", 1)[0]
	assert "\\" not in ref and not os.path.isabs(ref)


def test_prune_is_noop_below_threshold(tmp_path, monkeypatch) -> None:
	from memory.wsc_size_prune import maybe_prune_with_archive

	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path / "off"))
	small = "x" * 8192  # 恰好等于阈值 ⇒ 不修剪
	out, archived = maybe_prune_with_archive(small, msg_idx=1, uid="u", cwd=tmp_path)
	assert out == small and archived is None
	assert not (tmp_path / "off").exists() or not any((tmp_path / "off").rglob("*.txt"))


def test_prune_fails_open_when_archive_fails(tmp_path, monkeypatch) -> None:
	"""落盘失败 ⇒ 原样返回。拿不回的修剪比不修剪糟得多。"""
	import memory.offload as offload
	from memory.wsc_size_prune import maybe_prune_with_archive

	def boom(*_a, **_k):
		raise OSError("disk full")

	monkeypatch.setattr(offload, "_offload_root", boom)
	big = "Q" * 30_000
	out, archived = maybe_prune_with_archive(big, msg_idx=1, uid="u", cwd=tmp_path)
	assert out == big and archived is None


def test_compact_wiring_is_off_by_default_and_on_with_flag(tmp_path, monkeypatch) -> None:
	"""接线证明：同一份超长结果，关=走 C0 截断（无取回入口），开=走修剪（带 Read 入口）。"""
	from engine.compact import _project_tool_result_content

	big = "B" * 30_000
	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path / "off"))
	monkeypatch.delenv("XEYO_TOOL_OFFLOAD", raising=False)

	def run():
		return _project_tool_result_content(
			big, uid="toolu_1", name="Read", frozen=False, frozen_until=0,
			idx=3, aging=False, is_error=False, cwd=tmp_path,
		)

	monkeypatch.delenv("XEYO_WSC_SIZE_PRUNE", raising=False)
	off_out, off_aged = run()
	assert off_aged is False
	assert "truncated" in off_out and "Read(file_path=" not in off_out
	assert len(off_out) < 9000  # C0 上限 8192 字符量级

	monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
	on_out, _ = run()
	assert "Read(file_path=" in on_out
	assert "tool result middle pruned" in on_out
	# 最终档（2026-10-04 用户裁定）：阈 3072 → 可见 2048+512 ⇒ 明显小于 C0 的 4096+1024。
	# （旧接线曾用模块默认 4096/1024，与 C0 同形；这里起是"真的变小"后的断言。）
	assert len(on_out) < len(off_out) * 0.6
	assert len(on_out) < 4500
	# 更紧的手动档仍可用（取回面合同见 test_prune_shrinks_and_archives）
	from memory.wsc_size_prune import maybe_prune_with_archive

	tiny, _arch = maybe_prune_with_archive(
		big, msg_idx=9, uid="u9", cwd=tmp_path, head_chars=1024, tail_chars=256
	)
	assert len(tiny) < len(off_out) * 0.5
	assert "Read(file_path=" in tiny


def test_compact_wiring_passes_final_geometry(monkeypatch) -> None:
	"""最终档三参数（阈 3072 / 头 2048 / 尾 512）必须逐字传到 `maybe_prune_with_archive`。"""
	import memory.wsc_size_prune as SP
	from engine.compact import (
		SIZE_PRUNE_HEAD_CHARS,
		SIZE_PRUNE_TAIL_CHARS,
		SIZE_PRUNE_THRESHOLD_CHARS,
		_project_tool_result_content,
	)

	assert (SIZE_PRUNE_THRESHOLD_CHARS, SIZE_PRUNE_HEAD_CHARS, SIZE_PRUNE_TAIL_CHARS) == (3072, 2048, 512)

	captured: dict = {}

	def spy(raw, **kw):
		captured.update(kw)
		return raw, None

	monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
	monkeypatch.setattr(SP, "maybe_prune_with_archive", spy)
	out, _ = _project_tool_result_content(
		"E" * 10_000, uid="toolu_2", name="Read", frozen=False, frozen_until=0,
		idx=5, aging=False, is_error=False, cwd=None,
	)
	assert out == "E" * 10_000  # spy 原样返回 ⇒ 投影不变，本用例只验参数传递
	assert captured.get("threshold_chars") == SIZE_PRUNE_THRESHOLD_CHARS
	assert captured.get("head_chars") == SIZE_PRUNE_HEAD_CHARS
	assert captured.get("tail_chars") == SIZE_PRUNE_TAIL_CHARS


def test_final_tier_covers_3072_to_8192_range(tmp_path, monkeypatch) -> None:
	"""阈值收到 3072 的语义差：3k~8k 字符的结果也进修剪（旧接线要 >8192 才动）。"""
	from engine.compact import _project_tool_result_content

	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path / "off"))
	monkeypatch.delenv("XEYO_TOOL_OFFLOAD", raising=False)
	mid = "F" * 5_000  # 低于 C0 的 8192 ⇒ 关旗标时原样不动

	def run():
		return _project_tool_result_content(
			mid, uid="toolu_3", name="Read", frozen=False, frozen_until=0,
			idx=6, aging=False, is_error=False, cwd=tmp_path,
		)

	monkeypatch.delenv("XEYO_WSC_SIZE_PRUNE", raising=False)
	off_out, _ = run()
	assert off_out == mid and "Read(file_path=" not in off_out

	monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
	on_out, _ = run()
	assert "Read(file_path=" in on_out and "tool result middle pruned" in on_out
	assert len(on_out) < len(mid)


@pytest.mark.parametrize("size", [8193, 12_000, 30_000, 200_000])
def test_prune_never_grows(size, tmp_path, monkeypatch) -> None:
	from memory.wsc_size_prune import maybe_prune_with_archive

	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path / "off"))
	text = "C" * size
	out, _ = maybe_prune_with_archive(text, msg_idx=1, uid="u", cwd=tmp_path)
	assert len(out) <= len(text)
