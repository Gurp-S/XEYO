"""搜索排除目录（Grep / Glob 共用）。

默认排除两批目录：
- 版本控制目录（VCS）：避免元数据噪音；
- 重型/非源码目录：node_modules、构建产物、虚拟环境、缓存等。
对齐 Claude Code 的默认 ignore 行为，避免 Grep/Glob 扫进依赖树与构建产物
导致结果刷屏、截断或拖慢。

可用环境变量 ``XEYO_SEARCH_EXCLUDE``（逗号分隔）追加额外排除目录名。
"""

from __future__ import annotations

import os

VCS_DIRECTORIES_TO_EXCLUDE = (
	".git",
	".svn",
	".hg",
	".bzr",
	".jj",
	".sl",
)

HEAVY_DIRECTORIES_TO_EXCLUDE = (
	"node_modules",
	".pnpm-store",
	".venv",
	"venv",
	"__pycache__",
	".cache",
	"coverage",
	".next",
	".nuxt",
	".yarn",
	"bower_components",
	"dist",
	"build",
	"target",
)


def search_excluded_dirs() -> tuple[str, ...]:
	"""合并默认排除目录与环境变量追加项（去重，保序）。"""
	base = list(VCS_DIRECTORIES_TO_EXCLUDE) + list(HEAVY_DIRECTORIES_TO_EXCLUDE)
	extra = os.environ.get("XEYO_SEARCH_EXCLUDE", "").strip()
	if extra:
		for part in extra.split(","):
			name = part.strip()
			if name and name not in base:
				base.append(name)
	return tuple(base)


def excluded_dir_globs() -> list[str]:
	"""展开为 ripgrep 的 ``--glob`` 排除参数（扁平列表）。"""
	args: list[str] = []
	for dir_name in search_excluded_dirs():
		args += ["--glob", f"!{dir_name}"]
	args.extend(excluded_secret_globs())
	return args


AGENTIGNORE_FILENAME = ".agentignore"


def _read_agentignore_rules(path: str) -> list[str]:
	"""读取 .agentignore 的非否定行（否定行 !keep 只靠 --ignore-file 生效）。"""
	try:
		with open(path, "r", encoding="utf-8", errors="replace") as f:
			lines = f.readlines()
	except OSError:
		return []
	rules: list[str] = []
	for raw in lines:
		line = raw.strip()
		if not line or line.startswith("#") or line.startswith("!"):
			continue
		rules.append(line)
	return rules


def agentignore_args(*roots: str) -> list[str]:
	"""存在 ``.agentignore`` 时返回 ripgrep 的过滤参数（Glob/Grep 共用）。

	对传入的候选根目录（搜索根、工作区 cwd 等）逐个探测：
	- ``--ignore-file``：完整 gitignore 语义，不依赖 git 仓库；
	- 另把非否定行追加为**后置** ``--glob !rule``——rg 中命令行 --glob
	  白名单会覆盖 ignore 文件，且"后面的 glob 优先"，这样用户 glob
	  （如 ``*.log``）也无法穿透 .agentignore。
	"""
	args: list[str] = []
	seen: set[str] = set()
	for root in roots:
		if not root:
			continue
		path = os.path.abspath(os.path.join(root, AGENTIGNORE_FILENAME))
		if path in seen:
			continue
		seen.add(path)
		if os.path.isfile(path):
			args += ["--ignore-file", path]
			for rule in _read_agentignore_rules(path):
				args += ["--glob", f"!{rule}"]
	return args


def excluded_secret_globs() -> list[str]:
	"""排除密钥/凭据文件，避免 Grep/Glob 扫出敏感内容。"""
	from permissions.filesystem import DANGEROUS_FILES, DANGEROUS_SUFFIXES

	args: list[str] = []
	for name in sorted(DANGEROUS_FILES):
		args += ["--glob", f"!{name}", "--glob", f"!**/{name}"]
	for suf in DANGEROUS_SUFFIXES:
		args += ["--glob", f"!*{suf}", "--glob", f"!**/*{suf}"]
	# .ssh 目录（.git 已在 VCS 排除里）
	args += ["--glob", "!.ssh", "--glob", "!**/.ssh/**"]
	return args
