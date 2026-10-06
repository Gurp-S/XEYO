"""write_store 的容器分支必须按声明编码落字节——今天它把 encoding 整个丢了。

`WriteStore._atomic_write` 自己写着"复用 write_text_file 的编码语义（utf-16-le 补 BOM）"，
宿主分支也确实补了 BOM；但它前面有一段**早退**：

    if _routed_container():
        from tools.container_fs import write_text as _cfs_write
        _cfs_write(str(path), content)   # ← 没有 encoding 形参，内部硬编码 utf-8
        return

⇒ 容器路由（dev container 工作面）下：
- UTF-16 文件被重编码成 UTF-8（且不带 BOM）；
- utf-8-sig 的 BOM 被剥掉——正是宿主路径 2026-10-03 刚消灭的那个缺陷，在容器路径原样存在；
- 而同一枪 Edit 在"容器 + 主 agent（走 write_text_file）"下是**带 BOM** 的：
  劈开的不只是宿主/容器，还有主/子 agent。

修法不是给容器分支再补一套编码逻辑（那会多出第二处权威），而是**先算一次 payload 字节、
再让两条路由各自落字节**：容器侧改用已有且同签名的 `container_fs.write_bytes`。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import write_store as ws_mod
from engine.write_store import WriteStore

BOM_UTF8_SIG = b"\xef\xbb\xbf"


def _fake_container(monkeypatch, sink: list[tuple[str, bytes]]):
	"""把容器路由打开，并把容器写入的**字节**记进 sink。

	两个候选入口都装上（`write_bytes` / `write_text`）：修复前代码走的是 `write_text`
	（它没有 encoding 形参、内部硬编码 utf-8），于是这条门会红在"BOM 被剥掉"这个
	真实后果上，而不是红在 OSError 上。sink 为空 = 本次根本没走容器分支。
	"""
	import tools.container_fs as cfs

	monkeypatch.setattr(ws_mod, "_routed_container", lambda: "ctr-fake")

	def _bytes(path: str, data: bytes) -> bool:
		sink.append((str(path), bytes(data)))
		return True

	def _text(path: str, content: str) -> bool:
		sink.append((str(path), content.encode("utf-8")))
		return True

	monkeypatch.setattr(cfs, "write_bytes", _bytes)
	monkeypatch.setattr(cfs, "write_text", _text)
	return sink


def test_container_route_honours_utf8_sig_bom(tmp_path, monkeypatch):
	sink = _fake_container(monkeypatch, [])
	Text = "中文表头,列二\n"
	WriteStore._atomic_write(tmp_path / "csv_utf8sig.csv", Text, encoding="utf-8-sig")

	assert sink, "本次没走容器分支 ⇒ 这条门是装饰"
	_captured_path, payload = sink[0]
	assert payload.startswith(BOM_UTF8_SIG), f"BOM 被剥掉：{payload[:12]!r}"
	assert payload == Text.encode("utf-8-sig")


def test_container_route_honours_utf16_bom(tmp_path, monkeypatch):
	sink = _fake_container(monkeypatch, [])
	WriteStore._atomic_write(tmp_path / "u16.txt", "héllo\n", encoding="utf-16-le")

	assert sink
	_payload = sink[0][1]
	assert _payload.startswith(b"\xff\xfe"), f"UTF-16 缺 BOM，下一次 Read 认不出编码：{_payload[:8]!r}"


def test_plain_utf8_container_write_still_has_no_bom(tmp_path, monkeypatch):
	"""反向对照：不许把"补 BOM"修成"永远补 BOM"。"""
	sink = _fake_container(monkeypatch, [])
	WriteStore._atomic_write(tmp_path / "plain.txt", "plain\n", encoding="utf-8")

	assert sink
	assert not sink[0][1].startswith(BOM_UTF8_SIG)
	assert sink[0][1] == b"plain\n"


def test_container_and_host_routes_write_identical_bytes(tmp_path, monkeypatch):
	"""两条路由的字节必须逐位相同——encoding 只有一个计算点。"""
	Text = "带中文的正文\r\n"
	sink = _fake_container(monkeypatch, [])
	WriteStore._atomic_write(tmp_path / "both.txt", Text, encoding="utf-8-sig")
	container_payload = sink[0][1]

	monkeypatch.setattr(ws_mod, "_routed_container", lambda: "")
	host_target = tmp_path / "both_host.txt"
	WriteStore._atomic_write(host_target, Text, encoding="utf-8-sig")

	assert host_target.read_bytes() == container_payload, (
		f"宿主 {host_target.read_bytes()[:12]!r} 与容器 {container_payload[:12]!r} 不是同一份字节"
	)


def test_edit_through_store_carries_bom_into_container(tmp_path, monkeypatch):
	"""端到端见证：编码事实能从 Edit 经 ChangeIntent 一路走到容器字节，而不是只在底层能力上成立。"""
	from tools.file_edit_tool.file_edit_tool import EditInput, FileEditTool
	from tools.fileio.read_state import ReadFileState
	from tools.fileio.text import get_mtime_ms

	sink = _fake_container(monkeypatch, [])
	path = tmp_path / "bommed.txt"
	path.write_bytes("alpha\nbeta\n".encode("utf-8-sig"))

	rs = ReadFileState()
	tool = FileEditTool(cwd=str(tmp_path), read_state=rs)
	tool.set_write_store(WriteStore(tmp_path))
	tool.set_agent_id("sub-1")
	text, _endings, encoding = __import__(
		"tools.fileio.text", fromlist=["read_text_file"]
	).read_text_file(str(path))
	assert encoding == "utf-8-sig", "夹具本身没带上 BOM ⇒ 下面断言测不到东西"
	rs.set_written(str(path), text, get_mtime_ms(str(path)), "s1", offset=None, limit=None)

	inp = EditInput(file_path=str(path), old_string="beta", new_string="gamma")
	assert tool.validate_input(inp).get("result") is True
	tool.call(inp)

	assert sink, "这一枪没走容器分支"
	assert sink[-1][1].startswith(BOM_UTF8_SIG), (
		f"经 store 的容器写把用户文件的 BOM 剥了：{sink[-1][1][:12]!r}"
	)
	assert sink[-1][1] == "alpha\ngamma\n".encode("utf-8-sig")
