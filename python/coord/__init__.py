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

权威面：``_design_drafts/distributed-agents-plan.md``（v1.1）§2/§3 阶段 0-1。
"""

from coord.config import BACKEND_FILE, BACKEND_MEMORY, coord_backend
from coord.locking import FileGuard

__all__ = ["BACKEND_FILE", "BACKEND_MEMORY", "FileGuard", "coord_backend"]
