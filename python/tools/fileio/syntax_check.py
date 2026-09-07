"""写后语法自检（#11：语法门「只拦不报」→ 错误行注入回工具结果）。

背景：``WriteStore._syntax_ok`` 只算增量布尔（py/json），不产出行列细节；
模型写了坏 JSON/坏 Python 往往看不到 json.loads/ast 的具体报错，下轮瞎改。
本模块提供**纯函数** `syntax_error_detail`：

- 只对 .py / .json 判定（与 write_store 语法门同语言面，保持一致）；
- 返回可直接注入工具结果的可行动文案（含行/列），无错返回 None；
- 引擎只展示事实、不裁决 —— 是否重写由模型决定（产品语义：允许 WIP 写盘）。

收益口径：减少「写了坏格式 → 看不见原因 → 下一轮盲改」的无效轮；成本为一次
ast/json 解析（>2MB 内容跳过，防长文件卡顿）。
"""

from __future__ import annotations

import ast
import json
import os

#: 解析上限：超大文件跳过语法自检（解析成本不值当）。
_MAX_PARSE_CHARS = 2_000_000


def syntax_error_detail(file_path: str, content: str) -> str | None:
	"""返回可行动语法错误文案（含文件类型与行列）；无错/不支持/超限返回 None。"""
	suffix = os.path.splitext(str(file_path or ""))[1].lower()
	if suffix not in (".py", ".json"):
		return None
	if not isinstance(content, str) or len(content) > _MAX_PARSE_CHARS:
		return None
	text = content or ""
	if suffix == ".py":
		try:
			ast.parse(text)
			return None
		except SyntaxError as exc:
			line = exc.lineno or 0
			off = exc.offset or 0
			msg = exc.msg or "invalid syntax"
			detail = f"Python syntax error at line {line}" + (
				f" column {off}" if off else ""
			)
			if exc.text and isinstance(exc.text, str):
				detail += f": {exc.text.strip()[:80]}"
			return f"{detail} → {msg}"
	if suffix == ".json":
		try:
			json.loads(text)
			return None
		except json.JSONDecodeError as exc:
			return (
				f"JSON parse error at line {exc.lineno} column {exc.colno} "
				f"(char {exc.pos}): {exc.msg}"
			)
	return None


def introduces_error(file_path: str, old_content: str, new_content: str) -> bool:
	"""增量判据：新内容有错且旧内容无错（旧也错 → 不提示，避免对烂文件唠叨）。"""
	if not isinstance(new_content, str) or not isinstance(old_content, str):
		return False
	if syntax_error_detail(file_path, new_content) is None:
		return False
	return syntax_error_detail(file_path, old_content) is None
