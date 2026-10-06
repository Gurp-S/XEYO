"""工作区文件浏览：路径沙箱与列表/读取/删除/搜索。"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.workspace_fs import (
	delete_path,
	list_entries,
	read_file,
	resolve_in_workspace,
	search_entries,
	stat_file,
	write_file,
)


@pytest.fixture(autouse=True)
def _enable_direct_writes(monkeypatch: pytest.MonkeyPatch) -> None:
	"""直写通道默认关闭（安全默认值），本模块的写/删用例显式开启。

	默认关闭本身由 `test_writes_default_denied` 覆盖。
	"""
	monkeypatch.setenv("XEYO_WORKSPACE_FS_WRITABLE", "1")


def test_writes_default_denied(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""未显式开启时，直写通道必须拒绝写入与删除。"""
	monkeypatch.delenv("XEYO_WORKSPACE_FS_WRITABLE", raising=False)
	root = tmp_path / "ws"
	root.mkdir()
	(root / "notes.md").write_text("keep\n", encoding="utf-8")

	with pytest.raises(PermissionError):
		write_file(str(root), "notes.md", "hack")
	with pytest.raises(PermissionError):
		delete_path(str(root), "notes.md")

	# 内容原样保留
	assert (root / "notes.md").read_text(encoding="utf-8") == "keep\n"


def test_resolve_blocks_escape(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	outside = tmp_path / "secret.txt"
	outside.write_text("nope", encoding="utf-8")
	inside = resolve_in_workspace(str(root), "ok.txt")
	assert inside == (root / "ok.txt").resolve()
	with pytest.raises(PermissionError):
		resolve_in_workspace(str(root), "../secret.txt")


def test_list_and_read_text(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	(root / "sub").mkdir(parents=True)
	(root / "README.md").write_text("# hi\n", encoding="utf-8")
	(root / "sub" / "a.py").write_text("print(1)\n", encoding="utf-8")
	listing = list_entries(str(root), "")
	names = [e["name"] for e in listing["entries"]]
	assert "sub" in names
	assert "README.md" in names
	doc = read_file(str(root), "README.md")
	assert doc["kind"] == "text"
	assert "# hi" in doc["text"]
	assert isinstance(doc["mtime"], int)
	assert doc["mtime"] > 0
	nested = read_file(str(root), "sub/a.py")
	assert "print(1)" in nested["text"]


def test_stat_file_light(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	target = root / "a.ts"
	target.write_bytes(b"const\n")
	st = stat_file(str(root), "a.ts")
	assert st["path"] == "a.ts"
	assert st["size"] == 6
	assert isinstance(st["mtime"], int)
	assert "text" not in st
	assert "data_url" not in st
	full = read_file(str(root), "a.ts")
	assert full["mtime"] == st["mtime"]
	assert full["size"] == st["size"]


def test_read_image_data_url(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	png = (
		b"\x89PNG\r\n\x1a\n"
		+ b"\x00" * 16
	)
	(root / "dot.png").write_bytes(png)
	got = read_file(str(root), "dot.png")
	assert got["kind"] == "image"
	assert got["data_url"].startswith("data:image/png;base64,")


def test_large_utf8_read_truncated_at_char_boundary(tmp_path: Path) -> None:
	"""大 UTF-8 文件截断读：前缀可能切在多字节字符中间。

	旧行为：read(_MAX_TEXT+8) 的字节前缀 decode('utf-8') 抛错 → 整段落
	gbk(errors='replace') → 预览整屏乱码（而不是「正文 + 截断标记」）。
	构造：首字节 'a'（1B）+ 汉（3B/字），切口 400008 % 3 非整 ⇒ 必切在字中。
	"""
	root = tmp_path / "ws"
	root.mkdir()
	big = "a" + "汉" * 200_000  # utf-8 ≈ 0.58 MB，远超 400k 上限
	(root / "big.md").write_bytes(big.encode("utf-8"))

	got = read_file(str(root), "big.md")
	assert got["kind"] == "text"
	assert got["truncated"] is True
	# 乱码防线：正文必须以真实的 'a' + 连续「汉」开头（GBK 兜底会立刻变形）
	assert got["text"].startswith("a" + "汉" * 50)
	assert got["text"].endswith("…[truncated]")


def test_gbk_file_still_decodes_via_gbk(tmp_path: Path) -> None:
	"""回归护栏：真 GBK 文件路径不受边界回退修复影响。"""
	root = tmp_path / "ws"
	root.mkdir()
	(root / "gbk.txt").write_bytes("中文测试\n".encode("gbk"))

	got = read_file(str(root), "gbk.txt")
	assert got["kind"] == "text"
	assert got["text"] == "中文测试\n"


def test_write_text_roundtrip(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	(root / "notes.md").write_text("hello\n", encoding="utf-8")
	got = write_file(str(root), "notes.md", "**hello**\n")
	assert got["kind"] == "text"
	assert got["text"] == "**hello**\n"
	assert (root / "notes.md").read_text(encoding="utf-8") == "**hello**\n"


def test_write_blocks_escape(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	outside = tmp_path / "secret.txt"
	outside.write_text("keep", encoding="utf-8")
	with pytest.raises(PermissionError):
		write_file(str(root), "../secret.txt", "hack")
	assert outside.read_text(encoding="utf-8") == "keep"


def test_list_hides_internal_dirs(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	(root / ".git").mkdir(parents=True)
	(root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
	(root / ".xy-shadow-git").mkdir()
	(root / ".xeyo_uploads").mkdir()
	(root / "src").mkdir()
	listing = list_entries(str(root), "")
	names = [e["name"] for e in listing["entries"]]
	assert "src" in names
	assert ".git" not in names
	assert ".xy-shadow-git" not in names
	assert ".xeyo_uploads" not in names


def test_delete_file_and_dir(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	(root / "notes.md").write_text("hi\n", encoding="utf-8")
	(root / "sub").mkdir()
	(root / "sub" / "a.txt").write_text("a", encoding="utf-8")

	deleted = delete_path(str(root), "notes.md")
	assert deleted["ok"] is True
	assert not (root / "notes.md").exists()

	with pytest.raises(IsADirectoryError):
		delete_path(str(root), "sub")

	ok = delete_path(str(root), "sub", recursive=True)
	assert ok["ok"] is True
	assert not (root / "sub").exists()

	with pytest.raises(PermissionError):
		delete_path(str(root), ".")
	with pytest.raises(FileNotFoundError):
		delete_path(str(root), "ghost.txt")


def test_search_by_name(tmp_path: Path) -> None:
	root = tmp_path / "ws"
	root.mkdir()
	(root / "README.md").write_text("# r", encoding="utf-8")
	(root / "src").mkdir()
	(root / "src" / "xy_engine.py").write_text("x", encoding="utf-8")
	(root / ".xy-shadow-git").mkdir()
	(root / ".xy-shadow-git" / "xy_ignored.txt").write_text("x", encoding="utf-8")
	(root / "src" / "note.md").write_text("x", encoding="utf-8")

	got = search_entries(str(root), "xy")
	paths = [h["path"] for h in got["hits"]]
	assert "src/xy_engine.py" in paths
	# 内部目录被排除，即便名字匹配
	paths_all = [h["path"] for h in search_entries(str(root), "note")["hits"]]
	assert "src/note.md" in paths_all

	insensitive = search_entries(str(root), "README")
	assert [h["path"] for h in insensitive["hits"]] == ["README.md"]

	empty = search_entries(str(root), "")
	assert empty["hits"] == []
