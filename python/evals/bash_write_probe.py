"""把「bash 重定向写了哪个文件」接到 WSC 的判据槽上（**问答集旁路，不入主链**）。

为什么需要它：容器内任务（TerminalBench evidence 47 会话）的改盘动作几乎全走
``cat > f <<'EOF'`` / ``echo … > f``，而 ``textutil.WRITE_TOOLS`` 只认
Write/Edit/apply_patch ⇒ 图里 ``is_write`` 恒 False ⇒ 问答集 A1–A3（末次写是否成功 /
写是否触及被改文件）**没有分母** ⇒ 29 个外部 verifier 真值一条都配对不上。

与权限层的分工（刻意不重叠，避免第二份口径）：

- ``permissions/bash_readonly`` 回答「这条命令能不能自动放行」；本模块只取它的
  **否定结论**做护栏——它判定整条命令结构只读时，这里绝不声称发生了写。
- 「被写的是**哪个路径**」权限层答不了：它的 ``_scan`` 识别到重定向后只回收拒绝原因
  ``redirect_write``、把 target 丢掉。所以路径抽取放这边。

**只认一种形状**：引号外的 ``>`` / ``>>`` 右值。理由不是省事，是实测——先前用
``sed -i`` / ``Set-Content`` / ``tee`` 各配一条正则时，``sed -i '28d' p4.cbl`` 抓到
脚本 ``28d``、``python3 -c "…print('>'…)…"`` 抓到代码体里的 ``=0``，等于用正则重造
shell 解析器（本仓最忌讳的脆弱面）。重定向目标在语法上就是 ``>`` 后第一个词元，
**不需要猜 arity**，所以精确。

因此**已知不识别**：程序自己改盘（``python -c`` 里 ``open(…,'w')``、``sqlite3`` DDL、
``cp``/``mv``/``install``、``sed -i``、``tee`` 无重定向形态）。这些留作报告里的一列
``write_tool_profile``，不许冒充"写识别已完备"。

注册点在 ``evals/wsc_failure_judge.py``（离线裁定器）。**未注册时 WSC 行为逐字节
不变**（``_BASH_WRITE_PROBE is None``）⇒ 旁路上线，拿到收益数据再谈并入主链。
"""

from __future__ import annotations

from permissions import bash_readonly as br
from synaptic.textutil import normalize_path, set_bash_write_probe

#: 丢弃到 null / fd 复制：不改盘。
_NULL_TARGETS = frozenset({"$null", "/dev/null", "nul", "nul:", "none"})
_QUOTES = "'\""


def _scan_redirects(command: str) -> list[str]:
	"""引号感知地取出所有 ``>`` / ``>>`` 的右值词元。"""
	out: list[str] = []
	i, n = 0, len(command)
	quote = ""
	while i < n:
		ch = command[i]
		if quote:
			if ch == "\\" and quote == '"':
				i += 2
				continue
			if ch == quote:
				quote = ""
			i += 1
			continue
		if ch in _QUOTES:
			quote = ch
			i += 1
			continue
		if ch == "\\" and i + 1 < n:
			i += 2
			continue
		if ch == "#" and (i == 0 or command[i - 1] in " \t\r\n"):
			break  # 行尾注释：后面的 `>` 是文本不是重定向
		if ch == "<" and command.startswith("<<", i):
			i = _skip_heredoc(command, i)
			continue
		if ch == "@" and command[i + 1: i + 2] in ("'", '"'):
			i = _skip_here_string(command, i)
			continue
		if ch == ">":
			j = i + 1
			while j < n and command[j] in "<>":  # `>&`、`>>`、`2>>`
				j += 1
			while j < n and command[j] in " \t":
				j += 1
			k = j
			while k < n and command[k] not in " \t\r\n;|&<>":
				k += 1
			out.append(command[j:k])
			i = k
			continue
		i += 1
	return out


def _skip_heredoc(command: str, start: int) -> int:
	"""跳过整段 heredoc **正文**（返回正文之后的下标）。

	不跳会怎样（实测）：``cat > f <<'EOF'`` 后面那段 COBOL/TSX 正文里出现的 ``>``
	会被当成新一次重定向，把正文里的 ``s``、``28d``、``=0`` 之类的片段抓成"被写路径"。
	"""
	i = start + 2
	n = len(command)
	while i < n and command[i] in " \t":
		i += 1
	dash = i < n and command[i] == "-"
	if dash:
		i += 1
		while i < n and command[i] in " \t":
			i += 1
	quote = ""
	if i < n and command[i] in _QUOTES:
		quote = command[i]
		i += 1
	j = i
	while j < n and (command[j].isalnum() or command[j] == "_" or (quote and command[j] != quote)):
		j += 1
	word = command[i:j]
	if quote:
		i = j + 1
	else:
		i = j
	if not word:
		return i
	while i < n:
		line_end = command.find("\n", i)
		if line_end < 0:
			return n
		if command[i:line_end].strip() == word:
			return line_end + 1
		i = line_end + 1
	return n


def _skip_here_string(command: str, start: int) -> int:
	"""跳过 PowerShell here-string 正文（``@'`` … ``'@`` / ``@"`` … ``"@``，闭标记须行首）。

	实测语料里 ``$html = @'<!doctype html>…'@`` 这类整段 HTML/JSX 正文，里面的
	``<html lang="zh-CN">`` 会被当成一次重定向、把 ``path``、``/svg`` 抓成"被写路径"。
	"""
	q = command[start + 1]
	i = start + 2
	n = len(command)
	while i < n:
		line_end = command.find("\n", i)
		line_end = n if line_end < 0 else line_end
		if command[i:line_end].lstrip().startswith(q + "@"):
			return line_end + 1
		i = line_end + 1
	return n


def _clean(target: str) -> str:
	t = target.strip().rstrip("),;:").strip("\"'")
	if not t or t.startswith("-") or t.startswith("&"):
		return ""
	low = t.lower()
	if low in _NULL_TARGETS or low.startswith("$") or "&1" in t or "&2" in t:
		return ""
	if t.startswith("{") or t.isdigit():
		return ""
	# 变量 / 命令替换 / Windows 环境变量目标无法静态确定 ⇒ 不猜。
	if "$" in t or "`" in t or "%" in t:
		return ""
	if "\n" in t:
		return ""
	return normalize_path(t)


def write_targets(command: str) -> tuple[str, ...]:
	"""这条 shell 命令**重定向写入**了哪些路径；判不出 ⇒ 空元组。"""
	if not isinstance(command, str) or not command.strip():
		return ()
	# 护栏：权限层的结构分析说整条只读 ⇒ 这里不得宣称有写。
	if br.verdict_kind(command) == br.READONLY:
		return ()
	out = [p for p in (_clean(t) for t in _scan_redirects(command)) if p]
	return tuple(dict.fromkeys(out))


def install() -> None:
	set_bash_write_probe(write_targets)


def uninstall() -> None:
	set_bash_write_probe(None)


__all__ = ["install", "uninstall", "write_targets"]
