"""Bash 工具描述：按**活动路由**给出与环境一致的事实（2026-09-16）。

宿主（Windows 产品）走 PowerShell；容器路由下走 Linux bash。两者此前共用一份
"Shell is PowerShell / POSIX tools are usually absent" 的描述——在容器里那是
**与环境相反的事实陈述**（容器就是 bash + coreutils）。实测 9/14 轨迹里模型没被
误导去写 PowerShell（0 次），但描述既然是事实面，就该按路由说真话。

口径纪律：只陈述环境与能力事实，不含建议/劝导（引擎铁律 #1）。
"""

BASH_TOOL_NAME = "Bash"

DESCRIPTION = """
Run a shell command. The command surface includes build/test/install, package
managers, process/network tools, and git writes. File listing, content search,
file reads, file edits, file creation, and read-only git are also exposed by
dedicated tools.
Shell is PowerShell (7 when available, else Windows PowerShell 5.1). No bash-isms:
- POSIX tools are usually absent (grep/sed/awk/head/tail/wc/which/xargs report
  "not recognized"). PowerShell provides Select-String, Get-Content,
  Select-Object, Measure-Object, Get-Command, Where-Object, and ForEach-Object.
- Redirection/env: 2>$null (not 2>/dev/null); $env:VAR (not $VAR, not export).
- Quoting: double quotes expand $var and backtick escapes; single quotes are
  literal. Example regex argument: rg 'error$' file.
- && and || work on PowerShell 7 only; on 5.1 split into separate calls.
command required; timeout ms (default 120000, max 600000). A foreground command
still running near its own timeout (min(300s, timeout×0.8)) is auto-moved to a
background job: you get the job id plus partial output immediately, and a
completion notification later; job_output exposes the completed output.
run_in_background=true starts a background job immediately.
Optional working_directory (relative to session cwd; path is constrained to the workspace).
Noisy test/build/git stdout is compacted for the model; failures are kept.
"""

#: 容器路由下的描述（评测/远程工作面）：事实与环境一致。
#: 与宿主版的差异只在**环境事实**（shell / 可用工具 / 路径语义），能力契约一致。
CONTAINER_DESCRIPTION = """
Run a shell command. The command surface includes build/test/install, package
managers, process/network tools, and git writes. File listing, content search,
file reads, file edits, file creation, and read-only git are also exposed by
dedicated tools.
Shell is bash (`bash -lc`) inside the task container; the standard POSIX toolchain
is present (grep, sed, awk, head, tail, wc, find, xargs, sort, uniq, cut, tr).
Paths are container paths — the working directory reported in the system prompt is
a path inside that container, and the dedicated file tools read/write the same
container filesystem.
command required; timeout ms (default 120000, max 600000). A foreground command
still running near its own timeout (min(300s, timeout×0.8)) is auto-moved to a
background job: you get the job id plus partial output immediately, and a
completion notification later; job_output exposes the completed output.
run_in_background=true starts a background job immediately.
Optional working_directory (absolute container path, or relative to the session cwd).
Noisy test/build/git stdout is compacted for the model; failures are kept.
"""


def describe() -> str:
	"""当前环境下应展示的 Bash 描述（宿主 PowerShell / 容器 Linux bash）。"""
	try:
		from tools.container_fs import active_container

		if active_container():
			return CONTAINER_DESCRIPTION.strip()
	except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
		pass
	return DESCRIPTION.strip()
