"""#13 截断错误行抢救 + #3 双向保留契约 回归锁。

原契约（锁死防回归）：
- 短文本原样返回、不落盘；
- 超限文本 head 20k / tail 8k 双向保留，中间有截断标记；
- 完整输出落盘可查。

#13 新增：若尾部无高信号错误行，则从中段抢救错误行拼在截断标记后——
防「报错后跟 >8k 成功输出把关键报错挤出预览」。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.truncate import (
	HEAD_CHARS,
	TAIL_CHARS,
	truncate_for_model,
)


def _mk(n: int, ch: str = "x") -> str:
	return ch * n


def test_short_text_returns_unchanged(tmp_path):
	text = "hello world"
	out, path = truncate_for_model(text, persist_dir=str(tmp_path))
	assert out == text and path is None


def test_contract_head_and_tail_both_preserved(tmp_path):
	head = "A" * HEAD_CHARS
	tail = "Z" * TAIL_CHARS
	mid = "M" * 5000
	text = head + mid + tail  # >30k → 触发截断
	out, path = truncate_for_model(text, persist_dir=str(tmp_path))
	assert path is not None
	assert out.startswith("A" * 100)
	assert "middle truncated" in out
	# 尾部 8k 在截断标记之后、落盘提示之前 → 契约：尾部必须完整保留
	before_anno = out.split("[output truncated")[0]
	assert before_anno.rstrip().endswith("Z" * 50)
	assert "[output truncated" in out
	# 完整落盘 = 原文本逐字节
	assert Path(path).read_text(encoding="utf-8") == text


def test_regression_error_in_tail_is_kept_without_excerpt(tmp_path):
	"""报错本来就在尾部 8k 内 → 走既有 tail 保留，不加多余 excerpt 标记。"""
	head = "H" * HEAD_CHARS
	between = "m" * 4000  # 中段无信号噪声（把总长推过 28k、触发 tail）
	err = "\nTraceback (most recent call last):\nValueError: bad\n"
	tail_pad = "T" * (TAIL_CHARS - len(err))  # 报错置于尾部窗口起点
	text = head + between + err + tail_pad
	assert len(text) > HEAD_CHARS + TAIL_CHARS
	out, _ = truncate_for_model(text, persist_dir=str(tmp_path))
	assert "Traceback" in out
	assert "ValueError: bad" in out
	assert "error excerpt" not in out  # 尾部已覆盖，不需要中段抢救


def test_mid_error_rescued_when_tail_is_clean_noise(tmp_path):
	"""#13 主场景：报错在中段、其后是 >8k 无信号输出 → 报错行必须被抢救。"""
	head = "H" * HEAD_CHARS
	error = (
		"\nTraceback (most recent call last):\n"
		'  File "run.py", line 4, in <module>\n    main()\n'
		"ValueError: something is wrong\n"
	)
	noise_after = "\n".join(f"step {i} ok" for i in range(4000))  # >8k 无信号
	text = head + error + "\n" + noise_after
	assert len(text) > HEAD_CHARS + TAIL_CHARS
	out, _ = truncate_for_model(text, persist_dir=str(tmp_path))
	assert "ValueError: something is wrong" in out, (
		"中段关键报错被截断丢失——#13 失效"
	)
	assert "error excerpt preserved" in out


def test_mid_error_not_duplicated_when_same_lines_repeat(tmp_path):
	head = "H" * HEAD_CHARS
	repeated = "\n".join(["Error: boom"] * 50) + "\n"
	noise = "s" * (TAIL_CHARS + 4000)
	text = head + repeated + noise
	out, _ = truncate_for_model(text, persist_dir=str(tmp_path))
	assert out.count("Error: boom") >= 1  # 至少保留一条
