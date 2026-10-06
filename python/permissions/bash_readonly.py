"""默认档 Bash 放行面分类器：只读类 + 本地开发工具类（结构化、保守、fail-closed）。

背景（2026-09-20 用户裁定「bash 权限策略太过了」）：默认档原先只放行**单条、无管道、
命中内置只读白名单**的命令，其余一律 ASK ⇒ Windows 上模型自然写的 PowerShell 只读
cmdlet（``Get-ChildItem``/``Get-Content``/``Select-String``…）、纯只读管道
（``rg x | head``）、构建/测试类（``npm run build``/``py -m pytest``）全部逐条确认。

本模块把「默认可自动放行」重新定义为两个**结构化**类别：

- ``readonly``：命令的**每一段**都是只读程序（含 ``|`` / ``&&`` / ``||`` / ``;`` /
  换行链接的管道与链）⇒ 自动放行。
- ``dev``：每一段都是只读或本地开发工具，且至少一段是开发工具（构建 / 测试 /
  依赖安装 / 格式化 / 代码生成 / 本地 git 变更）⇒ 自动放行。
  dev 会写工作区或本机环境（``npm run build`` 跑 package.json 脚本、``pytest`` 跑
  conftest.py 都是**执行工作区里的代码**；``pip``/``npm`` 还会写工具链缓存）——
  这是放行面的信任档，不是「只读」；调用方必须给出与只读类**不同的
  matched_rule**，便于审计与按需收紧。

**不放行（保持逐条确认）的三条独立轴**（各有自己的批准语义，不属本模块放宽面）：
1. 网络外发 / 通用取回：``curl`` / ``wget`` / ``iwr`` / ``irm`` / ``gh`` / ``ssh`` /
   ``scp`` / ``git push`` —— 与 ``WebFetch`` / ``_OUTBOUND_ASK_TOOLS`` 同轴。
2. 内联任意代码：``bash -c`` / ``pwsh -Command`` / ``python -c`` / ``node -e`` /
   ``-``(stdin 代码) / ``$()`` —— 命令里看不见可审计的脚本来源。
3. 工作区之外的**文件**写：由 ``permissions.policy`` 的写目标证明负责
   （``cp``/``mkdir``/``New-Item``/重定向等；dev 类的工具链写入不在此列）。

结构上不可判定的一律不放行（fail-closed）：重定向写、命令替换 ``$()``、反引号、
子 shell / 脚本块 ``(){}[]``、后台 ``&``、包装器（``bash``/``pwsh``/``env``/
``xargs``/``sudo``/``time``/``Start-Process``…）、写型开关
（``-OutFile`` / ``sort -o`` / ``find -exec`` / ``npm -g`` / ``pip -t``…）。

DENY 黑名单（``bash_policy._DENY_RULES``）、密钥路径、策略文件、worker 沙箱
**不在此模块放宽**：它们在 ``permissions.policy`` 更早的分支终态返回。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 放行类别（字符串常量；调用方直接用作 policy matched_rule 后缀）。
READONLY = "readonly"
DEV = "dev"

# 结构扫描拒绝原因（中性、结果型措辞：只陈述判定结果）。
R_EMPTY = "empty_command"
R_UNKNOWN = "unknown_program"
R_REDIRECT = "redirect_write"
R_SUBSTITUTION = "command_substitution"
R_BLOCK_CHAR = "subshell_or_block"
R_BACKGROUND = "background"
R_QUOTE = "unterminated_quote"

#: 包装器 / 解释器壳：把「另一个程序」当参数执行 ⇒ 不作为放行类收录。
WRAPPERS = frozenset(
	{
		"bash",
		"sh",
		"zsh",
		"dash",
		"pwsh",
		"powershell",
		"cmd",
		"cmd.exe",
		"wsl",
		"env",
		"xargs",
		"sudo",
		"doas",
		"su",
		"runas",
		"psexec",
		"nohup",
		"nice",
		"timeout",
		"time",
		"eval",
		"exec",
		"source",
		"command",
		"call",
		"start",
		"start-process",
		"invoke-command",
		"invoke-expression",
		"iex",
		"foreach-object",
		"add-type",
		"new-object",
		"get-credential",
		"read-host",
	}
)

#: 全局写型参数（前缀匹配，命中即不放行）：把结果落盘的开关。
_WRITE_FLAGS_GLOBAL = frozenset(
	{
		"-outfile",
		"--outfile",
		"--out-file",
		"-outputfile",
		"--outputfile",
		"--output-document",
		"-setcontent",
		"-addcontent",
		"-redirectstandard",
	}
)

# 只读程序表
# 只读 = 语义上只产出 stdout/stderr（读文件 / 查询 / 过滤 / 格式化）：不写工作区、
# 不改环境、不执行外部程序。窗口类过滤命令（Select-Object / Where-Object /
# Format-* / ConvertTo-Json…）只做数据变换，收录；脚本块类（ForEach-Object /
# `%` / `?`）能执行任意语句，不收录（`{}` 也在结构扫描里被拒）。

_READONLY_ANY = frozenset(
	{
		# —— 文件 / 目录读取
		"echo",
		"pwd",
		"cd",
		"dir",
		"ls",
		"ll",
		"la",
		"cat",
		"type",
		"head",
		"tail",
		"wc",
		"du",
		"df",
		"tree",
		"stat",
		"file",
		"readlink",
		"realpath",
		"basename",
		"dirname",
		"md5sum",
		"sha1sum",
		"sha256sum",
		"sha512sum",
		"xxd",
		"od",
		"strings",
		"findstr",
		"rg",
		"ripgrep",
		"grep",
		"find",
		# —— 文本变换（纯过滤）
		"sort",
		"uniq",
		"cut",
		"tr",
		"nl",
		"diff",
		"cmp",
		"jq",
		# —— 环境 / 系统信息
		"whoami",
		"hostname",
		"uname",
		"date",
		"which",
		"where",
		"where.exe",
		"printenv",
		"id",
		"groups",
		"uptime",
		"ps",
		"nproc",
		"lscpu",
		"lsblk",
		"lsof",
		"netstat",
		"ipconfig",
		"ping",
		"tracert",
		"nslookup",
		"systeminfo",
		"tasklist",
		"ver",
		"vol",
		"who",
		"w",
		"cal",
		"seq",
		"sleep",
		"true",
		"false",
		"printf",
		"test",
		# —— PowerShell 只读 cmdlet（Windows 头号噪音来源）
		"get-childitem",
		"gci",
		"get-content",
		"gc",
		"get-item",
		"gi",
		"get-itemproperty",
		"gp",
		"get-process",
		"gps",
		"get-service",
		"gsv",
		"get-location",
		"gl",
		"get-date",
		"get-command",
		"gcm",
		"get-help",
		"get-member",
		"gm",
		"get-filehash",
		"get-acl",
		"get-volume",
		"get-psdrive",
		"get-variable",
		"gv",
		"get-module",
		"get-hotfix",
		"get-eventlog",
		"get-winevent",
		"get-ciminstance",
		"gcim",
		"get-computerinfo",
		"get-package",
		"test-path",
		"resolve-path",
		"rvpa",
		"select-string",
		"sls",
		# —— 数据变换（无执行能力）
		"select-object",
		"select",
		"where-object",
		"sort-object",
		"group-object",
		"measure-object",
		"compare-object",
		"format-table",
		"ft",
		"format-list",
		"fl",
		"format-wide",
		"out-string",
		"out-null",
		"write-output",
		"write-host",
		"convertfrom-json",
		"convertto-json",
		"convertfrom-csv",
		"convertto-csv",
		"join-string",
		"split-path",
		"start-sleep",
	}
)

#: 首个子命令必须命中集合才放行（跳过前置选项）。
_SUB_READONLY: dict[str, frozenset[str]] = {
	"git": frozenset(
		{
			"status",
			"log",
			"diff",
			"show",
			"branch",
			"tag",
			"remote",
			"rev-parse",
			"describe",
			"ls-files",
			"ls-tree",
			"blame",
			"shortlog",
			"whatchanged",
			"reflog",
			"cat-file",
			"count-objects",
			"version",
			"help",
		}
	),
	"npm": frozenset({"ls", "list", "view", "info", "outdated", "-v", "--version"}),
	"pnpm": frozenset({"ls", "list", "view", "info", "outdated", "why", "-v", "--version"}),
	"yarn": frozenset({"list", "info", "why", "version", "-v", "--version"}),
	"pip": frozenset({"list", "show", "freeze", "check", "--version", "-V"}),
	"pip3": frozenset({"list", "show", "freeze", "check", "--version", "-V"}),
	"cargo": frozenset({"tree", "metadata", "version", "--version"}),
	"go": frozenset({"version", "env", "list", "doc"}),
	"dotnet": frozenset({"--info", "--list-sdks", "--list-runtimes"}),
	"kubectl": frozenset(
		{
			"get",
			"describe",
			"logs",
			"version",
			"explain",
			"api-resources",
			"api-versions",
			"cluster-info",
			"top",
		}
	),
	"docker": frozenset(
		{
			"ps",
			"images",
			"inspect",
			"logs",
			"version",
			"info",
			"stats",
			"top",
			"port",
			"history",
			"search",
		}
	),
}

#: 参数级禁写开关（只读程序里的「会落盘 / 会执行」开关）。
_DENY_FLAGS: dict[str, frozenset[str]] = {
	# GNU sort -o 直接写文件
	"sort": frozenset({"-o", "--output", "--output="}),
	# find 的执行 / 删除 / 落盘动作
	"find": frozenset(
		{
			"-exec",
			"-execdir",
			"-delete",
			"-ok",
			"-okdir",
			"-fprint",
			"-fprint0",
			"-fprintf",
			"-fls",
			"-files0-from",
		}
	),
}

# 本地开发工具表（dev 类）
# 语义上等价于「跑工作区里的代码」（构建产物、格式化结果、依赖目录、本机环境）。

_DEV_ANY = frozenset(
	{
		# —— 构建系统
		"make",
		"gmake",
		"cmake",
		"ninja",
		"meson",
		"msbuild",
		"gradle",
		"gradlew",
		"gradlew.bat",
		"mvn",
		"mvnw",
		"bazel",
		"ctest",
		"tox",
		"nox",
		"turbo",
		"nx",
		# —— 打包器 / 编译前端
		"vite",
		"webpack",
		"rollup",
		"esbuild",
		"parcel",
		"swc",
		"babel",
		"gulp",
		"grunt",
		"tsx",
		"ts-node",
		# —— 测试运行器（pytest 在旧白名单里，语义同档）
		"pytest",
		"jest",
		"vitest",
		"mocha",
		"jasmine",
		"ava",
		"tape",
		"karma",
		"playwright",
		"cypress",
		# —— 格式化 / 静态检查（会改写源文件，属工作区常规写）
		"ruff",
		"black",
		"isort",
		"flake8",
		"pylint",
		"mypy",
		"pyright",
		"prettier",
		"stylelint",
		"biome",
		"oxlint",
		"clang-format",
		"rustfmt",
		"gofmt",
		"gofumpt",
		# —— 依赖 / 环境管理
		"poetry",
		"rye",
		"pipenv",
		"uv",
		"pdm",
		"hatch",
	}
)

_SUB_DEV: dict[str, frozenset[str]] = {
	"npm": frozenset(
		{
			"install",
			"i",
			"ci",
			"run",
			"run-script",
			"test",
			"t",
			"start",
			"build",
			"rebuild",
			"pack",
			"init",
			"create",
			"link",
			"unlink",
			"prune",
			"dedupe",
			"audit",
			"fund",
			"explain",
			"docs",
			"repo",
			"root",
			"prefix",
			"bin",
			"exec",
			"outdated",
		}
	),
	"pnpm": frozenset(
		{
			"install",
			"i",
			"add",
			"remove",
			"rm",
			"update",
			"up",
			"upgrade",
			"run",
			"test",
			"build",
			"exec",
			"dedupe",
			"prune",
			"patch",
		}
	),
	"yarn": frozenset({"add", "remove", "install", "run", "test", "build", "up", "upgrade", "exec"}),
	"pip": frozenset({"install", "uninstall", "download", "wheel"}),
	"pip3": frozenset({"install", "uninstall", "download", "wheel"}),
	"cargo": frozenset(
		{"build", "test", "check", "clippy", "run", "bench", "fmt", "fix", "doc", "add", "remove"}
	),
	"go": frozenset(
		{"build", "test", "run", "vet", "generate", "fmt", "mod", "get", "install", "work"}
	),
	"dotnet": frozenset(
		{"build", "test", "run", "restore", "clean", "format", "publish", "add", "remove", "new"}
	),
	"docker": frozenset(
		{"build", "run", "exec", "compose", "start", "stop", "restart", "tag", "create", "pull"}
	),
	"git": frozenset(
		{
			"add",
			"commit",
			"checkout",
			"switch",
			"merge",
			"rebase",
			"cherry-pick",
			"stash",
			"tag",
			"branch",
			"restore",
			"revert",
			"worktree",
			"fetch",
			"pull",
			"config",
			"mv",
			"rm",
			"clean",
			"gc",
			"repack",
			"prune",
			"init",
			"clone",
			"apply",
			"am",
		}
	),
}

#: dev 类的禁写 / 外发开关。**词形开关（publish…）按整词匹配，选项（-g…）按前缀匹配**。
_DENY_FLAGS_DEV: dict[str, frozenset[str]] = {
	"npm": frozenset(
		{"-g", "--global", "publish", "unpublish", "adduser", "token", "owner", "deprecate", "star"}
	),
	"pnpm": frozenset({"-g", "--global", "publish", "unpublish", "login", "logout", "adduser", "token"}),
	"yarn": frozenset({"--global", "publish", "login", "logout", "adduser", "token", "owner"}),
	"pip": frozenset({"--target", "--prefix", "--root"}),
	"pip3": frozenset({"--target", "--prefix", "--root"}),
	"poetry": frozenset({"publish"}),
	"uv": frozenset({"publish"}),
	"pdm": frozenset({"publish"}),
	"hatch": frozenset({"publish", "version"}),
	"gradle": frozenset({"publish", "deploy"}),
	"gradlew": frozenset({"publish", "deploy"}),
	"mvn": frozenset({"deploy", "release"}),
	"mvnw": frozenset({"deploy", "release"}),
	"cargo": frozenset({"publish", "login", "owner", "yank"}),
	"go": frozenset({"publish"}),
	"dotnet": frozenset({"nuget", "push"}),
	"git": frozenset({"push", "remote", "submodule", "filter-branch", "daemon"}),
	"docker": frozenset({"push", "login", "logout", "system", "volume", "rm", "rmi", "prune"}),
}

#: `python -m <模块>` 的 dev 模块白名单（跑测试 / 检查 / 格式化 / 环境管理）。
_PY_DEV_MODULES = frozenset(
	{
		"pytest",
		"unittest",
		"ruff",
		"mypy",
		"black",
		"isort",
		"flake8",
		"pylint",
		"pyright",
		"coverage",
		"pip",
		"venv",
		"build",
		"compileall",
		"doctest",
		"json.tool",
		"timeit",
		"cProfile",
		"pydoc",
		"site",
		"sysconfig",
	}
)

_INTERPRETERS = frozenset({"python", "python3", "py", "node", "deno", "bun"})

#: 内置工具名（`npx <tool>` / `pnpm dlx <tool>` 的目标必须命中这个集合）。
_KNOWN_TOOLS = (
	_DEV_ANY
	| _READONLY_ANY
	| frozenset(_SUB_DEV)
	| frozenset(_SUB_READONLY)
	| frozenset({"tsc", "eslint", "stylelint"})
)

#: `git remote` 只有这些形态是读（`git remote add/set-url/remove` 改 .git/config）。
_GIT_REMOTE_READ_FORMS = frozenset({"show", "get-url"})

#: `git branch` / `git tag` 的写法开关（命中即不是只读，交 dev / ASK 判定）。
_GIT_BRANCH_WRITE_FLAGS = frozenset(
	{"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy", "--edit-description"}
)
_GIT_TAG_WRITE_FLAGS = frozenset(
	{"-d", "-D", "--delete", "-f", "--force", "-a", "--annotate", "-s", "--sign", "-m", "--message"}
)

#: py 启动器的版本选择子（`py -3.11 -m pytest`）。
_PY_VERSION_SELECTOR_RX = re.compile(r"^-(?:V:)?\d+(?:\.\d+)*(?:-\d+)?$", re.I)


@dataclass(frozen=True)
class Verdict:
	"""结构化裁决结果（``kind`` 为空串 = 不放行）。"""

	kind: str
	reason: str
	programs: tuple[str, ...] = ()
	segments: tuple[str, ...] = ()


def program_of_token(tok: str) -> str:
	"""命令首 token → 程序 basename（去引号/路径/.exe，小写）。"""
	t = (tok or "").strip().strip("\"'")
	t = t.lower()
	if t.endswith(".exe"):
		t = t[:-4]
	if "/" in t or "\\" in t:
		t = re.split(r"[\\/]+", t)[-1]
	return t


# 词法：引号感知的单遍扫描（分段 + 词元 + 结构拒绝）

#: 重定向到这些目标 = 丢弃输出（`>$null` / `2>&1` / `>/dev/null`），不算写。
_REDIRECT_NOOP_TARGETS = frozenset({"$null", "/dev/null", "nul"})


def _scan(text: str) -> tuple[list[list[str]], str]:
	"""扫描命令 → (分段词元列表, 拒绝原因)；拒绝原因空串 = 结构可判。"""
	segments: list[list[str]] = []
	words: list[str] = []
	buf: list[str] = []
	quote = ""
	i = 0
	n = len(text)

	def flush_word() -> None:
		if buf:
			words.append("".join(buf))
			buf.clear()

	def flush_segment() -> None:
		flush_word()
		if words:
			segments.append(list(words))
			words.clear()

	while i < n:
		ch = text[i]
		if quote:
			if ch == "\\" and quote == '"' and i + 1 < n:
				buf.append(text[i + 1])
				i += 2
				continue
			if ch == quote:
				quote = ""
				i += 1
				continue
			buf.append(ch)
			i += 1
			continue
		if ch in ("'", '"'):
			quote = ch
			i += 1
			continue
		if ch == "\\" and i + 1 < n:
			buf.append(text[i + 1])
			i += 2
			continue
		if ch == "`":
			return segments, R_SUBSTITUTION
		if ch in "(){}[]":
			return segments, R_BLOCK_CHAR
		if ch == "$":
			nxt = text[i + 1] if i + 1 < n else ""
			if nxt in ("(", "{"):
				return segments, R_SUBSTITUTION
			buf.append(ch)
			i += 1
			continue
		if ch == "&":
			if text.startswith("&&", i):
				flush_segment()
				i += 2
				continue
			return segments, R_BACKGROUND
		if ch == "|":
			flush_segment()
			i += 2 if text.startswith("||", i) else 1
			continue
		if ch == ";":
			flush_segment()
			i += 1
			continue
		if ch in "\r\n":
			flush_segment()
			i += 1
			continue
		if ch in "<>":
			j = i + 1
			while j < n and text[j] in "<>":
				j += 1
			while j < n and text[j] in " \t":
				j += 1
			# fd 复制：`2>&1` / `>&2`
			if j < n and text[j] == "&":
				k = j + 1
				while k < n and text[k].isdigit():
					k += 1
				if k == j + 1:
					return segments, R_REDIRECT
				i = k
				continue
			# 丢弃到 null：`>$null` / `2>$null` / `>/dev/null`
			if j < n and text[j] in "\"'":
				q = text[j]
				k = text.find(q, j + 1)
				k = n if k < 0 else k
				target = text[j + 1 : k].strip().lower()
				nxt = k + 1
			else:
				k = j
				while k < n and text[k] not in " \t\r\n;|&":
					k += 1
				target = text[j:k].strip().lower()
				nxt = k
			if target not in _REDIRECT_NOOP_TARGETS:
				return segments, R_REDIRECT
			i = nxt
			continue
		if ch in " \t":
			flush_word()
			i += 1
			continue
		buf.append(ch)
		i += 1

	if quote:
		return segments, R_QUOTE
	flush_segment()
	return segments, ""


def _flag_hit(args: tuple[str, ...], flags: frozenset[str]) -> bool:
	"""禁写开关命中：选项（以 - 开头）按前缀，词形开关按整词。"""
	for a in args:
		low = a.strip("\"'").lower()
		if low in flags:
			return True
		if low.startswith("-") and any(low.startswith(f) for f in flags if f.startswith("-")):
			return True
	return False


def _sub_args(args: tuple[str, ...], *, skip_opts: bool = False) -> tuple[str, ...]:
	"""跳过前置选项后的子命令及余参（`git -C x status` / `git -c k=v diff`）。"""
	if not skip_opts:
		return args
	i = 0
	while i < len(args):
		tok = args[i]
		if tok in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
			i += 2
			continue
		if tok.startswith("-"):
			i += 1
			continue
		break
	return args[i:]


def _classify(program: str, args: tuple[str, ...]) -> str:
	"""单段裁决：READONLY / DEV / ""（不放行）。"""
	if not program or program in WRAPPERS:
		return ""
	if program in ("npx", "bunx"):
		return _classify_tool_runner(args)
	if program in ("pnpm", "yarn") and args and args[0].lower() == "dlx":
		return _classify_tool_runner(args[1:])
	if program in ("npm", "pnpm", "yarn") and args and args[0].lower() == "exec":
		# 与 npx / dlx 同形：跑的是远端包里的 bin，命令里看不见可审计来源，
		# 不像 `npm run <script>`（跑工作区 package.json，脚本可读）。
		# 早前只给了 npx/dlx 内置工具表，`npm exec evil-package` 直接落进
		# _SUB_DEV["npm"] 的 "exec" 整词 ⇒ 任意包名自动放行（10-04 实测
		# evaluate_policy = ALLOW/bash_dev_tool_allow；现网 10,781 条 Bash 命令
		# 里 exec 形态 0 次 ⇒ 收口不改变任何既有工作流）。
		return _classify_tool_runner(args[1:])
	if program in _INTERPRETERS:
		return _classify_interpreter(program, args)
	if program == "tsc":
		# 编译器：--noEmit 只做检查（只读），其余会写产物
		if _flag_hit(args, frozenset({"--noemit", "--no-emit", "-v", "--version"})):
			return READONLY
		return DEV
	if program in ("eslint", "stylelint"):
		return DEV
	if program in _SUB_READONLY or program in _SUB_DEV:
		return _classify_sub(program, args)
	if _flag_hit(args, _WRITE_FLAGS_GLOBAL):
		return ""
	if program in _READONLY_ANY:
		if _flag_hit(args, _DENY_FLAGS.get(program, frozenset())):
			return ""
		return READONLY
	if program in _DEV_ANY:
		if _flag_hit(args, _DENY_FLAGS_DEV.get(program, frozenset())):
			return ""
		return DEV
	return ""


def _classify_tool_runner(args: tuple[str, ...]) -> str:
	"""`npx <tool>`：目标程序必须在已知工具表内（不认任意包名）。"""
	tail = _sub_args(args)
	if not tail:
		return ""
	target = program_of_token(tail[0])
	if target in _KNOWN_TOOLS:
		return DEV
	return ""


def _classify_sub(program: str, args: tuple[str, ...]) -> str:
	"""按首个子命令分派只读 / dev；只读优先（`npm ls` 属只读）。"""
	if _flag_hit(args, _WRITE_FLAGS_GLOBAL):
		return ""
	if _flag_hit(args, _DENY_FLAGS.get(program, frozenset())):
		return ""
	tail = _sub_args(args, skip_opts=program == "git")
	if not tail:
		return ""
	sub = tail[0].lower()
	if sub in _SUB_READONLY.get(program, frozenset()) and not _git_sub_is_write(
		program, sub, tail
	):
		return READONLY
	if _flag_hit(args, _DENY_FLAGS_DEV.get(program, frozenset())):
		return ""
	if sub in _SUB_DEV.get(program, frozenset()):
		return DEV
	return ""


def _git_sub_is_write(program: str, sub: str, tail: tuple[str, ...]) -> bool:
	"""git 的「同名子命令既是读也是写」的例外（remote add / branch -D / tag -d）。"""
	if program != "git":
		return False
	rest = tail[1:]
	if sub == "remote":
		if not rest:
			return False  # `git remote` 列远端 = 只读
		return rest[0].lower() not in _GIT_REMOTE_READ_FORMS and not rest[0].startswith("-")
	if sub == "branch":
		return _flag_hit(rest, _GIT_BRANCH_WRITE_FLAGS)
	if sub == "tag":
		return _flag_hit(rest, _GIT_TAG_WRITE_FLAGS)
	return False


def _classify_interpreter(program: str, args: tuple[str, ...]) -> str:
	"""解释器：版本探测 → 只读；`-m <已知模块>` / 工作区脚本文件 → dev。

	内联代码（``-c`` / ``-e`` / ``-Command`` / ``-``）不在放行面内：命令里看不见
	可审计的脚本来源，属模块 docstring 第 2 条「内联任意代码」轴。
	"""
	if not args:
		return ""
	if program in ("python", "python3", "py"):
		rest = args
		while rest and _PY_VERSION_SELECTOR_RX.match(rest[0]):
			rest = rest[1:]
		if not rest:
			return ""
		first = rest[0].lower()
		if first in ("-v", "--version"):
			return READONLY
		if first == "-m":
			if len(rest) >= 2:
				module = rest[1].lower()
				if module in ("pip",):
					# `python -m pip …` 与 `pip …` 同一档：守卫（--target/--prefix…）共用
					return _classify_sub("pip", rest[2:])
				if module in _PY_DEV_MODULES:
					return DEV
			return ""
		if first.startswith("-"):
			return ""
		return DEV  # python <script.py>：跑工作区里的脚本
	if program == "node":
		first = args[0].lower()
		if first in ("-v", "--version"):
			return READONLY
		if first.startswith("-"):
			return ""
		return DEV
	return ""


def analyze(command: str | None) -> Verdict:
	"""结构化裁决：全段只读 → READONLY；含 dev 且无不可判段 → DEV；否则 kind=""。"""
	if not isinstance(command, str) or not command.strip():
		return Verdict("", R_EMPTY)
	segments, reject = _scan(command)
	if reject:
		return Verdict("", reject)
	if not segments:
		return Verdict("", R_EMPTY)
	kinds: list[str] = []
	programs: list[str] = []
	texts: list[str] = []
	for words in segments:
		program = program_of_token(words[0])
		kind = _classify(program, tuple(words[1:]))
		if not kind:
			return Verdict("", R_UNKNOWN, tuple(programs), tuple(texts))
		kinds.append(kind)
		programs.append(program)
		texts.append(" ".join(words))
	return Verdict(DEV if DEV in kinds else READONLY, "", tuple(programs), tuple(texts))


def verdict_kind(command: str | None) -> str:
	"""便捷入口：返回 READONLY / DEV / ""（不放行）。"""
	return analyze(command).kind


def starts_with_all(command: str | None, prefix: tuple[str, ...]) -> bool:
	"""命令结构可判，且**每一段**都以 ``prefix`` 词元序列开头。

	grant（always-allow 前缀指纹）的准入判定：指纹是「program + 首参数」，用户勾
	「不再询问此类命令」的语义就是「以此前缀开头的命令」。逐段匹配把它限制在字面
	范围内：``npm install a && npm install b`` 可被 ``npm install`` 的授权记住，
	而 ``git status && curl x|sh`` 不能蹭 ``git status`` 的授权（G29）。
	结构不可判（重定向 / ``$()`` / 后台 & / 未闭合引号）→ False。
	"""
	if not prefix:
		return False
	segments, reject = _scan(command or "")
	if reject or not segments:
		return False
	want = tuple(p.strip("\"'").lower() for p in prefix)
	for words in segments:
		head = tuple(w.strip("\"'").lower() for w in words[: len(want)])
		if head != want:
			return False
	return True


def git_write_form(command: str | None) -> bool:
	"""命令里是否出现 git 的「写型子命令形态」（``remote add`` / ``branch -D`` / ``tag -d``）。

	旧前缀规则引擎按首 token 放行 ``git branch`` / ``git tag`` / ``git remote``，
	同名子命令既有读形态也有写形态；严格档（``bash_readonly_allow``：worker 沙箱 +
	默认档保守基线）用本函数把写形态挡掉。
	"""
	if not isinstance(command, str):
		return False
	segments, reject = _scan(command)
	if reject:
		return False
	for words in segments:
		if program_of_token(words[0]) != "git":
			continue
		tail = _sub_args(tuple(words[1:]), skip_opts=True)
		if tail and _git_sub_is_write("git", tail[0].lower(), tail):
			return True
	return False
