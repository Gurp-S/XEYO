"""`except OSError` 抓不住 `UnicodeDecodeError`：三处用户文件的读点各自把"读不出"放大成更大的坏。

同一族的三个实测缺陷（2026-10-03，全部用真实产品函数复现）：

1. `memory/instruction.py::read_optional`（项目指令装配）
   用户的 AGENTS.md 族里只要有一个不是 UTF-8（中文 Windows 上用记事本/老编辑器保存的
   CLAUDE.md 是真实形态），严格 `read_text(encoding="utf-8")` 抛 UnicodeDecodeError，
   它不是 OSError ⇒ 逃逸到 `load_instruction_text`。
   上层 `prompt/system_prompt.py::_load_instructions` 是 `except Exception: return ""`
   ⇒ **整套项目指令静默消失**（连没坏的那个文件也没了），模型看到"这个项目没有说明"。
2. `engine/write_store.py::_syntax_ok`（写前语法门）
   容器分支用同文件已有的 `_read_text_safe`，非容器分支却裸 `read_text(encoding="utf-8")`。
   旧文件非 UTF-8 + 本次新内容自己就是语法错 ⇒ 逃逸出 `submit_sync` ⇒ 逃出工具 ⇒
   `ToolRegistry.run` 记完审计就 re-raise ⇒ 一枪 Edit/Write 打断整个回合。
3. `extension/skill_loader.py::_entry_from_dir`（技能发现表）
   GBK 的 SKILL.md 抛出的异常一路逃到 `_skill_entries_with_descriptions` 的
   `except Exception: return []` ⇒ **整张技能表清空**（同目录里别的正常技能一起没了）。
   模块自己写着的策略是"坏 frontmatter → broken-but-listed"，所以正解是走那个状态，
   而不是把"读不出"伪装成"这个 skill 没有说明"（body="" 会静默造出一个空描述的正常条目）。
4. `session/transcript_blobs.py::resolve_transcript_row`（历史 blob 水合）
   只兜 `(OSError, json.JSONDecodeError)`；截断的落盘把一个多字节字符切成两半时抛的是
   UnicodeDecodeError ⇒ 逃逸到子会话历史水合（`engine/subagent_runner`），
   一条坏 blob 打断一整次子代理运行。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from engine.write_store import _syntax_ok
from extension.skill_loader import _entry_from_dir
from memory import instruction as instr

GBK_TEXT = "# 旧项目说明\n中文优先。\n"


# ---------------------------------------------------------------- 1. 项目指令装配
def _instruction_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(instr, "xeyo_home", lambda: home)
    instr.clear_instruction_cache()
    root = tmp_path / "ws"
    root.mkdir(exist_ok=True)
    return root


def test_one_non_utf8_instruction_file_does_not_wipe_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _instruction_root(tmp_path, monkeypatch)
    (root / "CLAUDE.md").write_bytes(GBK_TEXT.encode("gb18030"))
    (root / "AGENTS.md").write_text("SENTINEL-KEEP-ME\n", encoding="utf-8")

    text = instr.load_instruction_text(str(root), str(root))
    assert "SENTINEL-KEEP-ME" in text, "一个文件读不出 ⇒ 整套项目指令都不见了"
    # 反向对照：读不出的那份不许被"尽力解码"塞进正文（那会把乱码当事实给模型）
    assert "中文优先" not in text


def test_includes_of_non_utf8_target_keep_the_parent_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _instruction_root(tmp_path, monkeypatch)
    (root / "notes" ).mkdir()
    (root / "notes" / "gbk_inc.md").write_bytes(GBK_TEXT.encode("gb18030"))
    (root / "AGENTS.md").write_text(
        "PARENT-BODY\n@include notes/gbk_inc.md\nTAIL-BODY\n", encoding="utf-8"
    )
    text = instr.load_instruction_text(str(root), str(root))
    assert "PARENT-BODY" in text and "TAIL-BODY" in text, "@include 目标读不出 ⇒ 父文件正文一起没了"


# ---------------------------------------------------------------- 2. 写前语法门
def test_syntax_gate_survives_a_non_utf8_old_file() -> None:
    """新内容自己就是语法错时，门会去读旧文件比对——旧文件非 UTF-8 不许炸这一枪。"""
    root = Path(tempfile.mkdtemp(prefix="xeyo_syn_gbk_"))
    old = root / "old.py"
    old.write_bytes(("x = 1  # 中文注释\n" * 3).encode("gb18030"))
    broken_new = "def f(:\n    pass\n"
    verdict = _syntax_ok(old, broken_new)  # 改前：UnicodeDecodeError 逃逸
    assert isinstance(verdict, bool)


def test_syntax_gate_still_blocks_a_fresh_syntax_error() -> None:
    """反向对照：容错解码不许把门变成橡皮章——干净旧文件 + 语法错新内容仍要拒。"""
    root = Path(tempfile.mkdtemp(prefix="xeyo_syn_ok_"))
    old = root / "clean.py"
    old.write_text("x = 1\n", encoding="utf-8")
    assert _syntax_ok(old, "def f(:\n    pass\n") is False


# ---------------------------------------------------------------- 3. 技能发现表
def test_non_utf8_skill_is_broken_but_listed(tmp_path: Path) -> None:
    d = tmp_path / "gbk"
    d.mkdir()
    (d / "SKILL.md").write_bytes(
        "---\nname: gbk\ndescription: 中文说明\n---\n\n正文\n".encode("gb18030")
    )
    entry = _entry_from_dir(d, source="workspace")  # 改前：异常逃逸，整张表被上层清空
    assert entry.broken is True
    assert "UTF-8" in entry.reason


def test_readable_skill_is_still_listed_normally(tmp_path: Path) -> None:
    """反向对照：坏文件不许连坐——同批里的正常 skill 必须照旧可发现。"""
    d = tmp_path / "good"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: good\ndescription: fine\n---\n\nbody\n", encoding="utf-8"
    )
    entry = _entry_from_dir(d, source="workspace")
    assert entry.broken is False
    assert entry.description == "fine"


def test_missing_skill_file_is_also_broken_not_silently_empty(tmp_path: Path) -> None:
    """读不出（权限/缺文件）与解码失败同档：不许伪装成"这个 skill 没有说明"。"""
    d = tmp_path / "nofile"
    d.mkdir()
    entry = _entry_from_dir(d, source="workspace")
    assert entry.broken is True
    assert entry.reason


# ---------------------------------------------------------------- 4. transcript blob 水合
def _blob_row(tmp_path: Path, payload: bytes) -> dict[str, object]:
    from session.transcript_blobs import resolve_transcript_row

    anchor = tmp_path / "s1.jsonl"
    blobs = tmp_path / "s1.blobs"
    blobs.mkdir(exist_ok=True)
    (blobs / "m1.json").write_bytes(payload)
    return resolve_transcript_row({"content_ref": "m1.json"}, anchor)


def test_truncated_blob_does_not_break_history_hydration(tmp_path: Path) -> None:
    """截断的落盘把一个多字节字符切成两半 ⇒ UnicodeDecodeError，不是 JSONDecodeError。
    原先它会从 `resolve_transcript_row` 逃到子会话历史水合（engine/subagent_runner）。"""
    half = '["正文中'.encode("utf-8")
    broken = half + b"\xe4"  # 末尾一个孤立的 UTF-8 前导字节 ⇒ 解码必抛
    with pytest.raises(UnicodeDecodeError):
        broken.decode("utf-8")
    row = _blob_row(tmp_path, broken)
    assert row["content"] == ""


def test_intact_blob_still_resolves(tmp_path: Path) -> None:
    """反向对照：收口不许把读得出来的正文也吞掉。"""
    row = _blob_row(tmp_path, '["正文中文 ok"]'.encode("utf-8"))
    assert row["content"] == ["正文中文 ok"]
