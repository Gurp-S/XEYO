"""容器路由覆盖（评测并发适配）——ContextVar 优先于进程级环境变量。

问题（p4 冒烟实测）：harbor 并发 trial 共进程时，适配器各自 setup() 往
os.environ 写 XEYO_DOCKER_CONTAINER，后写覆盖先写 → 两个 agent 的 bash
全部串进最后一个 trial 的容器（跨任务环境互染，测量无效；query-optimize
的 agent 落进 raman-fitting 容器，被误判"输入文件不存在"）。

方案：bash / job 工具的容器读取顺序 =
      ContextVar（每 trial 协程上下文隔离，适配器在 run() 内设置）
      → os.environ 回退（单 trial / GUI / 旧行为完全不变）。

本模块零依赖、零副作用；不设置 override 时所有路径字节级等价于旧行为。
"""

from __future__ import annotations

from contextvars import ContextVar
import os

_container_override: ContextVar[str] = ContextVar(
	"xeyo_docker_container_override", default=""
)


def set_container_override(cid: str) -> None:
	"""设置当前协程上下文的容器路由覆盖（空串 = 清除，回退环境变量）。"""
	_container_override.set((cid or "").strip())


def current_container() -> str:
	"""返回当前执行上下文的容器事实。

	显式的 ExecutionContext.runtime=local 会屏蔽遗留的进程环境变量，避免
	上一个 Harbor trial 的 ``XEYO_DOCKER_CONTAINER`` 污染本地/下一题；没有
	执行上下文时才保留旧的 ContextVar → env 回退链。
	"""
	try:
		from engine.workspace_context import get_execution_context

		ctx = get_execution_context()
		if ctx is not None:
			if ctx.runtime == "local":
				return ""
			if ctx.container_id:
				return ctx.container_id.strip()
	except Exception:  # noqa: BLE001 — 路由查询失败走兼容路径
		pass
	value = _container_override.get().strip()
	return value or os.environ.get("XEYO_DOCKER_CONTAINER", "").strip()
