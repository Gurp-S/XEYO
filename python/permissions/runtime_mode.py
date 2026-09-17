"""运行时审批模式活状态源（RuntimeModeStore）。

模式是**活的会话状态**，不是每轮开工时的快照。GUI 在轮次进行中切换
审批模式时，通过 ``POST /v1/sessions/{sid}/runtime-mode`` 直接写入本 store；
``permissions.policy.permission_mode`` 在工具准入时实时读它（优先级：
store 活值 > 请求 body 显式 > config 默认），从而**同一个请求内尚未执行的
下一个工具调用立即按新意图判定**，不必等下一轮。

T26 单向性：收紧即时、放宽延后。
- 严格度排序：always(每写必问) > risk(仅风险) > never(自动放行)。
- turn 边界（``begin_turn``）拍定本轮基线；轮内 ``effective`` 返回
  ``baseline`` 与 ``requested`` 中**更严**者 —— 收紧立即生效，放宽等到
  下一 turn 才放行（防止「批准完当前危险操作后，同轮剩余调用被静默放行」）。

模型面同步已于 2026-09-15 **整条撤销**（用户裁定）：原 ``_last_broadcast``
/ ``mark_turn_broadcast`` / ``runtime_mode_snapshot_text`` 组成的 T_now 广播
（块名 ``runtime_mode_snapshot``）已删。理由：该块只陈述"现在是什么模式"，
而**真开关始终在 ToolRegistry 准入 gate**——删掉后模型能做的事一点不变，
变的只是模型"知道自己被看着"（引擎铁律 3：限制只在执行层）。本 store 保留
的职责收敛为：活值读取 + turn 边界拍定基线（``permission_mode`` 消费）。
"""

from __future__ import annotations

import threading

# 严格度序：数值越大越严格（越爱问）。
_STRICTNESS = {"always": 3, "risk": 2, "never": 1}


def normalize_mode(value: object) -> str | None:
    """归一化审批模式；非法/空返回 None；``allow`` 视同 ``never``。"""
    mode = str(value or "").strip().lower()
    if mode == "allow":
        mode = "never"
    return mode if mode in _STRICTNESS else None


def strictness(mode: str) -> int:
    return _STRICTNESS.get(mode or "", 0)


def stricter(a: str | None, b: str | None) -> str | None:
    """返回较严的模式；二者成 0（均非法/空）时返回 b（可为 None）。"""
    if a is None:
        return b
    if b is None:
        return a
    return a if strictness(a) >= strictness(b) else b


class RuntimeModeStore:
    """线程安全的 per-session 活审批模式。

    读路径（single-key get）依赖 GIL 原子，不加锁；写路径与 turn 边界
    （跨两个 dict 的复合更新）用一把锁保证一致。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: GUI 最近一次显式写入的审批模式（活值）。
        self._requested: dict[str, str] = {}
        #: 本 turn 基线（begin_turn 拍定）；轮内不因放宽而变。
        self._baseline: dict[str, str] = {}

    def set(self, session_id: str, mode: object) -> str | None:
        """写入活审批模式；非法返回 None（不写入）。

        轮内基线为**本 turn 已见的最严值**：写入更严模式时同步抬升基线，
        因此「收紧即时、放宽延后」成立 —— 一旦收紧到某档，本轮不得被放宽。
        不在此处武装广播：轮中才出现的活值不触发轮中注入（#1）。
        """
        normalized = normalize_mode(mode)
        if normalized is None:
            return None
        with self._lock:
            self._requested[session_id] = normalized
            baseline = self._baseline.get(session_id)
            if baseline is not None and strictness(normalized) > strictness(baseline):
                self._baseline[session_id] = normalized
        return normalized

    def live(self, session_id: str) -> str | None:
        return self._requested.get(session_id)

    def begin_turn(self, session_id: str, default: str) -> str:
        """turn 边界：拍定基线 = 活值 or 默认。"""
        with self._lock:
            requested = self._requested.get(session_id)
            baseline = requested or normalize_mode(default) or "risk"
            self._baseline[session_id] = baseline
            return baseline

    def effective(self, session_id: str) -> str | None:
        """轮内实效模式：活值取严后返回；无活值返回 None（回退 body/config）。"""
        requested = self._requested.get(session_id)
        if requested is None:
            return None
        baseline = self._baseline.get(session_id)
        return requested if baseline is None else stricter(baseline, requested)

    def clear(self, session_id: str) -> None:
        """会话删除：清空该会话全部活状态。"""
        with self._lock:
            self._requested.pop(session_id, None)
            self._baseline.pop(session_id, None)


#: 模块级单例（懒加载由 get_runtime_mode_store 返回）；不随 import 显式实例化，
#: 避免在策略模块加载期产生循环依赖。
_store: RuntimeModeStore | None = None
_store_lock = threading.Lock()


def get_runtime_mode_store() -> RuntimeModeStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RuntimeModeStore()
    return _store
