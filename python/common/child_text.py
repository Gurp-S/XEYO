"""子进程文本输出的统一解码（Windows 码页现实）。

为什么需要它（2026-10-03 实测）：`subprocess.run(..., text=True)` 不给 `encoding` 时按
**本地首选码页**解码（中文 Windows = cp936；开了 UTF-8 模式才跟着变）。子进程是我们管不着
的外部程序：git/rg 走 UTF-8，PowerShell 5.1 与老 BAT 走 OEM/GBK，钩子脚本随作者。
撞上不兼容字节时，抛错的地方是 `subprocess` 的**读线程**，异常被它吞掉，`run()` 照常返回
`returncode=0` + **空 stdout/stderr** ⇒ 调用方看到的是"成功且没有输出"：
- 钩子被记成 success（连 `fail_policy=abort` 都被静默旁路）；
- `git clone` 失败时抛出的错误消息尾部是**空白**，用户与模型都看不到原因。

所以：抓字节，自己解码。优先 UTF-8，回退 GBK/cp1252，最后才替换 ——
与 `tools/bash_tool/runner.py::_decode` 同口径（那份在 bash 侧，这里做成公共函数供
extension/* 等更上层的调用者用，避免把 bash 拉进依赖图）。
"""

from __future__ import annotations

REPLACEMENT_CHAR = chr(0xFFFD)
_CODECS = ("utf-8", "gbk", "cp1252")


def decode_child_output(data: bytes | None) -> str:
	"""把子进程字节解码成文本；绝不抛异常，也绝不把"解不出"伪装成"没有输出"。

	返回里若含 ``REPLACEMENT_CHAR``，说明兜底替换发生过 —— 调用方可以据此如实标注，
	而不是把空串当成"子进程什么都没写"。
	"""
	if not data:
		return ""
	for codec in _CODECS:
		try:
			return data.decode(codec)
		except UnicodeDecodeError:
			continue
	return data.decode("utf-8", errors="replace")


__all__ = ["REPLACEMENT_CHAR", "decode_child_output"]
