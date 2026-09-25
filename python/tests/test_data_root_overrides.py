"""数据根必须只有一个权威解析点：认 env 覆盖，别在调用方各拼一份 Path.home()。

动因（2026-09-25 实测）：``memory/journal._journal_root()`` 与
``engine/subagent_runner._sidechain_dir()`` 硬编码 ``~/.xeyo/...``，而同仓库里
``session.persistence.default_sessions_dir()`` 明明声明"可用 XEYO_SESSIONS_DIR
覆盖"。结果是双重的：设了覆盖的进程（每个测试都会设）把 journal 和子 agent 侧链
继续写进用户真实主目录（``~/.xeyo/journal`` 实测 9662 个 .jsonl，其中 534 个是真
journal），而清理循环又按另一套根扫描，扫不到自己写下的东西。

行为测试只钉住今天修好的两处；结构门负责让第三处不能再悄悄出现。
"""

from __future__ import annotations

import re
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {".venv", "tests", "__pycache__", ".pytest_cache", "node_modules"}

# (路径字面量, 必须同时出现的 env 名)
RELOCATABLE = {
	r'"\.xeyo"\s*/\s*"sessions"': "XEYO_SESSIONS_DIR",
	r'"\.xeyo"\s*/\s*"journal"': "XEYO_JOURNAL_DIR",
}


def _source_files() -> list[Path]:
	return [
		p
		for p in PKG_ROOT.rglob("*.py")
		if not (_SKIP_DIRS & set(p.relative_to(PKG_ROOT).parts))
	]


def test_every_hardcoded_data_root_honours_its_override() -> None:
	offenders: list[str] = []
	checked = 0
	for p in _source_files():
		text = p.read_text(encoding="utf-8", errors="replace")
		for pattern, env_name in RELOCATABLE.items():
			if re.search(pattern, text):
				checked += 1
				if env_name not in text:
					offenders.append(f"{p.relative_to(PKG_ROOT)}: {pattern} 但没读 {env_name}")
	assert checked >= 2, f"扫描没覆盖到已知的数据根（命中 {checked} 处），这条门已失效"
	assert not offenders, "拼死路径却绕过权威解析：\n" + "\n".join(offenders)


def test_journal_root_follows_the_env(monkeypatch, tmp_path: Path) -> None:
	from memory import journal

	monkeypatch.setenv("XEYO_JOURNAL_DIR", str(tmp_path / "jl"))
	assert journal.journal_root() == tmp_path / "jl"
	assert journal._changes_path("ws-a").parent == tmp_path / "jl"

	monkeypatch.delenv("XEYO_JOURNAL_DIR", raising=False)
	assert journal.journal_root() == Path.home() / ".xeyo" / "journal"


def test_sidechains_follow_the_sessions_env(monkeypatch, tmp_path: Path) -> None:
	from engine.subagent_runner import _sidechain_dir, _sidechain_path

	alt = tmp_path / "sessions"
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(alt))
	assert _sidechain_dir("s1").parent == alt / "s1"
	assert _sidechain_path("s1", "a1").parent == alt / "s1" / "agents"


def test_default_stays_under_home(monkeypatch) -> None:
	"""没有覆盖时的落点不能被这次改动挪走（迁移风险为零的前提）。"""
	from session.persistence import default_sessions_dir

	monkeypatch.delenv("XEYO_SESSIONS_DIR", raising=False)
	assert default_sessions_dir() == Path.home() / ".xeyo" / "sessions"
