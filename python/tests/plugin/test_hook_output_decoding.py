"""钩子输出的解码：子进程写了本地码页解不了的字节时，不许把钩子当成"成功且没有输出"。

缺陷（2026-10-03 实测复现并修复）：`extension/hooks.py::_run_one_sync` 用
`subprocess.run(..., capture_output=True, text=True)` 且**不给 encoding**，
于是按本地首选码页解码（中文 Windows=cp936，开了 UTF-8 模式则 utf-8）。
钩子是用户在 settings 里启用的**外部程序**，用什么码页不由引擎决定。

撞上不兼容字节时的真实形状不是"抛错"，而是**静默清空**：
解码异常发生在 `subprocess` 的读线程里并被吞掉，`run` 正常返回
`returncode=0` + `stdout=b""` ⇒ `_run_one_sync` 报 `status=ok`、
`run_event_hooks` 归成 **success**，连 `errors` 都不记一条
（实测：钩子明明跑了、输出被丢；声明 `fail_policy=abort` 的钩子也一样不 abort）。
⇒ 一个根本没跑通的钩子在账面上"通过"，且 fail-closed 策略被静默旁路。

修法：抓字节 + 自己按 `utf-8 → gbk → cp1252 → utf-8(replace)` 解码
（与 `tools/bash_tool/runner.py::_decode` 同一口径；不引私有函数，避免跨模块耦合）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from extension.hooks import PluginHook, _run_one_sync


def _bytes_hook(tmp_path: Path, script_body: bytes, *, fail: str = "continue") -> PluginHook:
	"""造一个真会执行的钩子：命令 = 当前解释器，脚本按给定字节原样落盘。"""
	script = tmp_path / "hook_bytes.py"
	script.write_bytes(script_body)
	return PluginHook(
		plugin_name="p_bytes",
		event="PreToolUse",
		command=Path(sys.executable),
		args=(str(script),),
		timeout_s=30.0,
		fail_policy=fail,
	)


def test_undecodable_hook_output_is_not_swallowed(tmp_path: Path) -> None:
	"""0xFF 在 utf-8 与 cp936 里都是非法字节 ⇒ 旧写法会把整段输出吞成空串。"""
	body = b"import sys\nsys.stdout.buffer.write(b'pre' + b'\\xff' + b'post\\n')\n"
	res = _run_one_sync(_bytes_hook(tmp_path, body), {"tool": "Bash"})
	assert res["status"] == "ok"
	assert res["returncode"] == 0
	assert "pre" in res["stdout"] and "post" in res["stdout"], (
		f"钩子输出被解码失败静默丢掉了：{res['stdout']!r}"
	)


def test_undecodable_output_still_visible_through_public_entry(tmp_path: Path) -> None:
	"""判据落在消费点上：`run_event_hooks` 不许把"输出解不出"的钩子报成干净的 success。

	这里用 `fail_policy=abort` 的钩子：它 exit(2)，输出带非法字节。
	旧实现下 stdout 被清空但 returncode 仍可读 ⇒ 归类正确；这条钉的是
	"解码失败不得改变归类"，防止有人把修法的副作用改成"解不出就当 success"。
	"""
	import extension.hooks as H

	body = b"import sys\nsys.stdout.buffer.write(b'no\\xffpe' + b'\\n')\nsys.exit(2)\n"
	hook = _bytes_hook(tmp_path, body, fail="abort")
	original = H._plugin_hooks
	H._plugin_hooks = lambda cfg, cwd: [hook]  # type: ignore[assignment]
	try:
		out = H.run_event_hooks("PreToolUse", str(tmp_path), {"tool": "Bash"}, config=_OnCfg())
	finally:
		H._plugin_hooks = original  # type: ignore[assignment]
	assert out.status == "abort", f"fail_policy=abort 的钩子被归成 {out.status!r}"


class _OnCfg:
	"""最小配置替身：只回答"钩子总开关开着"。"""

	def hooks_enabled(self) -> bool:
		return True

	@property
	def plugins(self):
		return {}


def test_utf8_hook_output_decodes_cleanly(tmp_path: Path) -> None:
	"""反向对照：UTF-8 中文输出必须原样可读，不许混进替换字符。"""
	body = "import sys\nsys.stdout.buffer.write('结果：通过'.encode('utf-8'))\n".encode("utf-8")
	res = _run_one_sync(_bytes_hook(tmp_path, body), {"tool": "Bash"})
	assert "通过" in res["stdout"], res["stdout"]
	replacement = chr(0xFFFD)  # 不写字面码位：同形异码位会把断言写成恒真/恒假
	assert replacement not in res["stdout"], "UTF-8 正文不该被替换字符污染"


def test_gbk_hook_output_decodes_by_fallback(tmp_path: Path) -> None:
	"""GBK 输出（PowerShell 5.1 / 老 BAT 的真实形状）走回退分支，不产生替换字符。"""
	body = "import sys\nsys.stdout.buffer.write('中文输出'.encode('gbk'))\n".encode("utf-8")
	res = _run_one_sync(_bytes_hook(tmp_path, body), {"tool": "Bash"})
	assert "中文输出" in res["stdout"], res["stdout"]


def test_empty_hook_output_is_still_empty(tmp_path: Path) -> None:
	"""反向对照：不许把"非空"断言写成恒真——真的零输出仍是零输出。"""
	res = _run_one_sync(_bytes_hook(tmp_path, b"raise SystemExit(0)\n"), {"tool": "Bash"})
	assert res["status"] == "ok"
	assert res["stdout"] == ""


def test_stderr_uses_the_same_decoder(tmp_path: Path) -> None:
	"""stderr 同罪同罚：旧写法两个流都是 text=True，任一流都能触发同一个静默清空。"""
	body = b"import sys\nsys.stderr.buffer.write(b'e' + b'\\xff' + b'ror line\\n')\n"
	res = _run_one_sync(_bytes_hook(tmp_path, body), {"tool": "Bash"})
	assert "e" in res["stderr"] and "ror line" in res["stderr"], res["stderr"]


# ---------------------------------------------------------------------------
# 同一族：`install_from_github` 里 git clone 失败时的原因串
# 旧写法 text=True 把解不出的 stderr 吞成空串 ⇒ PluginError 尾部是一片空白。


def test_clone_failure_reason_is_never_blank(monkeypatch, tmp_path: Path) -> None:
	"""git 走 GBK 码页报错时（旧写法会吞成空串）原因必须进消息。"""
	import subprocess

	import extension.plugin_fetcher as PF

	captured: dict[str, object] = {}
	gbk_err = "仓库不存在".encode("gbk")

	def fake_run(cmd, **kw):
		captured["text"] = kw.get("text")
		return subprocess.CompletedProcess(cmd, 128, b"", gbk_err)

	monkeypatch.setattr(PF.subprocess, "run", fake_run)
	with pytest.raises(PF.PluginError) as ei:
		PF.install_from_github(str(tmp_path), "acme/ghost")
	msg = str(ei.value)
	assert captured["text"] is False, "必须抓字节自己解码（text=True 会静默吞输出）"
	assert "仓库不存在" in msg, f"失败原因没落到消息里：{msg!r}"


def test_clone_failure_never_leaks_a_raw_bytes_repr(monkeypatch, tmp_path: Path) -> None:
	"""解不出的字节要变替换字符，不许把 `b'\\xff\\xfe'` 这种原始 repr 甩进用户可见消息。

	这条同时钉住两件事：① `text=False`（否则子进程给的是 str，走不到解码器）；
	② 失败消息经过解码而不是直接把 stderr 塞进 f-string。
	旧写法在真子进程下的表现是"原因被吞成空白"，在假子进程下的表现是"漏出 bytes repr"
	—— 两种都是同一处缺陷的形状，所以断言按"消息里既不能空白也不能有原始 repr"写。
	"""
	import subprocess

	import extension.plugin_fetcher as PF

	captured: dict[str, object] = {}

	def fake_run(cmd, **kw):
		captured["text"] = kw.get("text")
		return subprocess.CompletedProcess(cmd, 128, b"", bytes([0xFF, 0xFE, 0xFD]))

	monkeypatch.setattr(PF.subprocess, "run", fake_run)
	with pytest.raises(PF.PluginError) as ei:
		PF.install_from_github(str(tmp_path), "acme/ghost")
	msg = str(ei.value)
	assert captured["text"] is False, "必须抓字节再解码"
	assert "b'" not in msg, f"原始字节 repr 漏进了用户可见消息：{msg!r}"
	assert not msg.rstrip().endswith(":"), f"原因尾部空白：{msg!r}"



def test_clone_failure_without_any_output_still_names_the_exit_code(monkeypatch, tmp_path: Path) -> None:
	"""git 什么都没留下时也要说实话：不许回一句"failed: "（空原因）。"""
	import subprocess

	import extension.plugin_fetcher as PF

	def fake_run(cmd, **kw):
		return subprocess.CompletedProcess(cmd, 128, b"", b"")

	monkeypatch.setattr(PF.subprocess, "run", fake_run)
	with pytest.raises(PF.PluginError) as ei:
		PF.install_from_github(str(tmp_path), "acme/ghost")
	assert "128" in str(ei.value), str(ei.value)


def test_shared_decoder_guaranteed_properties() -> None:
	"""公共解码器只承诺四件事：不抛、UTF-8 原样、GBK 回退、非空字节不会变空串。"""
	from common.child_text import decode_child_output

	assert decode_child_output(None) == ""
	assert decode_child_output(b"") == ""
	# UTF-8 优先
	assert decode_child_output("中文 ok".encode("utf-8")) == "中文 ok"
	# GBK 回退（PowerShell 5.1 / 老 BAT 的真实形状）
	assert decode_child_output("中文输出".encode("gbk")) == "中文输出"
	# 任意恶劣字节：不抛，且"有字节"不等于"没输出"
	nasty = [
		bytes([0xFF, 0xFE, 0xFD]),
		bytes([0x81, 0x8D, 0x8F, 0x90, 0x9D]),
		b"\xc3(\xf0\x9f\xa4",  # 半个 emoji
		bytes(range(0x80, 0x100)),
	]
	for payload in nasty:
		out = decode_child_output(payload)
		assert isinstance(out, str)
		assert out != "", f"非空字节被解成空串（就是被吞掉的形状）：{payload[:8]!r}"
	assert decode_child_output(b"plain ascii") == "plain ascii"
