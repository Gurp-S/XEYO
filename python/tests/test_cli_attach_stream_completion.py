"""attach 客户端必须能区分「回答完了」和「流被提前关闭」。

`data: [DONE]` 不是 JSON 对象，`parse_data_line` 一律判 None —— 所以在补上
``end_state`` 之前，**调用方看不见结束标记**：服务器中途断流（截断的回答、
异常收尾）与正常收尾在 `xeyo attach` 里完全同形，残缺答案被当成完整答案打印，
没有任何提示。GUI（``chatStream.ts`` 的 ``sawDone``）与 TUI（``incomplete_stream``）
都已经按「无 [DONE] 的 EOF 是故障形态」报错，这条把第三个客户端拉平。
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import pytest

from cli import attach_cmd, http_api


def _data_lines(payloads: list[str]) -> Iterator[str]:
	for p in payloads:
		yield f"data: {p}\n\n"


def _chunked(payloads: list[str]) -> Iterator[str]:
	"""按半行切块：SSE 的 data 行可能被 TCP 分片切开，扫描器必须跨块识别。"""
	raw = "".join(f"data: {p}\n\n" for p in payloads)
	for i in range(0, len(raw), 7):
		yield raw[i : i + 7]


# --- 单元：终止证据 ------------------------------------------------------------


def test_done_marker_is_recorded_without_changing_parsed_objects() -> None:
	payloads = [
		json.dumps({"choices": [{"delta": {"content": "前半段"}}]}),
		"[DONE]",
	]
	state: dict[str, Any] = {}
	objs = list(attach_cmd.iter_sse_objects(_data_lines(payloads), end_state=state))
	assert state.get("done") is True, "收到 [DONE] 必须记为完成"
	assert len(objs) == 1, "对象流不得因新增证据而多吞/少吐"


def test_eof_without_done_leaves_no_completion_evidence() -> None:
	payloads = [json.dumps({"choices": [{"delta": {"content": "被截断"}}]})]
	state: dict[str, Any] = {}
	objs = list(attach_cmd.iter_sse_objects(_data_lines(payloads), end_state=state))
	assert "done" not in state, "没有 [DONE] 却判完成 ⇒ 截断会被当成功"
	assert len(objs) == 1


def test_done_recognised_across_chunk_boundaries() -> None:
	state: dict[str, Any] = {}
	list(
		attach_cmd.iter_sse_objects(
			_chunked([json.dumps({"choices": [{"delta": {"content": "x"}}]}), "[DONE]"]),
			end_state=state,
		)
	)
	assert state.get("done") is True, "[DONE] 被分片切开时也必须识别"


def test_end_state_is_optional_and_legacy_call_shape_still_works() -> None:
	objs = list(
		attach_cmd.iter_sse_objects(_data_lines([json.dumps({"choices": []}), "[DONE]"]))
	)
	assert objs == [{"choices": []}], "不传 end_state 的旧调用行为必须逐字不变"


# --- 集成：attach_repl 的报错与不报错 ------------------------------------------


class _FakeConsole:
	def __init__(self) -> None:
		self.lines: list[str] = []

	def print(self, *args: Any, **kwargs: Any) -> None:
		self.lines.append(" ".join(str(a) for a in args))


class _FakeResp:
	def __init__(self, payloads: list[str]) -> None:
		self._payloads = payloads
		self.status_code = 200

	def read(self) -> bytes:
		return b""

	def iter_text(self) -> Iterator[str]:
		yield from _data_lines(self._payloads)


class _FakeStream:
	def __init__(self, resp: _FakeResp) -> None:
		self._resp = resp

	def __enter__(self) -> _FakeResp:
		return self._resp

	def __exit__(self, *exc: Any) -> bool:
		return False


class _FakeClient:
	def __init__(self, payloads: list[str]) -> None:
		self._payloads = payloads
		self.closed = False

	def stream(self, method: str, url: str, **kwargs: Any) -> _FakeStream:
		return _FakeStream(_FakeResp(self._payloads))

	def close(self) -> None:
		self.closed = True


def _drive(
	monkeypatch,
	tmp_path,
	payloads: list[str],
	*,
	json_mode: bool = False,
) -> list[str]:
	"""跑一轮 attach：读一行 → 收流 →  EOF 退出；返回期间写入 stderr 的行。"""
	_lines = iter(["看一下这个结果", EOFError()])

	def _read_line(mode: str) -> str:
		item = next(_lines)
		if isinstance(item, Exception):
			raise item
		return item

	monkeypatch.setattr(attach_cmd, "_read_line", _read_line)
	monkeypatch.setattr(attach_cmd, "ensure_utf8_stdio", lambda: None)
	monkeypatch.setattr(attach_cmd, "load_config", lambda: {})
	monkeypatch.setattr(attach_cmd, "resolve_server_base_url", lambda a, cfg=None: "http://x")
	monkeypatch.setattr(attach_cmd, "resolve_api_key", lambda a, cfg=None: "k")
	monkeypatch.setattr(attach_cmd, "resolve_provider", lambda a, cfg=None: "p")
	monkeypatch.setattr(attach_cmd, "resolve_model", lambda a, cfg=None: "m")
	monkeypatch.setattr(attach_cmd, "resolve_permission_mode", lambda a, cfg=None: "default")
	monkeypatch.setattr(attach_cmd, "resolve_cwd", lambda c: str(tmp_path))
	fake_console = _FakeConsole()
	monkeypatch.setattr(attach_cmd, "console", fake_console)
	monkeypatch.setattr(http_api, "make_client", lambda *a, **k: _FakeClient(payloads))

	monkeypatch.setattr(attach_cmd.ui, "print_banner", lambda **k: None)
	monkeypatch.setattr(attach_cmd.ui, "print_rule", lambda: None)
	monkeypatch.setattr(attach_cmd.ui, "out", _FakeConsole())

	attach_cmd.attach_repl("sess-1", json_mode=json_mode)
	return fake_console.lines


def test_truncated_stream_is_reported_as_failure(monkeypatch, tmp_path) -> None:
	err = _drive(
		monkeypatch,
		tmp_path,
		[json.dumps({"choices": [{"delta": {"content": "只到这里"}}]})],
	)
	joined = "\n".join(err)
	assert "连接中断" in joined, "无 [DONE] 的 EOF 必须出声，否则残缺答案冒充完整答案"
	assert "请重试" in joined


def test_completed_stream_reports_nothing(monkeypatch, tmp_path) -> None:
	err = _drive(
		monkeypatch,
		tmp_path,
		[json.dumps({"choices": [{"delta": {"content": "完整"}}]}), "[DONE]"],
	)
	joined = "\n".join(err)
	assert "连接中断" not in joined, "正常收尾不得报错（反向校：门不是装饰）"


def test_truncation_reported_in_json_mode_too_without_polluting_stdout(
	monkeypatch, tmp_path, capsys
) -> None:
	err = _drive(
		monkeypatch,
		tmp_path,
		[json.dumps({"choices": [{"delta": {"content": "半句"}}]})],
		json_mode=True,
	)
	assert "连接中断" in "\n".join(err)
	out = capsys.readouterr().out
	assert out.strip(), "json 模式仍要把事件吐给管道"
	assert "连接中断" not in out, "人类可读的报错不得混进 JSONL 管道"
