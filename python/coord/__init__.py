"""XEYO coord：多会话/多进程协调层（分布式 agent 计划阶段 0 + 阶段 1）。

模块边界（反巨石）：
- ``config``：coord.backend 开关（memory | file，默认 memory=零行为变化）
- ``locking``：资源级跨进程文件锁（毫秒级临界区，mtime stale 回收）
- ``store``：任务 / scope 租约 / ask 队列的数据结构与纯操作
- ``file_store``：状态文件持久化（``<ws>/.xeyo/coord/`` + 全局索引 ``~/.xeyo/coord/``）
- ``presence_adapter``：session_presence 的文件后端（复用 PresenceState 逻辑）
- ``worktree``：worker worktree 生命周期（add→commit→remove，git 子进程封装）
- ``reconciler``：单点串行收敛（三路合并 rebase + update-ref ff + 冲突退回熔断）
- ``worker_pool``：claim → worktree → 执行回调 → 上交（L1 执行层）
- ``planner``：任务入表 + 认领闸门（scope 声明强制 + 租约先行拒并行）
- ``reviewer``：评审打回 + 重规划 scope 执法（findings 结构化 + scope ⊆ 原∪findings）
- ``ask_gate``：人在环 ASK 队列化（挂起即释放租约 + 超时转 pending 非丢弃）

权威面 = 本包实现（`python/coord/`）。设计来源 ``_design_drafts/distributed-agents-plan.md``
（v1.1）§2/§3 阶段 0-2 早于实现、可能漂移，**以各模块实际行为为准**。
"""

from coord.config import BACKEND_FILE, BACKEND_MEMORY, coord_backend
from coord.locking import FileGuard

__all__ = ["BACKEND_FILE", "BACKEND_MEMORY", "FileGuard", "coord_backend"]
