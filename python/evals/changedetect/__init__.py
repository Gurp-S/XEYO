"""changedetect —— 变更收益侦测器。

回答一个问题：**这次改动，到底让 XEYO 变好了还是变坏了？**

三层金字塔，按"噪声从零到有"排列：

  L0  surface  模型可见文本面（system / tools / T_now / slash manifest）
               零噪声 · 1 字符灵敏度 · 零成本 · 秒级
  L1  trace    引擎决策轨迹（注入载荷 + FakeModel 回放事件）
               零噪声 · 分支级灵敏度 · 零成本 · 秒级
  L2  ab       配对 A/B（真模型，McNemar + bootstrap）
               有噪声 · 灵敏度 = 预算的函数 · 明确报价 MDE

三层的关系是**互补而非替代**：
  L0/L1 会告诉你"变了一定发生了"，但不会告诉你"这是好事"；
  L2 会告诉你"是不是好事"，但它对小改动天生无力——所以它必须自报 MDE，
  低于 MDE 的差异一律标 "inconclusive"，不允许被读成"没变化"。

"完美侦测"的诚实定义：确定性层（L0+L1）是真正的完美——1 个字符、1 个
分支的改动必然被检出，且可复现；统计层（L2）不可能完美，但它把不可能性
量化成了"再花多少样本"，而不是含糊其辞。

用法见 `python -m evals.changedetect --help`；设计口径见
`docs/变更收益侦测器-20260910.md`。
"""

from __future__ import annotations

__all__ = ["canon", "stats", "surface", "trace"]

SCHEMA_VERSION = 1
