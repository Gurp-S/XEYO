"""流式契约的门（三）：TUI 侧对账（2026-10-03）。

`server/stream_contract.py` 的口径是「后端新增/改名一个 `xy.type`，客户端 if-chain
缺分支 ⇒ 帧被静默丢弃、界面少一块且**没有任何测试变红**」。它自己的模块文档写明
前端对账只做了 GUI（`gui/src/lib/api/streamContract.test.ts`）——第二客户端 TUI
从来没被任何门覆盖过。这条把 TUI 也纳进来。

堵的具体事故形态：后端今天再加一帧，GUI 会红、TUI 会**静默少一块**。

本门**不修** TUI 现在没渲染的那些帧（那是功能开发，按项目规矩要用户拍），
只做两件事：
1. 在册：每个声明帧要么被 TUI 认，要么出现在下面的显式清单里并写明代价；
2. 双向：清单里的帧一旦哪天被 TUI 真的处理了，本门同样报红，逼着把条目删掉——
   否则清单会变成第二个"死分支"（本项目反复踩的口径漂移）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.stream_contract import STREAM_EVENT_TYPES

_PY_ROOT = Path(__file__).resolve().parents[1]
_TUI_SRC = _PY_ROOT.parent / "tui" / "src"

#: 扫描范围：TUI 生产代码。测试与生成物不算「客户端认得这帧」的证据。
_SKIP_DIR_NAMES = frozenset({"node_modules", "dist", "generated", "__pycache__"})

#: 声明了但 TUI 当前不渲染的帧 —— 逐条写明「为什么现在可以不要它」。
TUI_UNHANDLED_ALLOWED = {
	"task_state_changed": "TUI 用回合结束后的 /v1/sessions 快照刷状态，不靠这帧驱动界面",
	"goal": "目标块只在 GUI 的目标坞里呈现；TUI 走 /v1/goals 轮询",
	"jobs": "后台作业卡片是 GUI 面；TUI 用 `xeyo jobs` CLI 读同一账本",
	"steer_delivered": "TUI 无忙时引导输入通路，收不到该帧；若将来接入必须同时补渲染",
	"llm_retry": "TUI 只显示重试后的静默期，不做倒计时卡片",
	"llm_retry_started": "同上：重试起点未渲染",
	"multi_agent_task": "TUI 目前用 tool_progress 里的文本行呈现子代理，不建多代理卡",
	"multi_agent_progress": "同上",
	"multi_agent_delta": "同上",
}


def _tui_production_text() -> str:
	blobs: list[str] = []
	for path in sorted(_TUI_SRC.rglob("*")):
		if not path.is_file() or path.suffix not in (".ts", ".tsx"):
			continue
		if ".test." in path.name:
			continue
		if _SKIP_DIR_NAMES & set(path.parts):
			continue
		blobs.append(path.read_text(encoding="utf-8", errors="replace"))
	return "\n".join(blobs)


@pytest.fixture(scope="module")
def tui_text() -> str:
	if not _TUI_SRC.is_dir():
		pytest.skip(f"没有 TUI 源码树：{_TUI_SRC}（独立精简树里不判这条）")
	text = _tui_production_text()
	# 探针非空前置：扫描器若什么都读不到，"缺失"断言就毫无意义。
	assert len(text) > 1000, f"TUI 生产代码扫描结果近乎为空（{len(text)} 字符）——门已失效"
	return text


def test_every_declared_frame_is_either_handled_or_registered(tui_text: str) -> None:
	handled = {t for t in STREAM_EVENT_TYPES if t in tui_text}
	unaccounted = set(STREAM_EVENT_TYPES) - handled - set(TUI_UNHANDLED_ALLOWED)
	assert not unaccounted, (
		"后端新增/改名的 xy 帧在两个客户端都没登记："
		f"{sorted(unaccounted)}；TUI 要么补渲染分支，要么写入 TUI_UNHANDLED_ALLOWED 并写明代价"
	)


def test_registered_unhandled_frames_are_really_unhandled(tui_text: str) -> None:
	"""双向校：清单里写的帧若已被 TUI 认，必须把条目删掉。

	没有这一条，清单会退化成第二个"死分支"——GUI 侧已经吃过一次「前端留着后端
	从不发的死分支」。
	"""
	stale = {name for name in TUI_UNHANDLED_ALLOWED if name in tui_text}
	assert not stale, (
		f"TUI_UNHANDLED_ALLOWED 里的 {sorted(stale)} 已被 TUI 生产代码引用，"
		"请删掉对应条目（否则这条门不再执法）"
	)


def test_tui_probe_denominator_is_not_empty(tui_text: str) -> None:
	"""正向自证：探针确实读到了 TUI 用来认帧的那些字面量。"""
	handled = {t for t in STREAM_EVENT_TYPES if t in tui_text}
	assert handled, "TUI 一个声明帧都没匹配上——多半是扫描路径或后缀写错了"
	assert len(handled) >= 10, f"只匹配到 {len(handled)} 个帧名，覆盖面远低于 TUI 实际分支数"
