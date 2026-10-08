"""note 可见性的**逐枪时点**模型（分析侧，非生产链路）。

两个函数都是对生产 ``session.state_projection.current_context_items`` 时间行为的
建模：给定某一枪可见的 item 序列，算出「此刻模型实际看得见的 note」。

- :func:`temporal_note_filter`——**生产形态**。每个 ``note_key`` 只留「此刻已出现的
  最新版」，旧版从原位抽走。断点只在"新版本到来的那一枪"出现；早枪仍能看到当时的
  旧版。
- :func:`temporal_fixed_filter`——**候选修法**（实测**未采用**：水位 A/B 的
  ``note_policy`` 臂无收益，台子已删除）。每个 key 保留"内容等于当前版本"的**最早**
  实例，于是同内容的重复追加成为纯 no-op（前缀零改写）。可见内容与生产形态等价，
  只差"内容没变时不动"这一条实例位置语义。

调用方只有测试（``tests/wsc/test_epoch_and_note_guards.py``）：它钉住的是上面这份
语义契约，因此留在这里、与它建模的生产语义（``session.state_projection``）同层。
"""

from __future__ import annotations

__all__ = ["temporal_fixed_filter", "temporal_note_filter"]


def temporal_note_filter(items: list[dict]) -> list[dict]:
    """生产形态的逐枪时点过滤：每个 ``note_key`` 只留"此刻已出现的最新版"。"""
    last: dict[str, int] = {}
    for i, m in enumerate(items):
        if m.get("note_key"):
            last[m["note_key"]] = i
    return [m for i, m in enumerate(items)
            if not m.get("note_key") or last[m["note_key"]] == i]


def temporal_fixed_filter(items: list[dict]) -> list[dict]:
    """候选修法的逐枪时点过滤：每个 key 保留"内容等于当前版本"的最早实例。"""
    current: dict[str, object] = {}
    for m in items:
        k = m.get("note_key")
        if k:
            current[k] = m.get("content")
    first: dict[str, int] = {}
    for i, m in enumerate(items):
        k = m.get("note_key")
        if k and m.get("content") == current.get(k):
            first.setdefault(k, i)
    return [m for i, m in enumerate(items)
            if not m.get("note_key") or first.get(m["note_key"]) == i]
