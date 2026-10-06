"""一个读不动的嵌套指令文件，不许把整块项目指令带走。

现场（2026-10-03 读码 + 实测）：
- `load_nested_instruction_text()` 逐文件 `Path(p).read_text(encoding="utf-8")`
  只捕 `OSError` ⇒ 一个 UTF-16/GBK 的 AGENTS.md 抛 `UnicodeDecodeError`（ValueError 系）；
- 唯一调用点 `prompt/pre_llm_inject._format_nested_block` 把**整趟**包在
  `except Exception: log.debug(...)` 里 ⇒ 结果是**所有**嵌套指令一起被丢掉，
  而且本项目从不配置 logging handler（实测 221 处 getLogger / 0 处 handler），
  debug 等价于 pass ⇒ 模型每轮都在没有项目规则的情况下跑，且现场无任何证据。
- `reconcile_nested_state()` / `note_read_path_for_nested()` 走同一个 `_sha1_file`：
  同一异常让引擎侧状态卫生整段跳过。

修法只收窄失败范围，不预设"非 UTF-8 该怎么办"（那是另一条待拍项）：
- 单文件读不动 ⇒ 跳过该文件，并在**已有的 notice 行**里点名（纯事实）；
- `_sha1_file` 的失败哨兵本来就是 ""（OSError 返回 ""），把解码失败并入同一哨兵。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from memory.instruction_maintain import (
	_sha1_file,
	load_nested_instruction_text,
	reconcile_nested_state,
)

HEAD_A = "Rule A: 用 py -3.11 跑测试"
HEAD_B = "Rule B: 提交前必须全绿"


@pytest.fixture
def ws(tmp_path: Path) -> tuple[Path, Path, Path]:
	"""两个能读的嵌套指令文件 + 一个注定读不动的路径。"""
	a = tmp_path / "a_agents.md"
	b = tmp_path / "nested" / "b_agents.md"
	b.parent.mkdir(parents=True, exist_ok=True)
	a.write_bytes(HEAD_A.encode("utf-8"))
	b.write_bytes(HEAD_B.encode("utf-8"))
	return a, b, tmp_path / "broken" / "c_agents.md"


def test_one_undecodable_file_does_not_erase_the_whole_block(
	ws: tuple[Path, Path, Path]
) -> None:
	a, b, bad = ws
	bad.parent.mkdir(parents=True, exist_ok=True)
	bad.write_bytes("Rule C: 中文正文".encode("gbk"))  # 不是合法 UTF-8

	out = load_nested_instruction_text([str(a), str(bad), str(b)])

	assert HEAD_A in out, "一个坏文件把同批合法指令一起带走了"
	assert HEAD_B in out, "同上（后于坏文件的合法项也必须保留）"
	assert "无法按 UTF-8 解码" in out, f"坏文件必须留下事实句，不能静默消失：{out!r}"
	assert bad.name in out


def test_all_decodable_renders_unchanged_and_adds_no_notice(
	ws: tuple[Path, Path, Path]
) -> None:
	"""反向对照：正常树里不许冒出"略过/未解码"这类新句子（每轮都在交税）。"""
	a, b, _bad = ws
	out = load_nested_instruction_text([str(a), str(b)])

	assert HEAD_A in out and HEAD_B in out
	assert "无法按 UTF-8 解码" not in out
	assert "整份略过" not in out


def test_sha1_file_returns_sentinel_instead_of_raising(tmp_path: Path) -> None:
	p = tmp_path / "utf16.md"
	p.write_bytes(b"\xff\xfe" + "Rule UTF-16".encode("utf-16-le"))

	assert _sha1_file(str(p)) == "", "解码失败应落到与 OSError 同一个哨兵，别把异常抛给调用方"
	ok = tmp_path / "utf8.md"
	ok.write_text("plain", encoding="utf-8")
	digest = _sha1_file(str(ok))
	assert len(digest) == 40 and digest != ""


def test_reconcile_nested_state_survives_undecodable_file(tmp_path: Path) -> None:
	p = tmp_path / "xeyo.md"
	p.write_bytes("中文".encode("gbk"))
	working = SimpleNamespace(
		loaded_nested_instruction_paths=[str(p)],
		nested_hashes={},
	)

	reconcile_nested_state(working)  # 不得抛

	assert working.loaded_nested_instruction_paths == [str(p)]


def test_missing_file_still_skipped_quietly(
	ws: tuple[Path, Path, Path], tmp_path: Path
) -> None:
	"""反向对照：路径不存在（OSError）的行为不变——整块照渲染，不多一名句。"""
	a, b, _bad = ws
	out = load_nested_instruction_text([str(a), str(tmp_path / "nope.md"), str(b)])

	assert HEAD_A in out and HEAD_B in out
	assert "nope.md" not in out
