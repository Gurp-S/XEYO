"""基线淘汰后的报错必须能区分"从没读过"与"读过但基线没了"（⑤ 回归）。

事故形态（本场实测两次被同一句 ``missing_read`` 拦住）：模型只拿到
``no prior Read baseline for this path in this process/session``，无法判断该
"重读同一段"还是"从头读"——只能试。修法 = 报错带上因由与世代。

方向性都钉：
- 被 LRU 淘汰 / 被 clear 的路径 ⇒ ``baseline_dropped`` 为真（报错说 dropped + epoch）；
- 从没读过的路径 ⇒ 假（报错说 never read）；
- epoch 只在真的丢条目时前进（别在无关路径上乱增，否则归因失去意义）。
"""

from __future__ import annotations

from tools.fileio.read_state import (
	FileStateEntry,
	ReadFileState,
	baseline_dropped,
	baseline_epoch,
)


def _entry(content: str = "x") -> FileStateEntry:
	return FileStateEntry(content=content, timestamp=1)


def test_evicted_baseline_is_reported_as_dropped(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_READ_STATE_MAX_ENTRIES", "8")
	state = ReadFileState()
	paths = [str(tmp_path / f"f{i}.py") for i in range(9)]
	for path in paths:
		state.set(path, _entry())
	# 第 1 条被 LRU 淘汰 ⇒ 它属于"读过但基线没了"，最后一条仍在册。
	assert baseline_dropped(paths[0]) is True
	assert baseline_dropped(paths[-1]) is False


def test_never_read_path_is_not_reported_as_dropped(tmp_path) -> None:
	assert baseline_dropped(str(tmp_path / "never_read.py")) is False


def test_clear_marks_all_entries_dropped(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_READ_STATE_MAX_ENTRIES", "8")
	state = ReadFileState()
	path = str(tmp_path / "a.py")
	state.set(path, _entry())
	before = baseline_epoch()
	state.clear()
	assert baseline_epoch() > before
	assert baseline_dropped(path) is True


def test_epoch_does_not_move_without_a_drop(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_READ_STATE_MAX_ENTRIES", "8")
	state = ReadFileState()
	before = baseline_epoch()
	state.set(str(tmp_path / "fits.py"), _entry())
	assert baseline_epoch() == before
