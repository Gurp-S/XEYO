"""
会话状态（SessionState）模块

定义单个 Agent 会话的核心可变状态，包括：
- 工作目录（cwd）
- 消息历史（MessageStore）
- 预算追踪（BudgetTracker）
- 中止控制（AbortController）
- 会话 ID 和持久化控制

设计目标：
  - 作为 QueryEngine 的内部状态容器，统一管理所有会话相关的可变数据。
  - 在构造时解析会话 cwd（不写进程全局）。
  - 提供 apply_cwd 方法，供 Bash cd 或 submit 更新本会话路径。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from engine.abort import AbortController
from engine.budget import BudgetTracker
from memory.working import WorkingSnapshot
from session.workspace_path import resolve_physical_cwd
from session.message_store import MessageStore


@dataclass
class SessionState:
    """
    单个 Agent 会话的状态快照，包含所有可变数据。

    字段说明：
        cwd: 当前会话工作目录（字符串路径，通常为绝对物理路径）。
        messages: 消息历史存储（MessageStore 实例），包含对话中的所有消息。
        budget: 预算追踪器，记录已用轮次、字符/费用上限等。
        abort: 中止控制器，用于取消当前正在进行的查询。
        session_id: 会话键（与 SessionPool / 磁盘文件名一致）；空则 uuid4。
        session_persistence_disabled: 是否禁用此会话的持久化（默认为 False）。
        transcript_known_ids: 已写入转录的消息 ID 集合，用于避免重复记录（去重）。
        transcript_persist_index: 已持久化到 transcript 的消息数量游标（增量写入）。

    自动行为：
        __post_init__ 解析 self.cwd 为物理路径；无效则 fallback，不写模块全局。
    """

    cwd: str
    messages: MessageStore = field(default_factory=MessageStore)
    budget: BudgetTracker = field(default_factory=BudgetTracker)
    abort: AbortController = field(default_factory=AbortController)
    session_id: str = ""
    session_persistence_disabled: bool = False
    # 已写入 transcript 的消息 id，避免重复扫盘
    transcript_known_ids: set[str] = field(default_factory=set)
    transcript_persist_index: int = 0  # 增量落盘游标：items[:index] 视为已提交
    working: WorkingSnapshot = field(default_factory=WorkingSnapshot)  # L3 机器状态引用，不含 memdir I/O

    def __post_init__(self) -> None:
        """
        构造后解析工作目录，不写入进程级全局 cwd。
        """
        if not (self.session_id or "").strip():
            self.session_id = uuid4().hex
        else:
            self.session_id = self.session_id.strip()
        try:
            self.cwd = resolve_physical_cwd(self.cwd)
        except (OSError, ValueError):
            # 允许先用占位路径；submit 阶段①再严格 set_cwd
            self.cwd = os_path_fallback(self.cwd)

    def set_session_persistence_disabled(self, disabled: bool) -> None:
        """设置当前会话是否禁用持久化。"""
        self.session_persistence_disabled = disabled

    def is_session_persistence_disabled(self) -> bool:
        """返回当前会话是否禁用持久化。"""
        return self.session_persistence_disabled

    def apply_cwd(self, path: str, relative_to: str | None = None) -> str:
        """
        更新本会话工作目录（不写进程全局）。
        """
        physical = resolve_physical_cwd(path, relative_to or self.cwd)
        self.cwd = physical
        return physical


def os_path_fallback(path: str) -> str:
    """
    当 set_cwd 因路径无效失败时，生成一个可用的 fallback 路径。

    行为：
      - 将 path 作为普通文件系统路径处理，展开 ~ 并转为绝对路径。
      - 若出现 OSError（如权限问题），则直接返回 path 或 "." 作为兜底。

    注意：此函数不验证路径是否存在，仅用于构造阶段避免异常导致对象创建失败。
    """
    import os

    try:
        return os.path.abspath(os.path.expanduser(path or "."))
    except OSError:
        return path or "."