# -*- coding: utf-8 -*-
"""rg → GNU grep 回退映射（容器里没有 ripgrep 时用）。

## 为什么需要

2026-09-16 实测：抽样 5 个 Terminal-Bench 任务镜像
（regex-log / openssl-selfsigned-cert / mteb-retrieve / cobol-modernization /
gpt2-codegpt）**全部没有 `rg`**，但都有 `grep` 与 `find`。而 Grep 的容器分支
走 ``run_ripgrep_lines``，rg 缺失会直接抛错——等于在评测里 Grep 完全不可用。

## 为什么映射是安全的（而不是"大致像"）

Grep 的解析层只认三种行形状，恰好与 GNU grep 逐字同形：

| 模式 | rg 输出 | grep 参数 | grep 输出 |
|---|---|---|---|
| content | ``path:line:content`` | ``grep -rn`` | ``path:line:content`` |
| count | ``path:count`` | ``grep -rc`` | ``path:count`` |
| files_with_matches | ``path`` | ``grep -rl`` | ``path`` |

## 不保证等价即拒绝

**映射不出逐字等价语义时返回 ``None``**，调用方照原样抛错——宁可让模型看到
"这个模式在本容器不可用"，也不给它一个悄悄改过语义的结果（静默错答是本轮
在批的失败形态）。
"""

from __future__ import annotations

__all__ = ["grep_argv_from_rg"]

#: 无法在 GNU grep 上保义映射的 rg 选项 → 直接拒绝。
_UNSUPPORTED = (
	"-U",
	"--multiline-dotall",
	"--multiline",
	"--type",
	"--ignore-file",
	"--json",
	"--vimgrep",
	"--pcre2",
	"-P",
)

#: 可安全丢弃的纯性能/呈现类选项（丢弃不改变"命中集合"语义）。
_DROPPABLE_WITH_VALUE = ("--max-columns",)
_DROPPABLE_FLAGS = ("--hidden", "--max-columns-preview", "--no-config", "--no-heading")


def _is_glob_like(token: str) -> bool:
	return any(ch in token for ch in "*?[")


def _glob_to_grep(value: str, out: list[str]) -> bool:
	"""``--glob`` 值 → grep 的 include/exclude；**无法保义映射时返回 False**。

	两处已知的语义陷阱（2026-09-16 实测发现，都属"静默改语义"）：
	1. 排除项若只发 ``--exclude-dir``，文件名形态的排除（``!**/credentials.json``）
	   不会生效 ⇒ 密钥文件会重新出现在搜索结果里。故排除项**同时发**
	   ``--exclude`` 与 ``--exclude-dir``（排除集是超集，方向安全）。
	2. 含 ``/`` 的**正向** glob（``--glob 'src/*.py'``）在 GNU grep 里没有等价物
	   ——``--include`` 只匹配 basename ⇒ 会静默少给结果。直接拒绝映射。
	"""
	negated = value.startswith("!")
	body = value[1:] if negated else value
	body = body.strip()
	if not body:
		return True
	if not negated and "/" in body:
		return False
	core = body
	if core.startswith("**/"):
		core = core[len("**/") :]
	if core.endswith("/**"):
		core = core[: -len("/**")]
	core = core.strip("/")
	if not core:
		return True
	if negated:
		# 文件与目录两种形态都排（见上面陷阱 1）
		out.append(f"--exclude={core}")
		out.append(f"--exclude-dir={core}")
		return True
	out.append(f"--include={body}")
	return True


def grep_argv_from_rg(args: list[str], target: str) -> list[str] | None:
	"""把 rg argv 映射为等价的 ``grep`` argv（**不含可执行文件名**）；不可映射 → None。

	``args`` 是 ``build_rg_args`` 的产物（不含最终 path 目标），``target`` 是搜索面。

	⚠️ 带**正向 glob** 时本函数返回的 argv **不可直接使用**——GNU grep 里只要出现
	``--exclude``，``--include`` 就不再过滤（2026-09-16 实测：任意一条排除都能复现，
	grep 3.11）。那种组合必须走 ``pipeline_from_rg``（find|grep）。
	"""
	out = _map_to_grep_flags(args)
	if out is None:
		return None
	try:
		from tools.container_fs import _host_shaped_to_container as _fix

		target = _fix(str(target))
	except Exception:  # noqa: BLE001
		pass
	out.append(target)
	return out


def has_include(args: list[str]) -> bool:
	"""映射结果里是否含 ``--include``（用于决定是否必须走 find 管道）。"""
	mapped = _map_to_grep_flags(args)
	return bool(mapped) and any(a.startswith("--include") for a in mapped)


def pipeline_from_rg(args: list[str], target: str) -> str | None:
	"""带正向 glob 时的正确实现：``find <target> <prune> <name 过滤> -print0 | xargs -0 grep``。

	为什么不能直接用 ``grep --include``：GNU grep 的 --exclude 会让 --include 失效，
	把不该搜的文件（含密钥文件）也搜进来。排除项是**安全相关**的，不能为了省事丢掉；
	而包含项丢了会多给结果。find 管道把两者都表达清楚：

	- 目录排除 → ``-name X -prune -o``（不下降，且不输出目录本身）
	- 文件排除 → ``! -name X``
	- 正向 glob → ``-name G``（多个取 -o）
	- 最后 ``-print0 | xargs -0 grep <flags>``（含 -H 强制带文件名，保证行形状一致）
	"""
	mapped = _map_to_grep_flags(args)
	if mapped is None:
		return None
	includes = [a.split("=", 1)[1] for a in mapped if a.startswith("--include=")]
	# 无正向 glob → 不建管道：直接 grep 已能正确处理排除（且少一层 find，风险更小）。
	if not includes:
		return None
	dir_excl = [a.split("=", 1)[1] for a in mapped if a.startswith("--exclude-dir=")]
	file_excl = [a.split("=", 1)[1] for a in mapped if a.startswith("--exclude=")]
	grep_flags = [
		a for a in mapped
		if not a.startswith(("--include=", "--exclude=", "--exclude-dir="))
	]
	# -H：经 xargs 管道输入时 GNU grep 不会自动带文件名，必须显式打开，
	# 保证输出行形状恒为 path:line:content（解析层契约）。
	if "-H" not in grep_flags:
		grep_flags.insert(0, "-H")

	parts: list[str] = []
	if dir_excl:
		# find 的转义括号：前后都要空格，否则会拼成 `\(-name`（实测报
		# "paths must precede expression"）。
		parts.append(" \\( " + " -o ".join(f"-name {_q(x)}" for x in dir_excl) + " \\) -prune -o")
	if file_excl:
		parts.append(" ".join(f"! -name {_q(x)}" for x in file_excl))
	parts.append("-type f")
	parts.append(" \\( " + " -o ".join(f"-name {_q(x)}" for x in includes) + " \\)")
	parts.append("-print0")
	find_expr = " ".join(parts)
	grep_expr = " ".join(_q(a) for a in ["grep", *grep_flags])
	# 本管道直接交给 container_exec（不过 run_argv），故必须在此自己纠正路径形态：
	# 工具层的 abspath 会把 /app/src 变成 D:\app\src（实测），喂给容器 shell 必然
	# 找不到（报 0 结果，静默空）。
	try:
		from tools.container_fs import _host_shaped_to_container as _fix

		target = _fix(str(target))
	except Exception:  # noqa: BLE001
		pass
	return f"find {_q(target)} {find_expr} | xargs -0 -r {grep_expr}"


def _q(value: str) -> str:
	"""POSIX 单引号转义（管道串用；与 container_fs._sq 同语义）。"""
	return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _map_to_grep_flags(args: list[str]) -> list[str] | None:
	"""rg argv → grep 参数列表（不含目标路径）；不可保义映射 → None。"""
	for flag in _UNSUPPORTED:
		if flag in args:
			return None

	out: list[str] = ["-r"]  # 递归
	pattern_seen = False
	i = 0
	while i < len(args):
		tok = args[i]
		if tok in _DROPPABLE_FLAGS:
			i += 1
			continue
		if tok in _DROPPABLE_WITH_VALUE:
			i += 2
			continue
		if tok == "--glob":
			if i + 1 >= len(args):
				return None
			if not _glob_to_grep(args[i + 1], out):
				return None
			i += 2
			continue
		if tok == "-e":
			if i + 1 >= len(args):
				return None
			out.extend(["-e", args[i + 1]])
			pattern_seen = True
			i += 2
			continue
		if tok in ("-i", "-l", "-c", "-n"):
			out.append(tok)
			i += 1
			continue
		if tok in ("-C", "-A", "-B"):
			if i + 1 >= len(args):
				return None
			out.extend([tok, args[i + 1]])
			i += 2
			continue
		if tok.startswith("-"):
			# 未识别的 rg 选项：不猜语义
			return None
		if not pattern_seen:
			out.extend(["-e", tok])  # 统一走 -e，避免以 - 开头的 pattern 被当选项
			pattern_seen = True
			i += 1
			continue
		return None  # 多出来的位置参数形态不在契约内
	if not pattern_seen:
		return None
	return out
