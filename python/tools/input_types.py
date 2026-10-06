"""模型工具入参的类型收口：schema 声明 string 的字段拿到非 string 时必须吵。

动机（2026-10-03 实测）：`Grep`/`Glob` 的 `path`/`glob`/`type` 在解析层写成
`x.strip() if isinstance(x, str) else None`，`pattern` 写成 `str(raw.get(...))`。
于是模型发 `glob: ["*.py"]`（列表，模型确实会发）时：

- 过滤器被**静默丢掉** ⇒ 搜遍整个工作区，却照常报 "Found 2 files"；
  实测 `glob='*.py'` → 1 个文件，`glob=['*.py']` → 2 个文件。
- `pattern: ["a"]` 被强造成字面量 `['a']`，作为正则匹配到字符类里的 `a`，
  返回一个看着合理、其实答的不是所问的结果。

两种都不是"报错"，而是**把请求换了**——模型据此得到的覆盖面比它要求的大。
本模块只做一件事：把"给了但不是 string"这种形状如实挡回去；
缺省、`null`、以及 JS 侧传来的 `"undefined"`/`"null"` 字面量仍按原口径当"没给"。
"""

from __future__ import annotations

from typing import Any

_MAX_REPR = 80


def string_field_type_error(raw: dict[str, Any], fields: tuple[str, ...]) -> str:
	"""返回给模型的错误文本；空串表示没有问题。

	只查"这个 key 出现了但不是字符串"；缺席与 None 一律放行（各工具自己按默认值处理）。
	措辞只陈述形状，不含建议。
	"""
	if not isinstance(raw, dict):
		return ""
	for name in fields:
		if name not in raw:
			continue
		value = raw[name]
		if value is None or isinstance(value, str):
			continue
		shown = repr(value)
		if len(shown) > _MAX_REPR:
			shown = shown[:_MAX_REPR] + "…"
		return f"invalid {name}: expected a string, got {type(value).__name__} {shown}"
	return ""


def _looks_numeric(text: str) -> bool:
	s = text.strip()
	if not s or s.lower() in ("undefined", "null"):
		return True          # 空串与 JS 侧占位：各工具本来就按"没给"处理
	try:
		int(float(s))
	except (ValueError, OverflowError):
		return False
	return True


def int_field_type_error(raw: dict[str, Any], fields: tuple[str, ...]) -> str:
	"""schema 声明整数/数字的字段拿到"无法当数字用"的值时如实挡回去。

	动机（2026-10-03 实测，与上面 string 分支同族）：解析层写成
	``_coerce_optional_int``——认不出的值一律返回 ``None``，而 ``None`` 的含义是
	"没给"。于是 ``Read.limit='abc'`` 读到**整份文件**（534 行 vs 要求的 5 行），
	``Read.offset='abc'`` 静默从第 1 行开始（要求第 500 行），
	``Grep.head_limit='abc'`` 完全不截断，``Grep.-A='abc'`` 上下文被丢光。
	四种都不是报错，而是**把请求换了**：模型拿到的结果面比它要求的宽（或位置不对），
	而输出看起来是一次成功的读取。

	放行口径保持与既有实现一致：缺席、``None``、空串、``"undefined"/"null"``、
	数字字符串、int/float/bool（bool 走 ``int()``）——只有"给了且无论如何也当不成数"才挡。
	"""
	if not isinstance(raw, dict):
		return ""
	for name in fields:
		if name not in raw:
			continue
		value = raw[name]
		if value is None or isinstance(value, (int, float)):
			continue
		if isinstance(value, str) and _looks_numeric(value):
			continue
		shown = repr(value)
		if len(shown) > _MAX_REPR:
			shown = shown[:_MAX_REPR] + "…"
		return f"invalid {name}: expected an integer, got {type(value).__name__} {shown}"
	return ""
