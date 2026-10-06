"""金额取整的共享判据。

这里只做一件事：把「费用未知」（``None``，即该厂商没有权威价目）安全地穿过
取整。未知必须原样保持 ``None``，绝不落成 ``0.0`` —— 把未知读成 0 是反方向
的谎报（"免费"），和借别家价目算出一个数一样不诚实。

调用方拿到 ``None`` 时的职责：在各自界面上说明「费用未知」，而不要把 ``None``
参与算术（``None + float`` 会直接抛 ``TypeError``，把账本问题升级成崩溃）。
"""

from __future__ import annotations

import math

__all__ = ["round_money8"]


def round_money8(value: float | None) -> float | None:
	"""金额取 8 位小数；``None``（费用未知）保持 ``None``。"""
	if value is None:
		return None
	amount = float(value)
	return round(amount, 8) if math.isfinite(amount) else None
