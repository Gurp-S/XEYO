"""`xeyo probe …`：在**新进程**里用磁盘上的当前代码跑一次装配，打印会进注意力的东西。

为什么要有它（agent 自报摩擦）：提示面 / 工具面改动都在常驻后端进程里，改完看不到效果，
只能等重启。`scripts/t_now_dryrun.py` / `scripts/tool_dryrun.py` 是止血版（独立进程 + 零
API 成本）；这里把它们收进 CLI 作为常规观测面——进程新 = 代码新。

    小写命令 == 观测；不动运行中的后端，不碰工作树。

用法::

    py -3.11 -m cli probe t-now --session sess_x --used 41000 --window 1000000
    py -3.11 -m cli probe tool --list
    py -3.11 -m cli probe tool --tool Read --args '{"file_path":"python/engine/query_loop.py"}'
"""

from __future__ import annotations

import typer

probe_app = typer.Typer(
    help="用**当前磁盘代码**（新进程）跑提示面 / 工具面，打印会进注意力的东西。",
    add_completion=False,
)

#: 观测参数原样透传给脚本：Typer 不解析它们，避免枚举/JSON 参数被 CLI 吃掉。
_PASS_THROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


@probe_app.command("t-now", context_settings=_PASS_THROUGH)
def t_now(ctx: typer.Context) -> None:
    """提示面 dry-run：打印本次新增片段的块名 / 正文 / 来源声明次数。"""
    from scripts.t_now_dryrun import main as t_now_main

    raise SystemExit(t_now_main(list(ctx.args)))


@probe_app.command("tool", context_settings=_PASS_THROUGH)
def tool(ctx: typer.Context) -> None:
    """工具面 dry-run：真跑工具，打印 content / metadata / 判定字段。"""
    from scripts.tool_dryrun import main as tool_main

    raise SystemExit(tool_main(list(ctx.args)))
