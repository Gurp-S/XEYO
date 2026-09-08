"""同签名 · 字节级同输出折叠（R2'）——空转去噪，不做任何拦截。

判别（零误杀取向）
------------------
- 死循环 = 同签名（RepeatCallGuard.semantic_key 语义归一）且输出摘要**逐字节相同**；
- 合法轮询（后台 job 状态、长任务进度）输出通常含时间戳/进度 → 天然不命中；
- 只要求与**上一次**该签名输出相同，连续计数（``seq``）；输出一变即重置。

动作（不改历史语义）
-------------------
- 连续第 ``fold_after`` 次（默认 3）相同输出：把**该次**将写入 store / 送给模型
  的内容替换为一行解释性折叠行（首次完整输出仍在历史前部，信息无损）；
- 之后同签名持续相同：每轮只放一行**极短**计数占位（``[同前, 第 N 次]``），
  保持 tool_use ↔ tool_result 配对完整（崩溃恢复 / 投影不再重复展示整段原文）。
- **永不拒执行**：调用照常跑，只裁剪"与上次完全相同、无新增信息"的展示体积。

不变量
------
- 纯函数式状态机（每 submit 新建 → 用户输入级重置，与 RepeatCallGuard 同步）；
- 不触碰 MessageStore 的历史条目——只在结果**写入前**决定替换文本；
- 折叠行含 ``[fold]`` 前缀，与既有 [repeat] 提醒文案互不冲突（测试可精确匹配）。
"""

from __future__ import annotations

import hashlib
from typing import Any

from engine.repeat_guard import semantic_key

DEFAULT_FOLD_AFTER = 3

#: 超短占位（seq > fold_after 时使用）：既保持配对又几乎零 token。
_REPEAT_SHORT = "[fold] 与上一条输出相同（第 {n} 次连续）——详情见首次输出。"
#: 触发档的解释行：出现一次，点明引擎在做什么（C1 同精神：纯事实，
#: 不带"请继续/请换参数"类劝导）。
_FOLD_EXPLAIN = (
	"[fold] 这是同一签名的第 {n} 次调用，输出与首次逐字节相同——"
	"引擎已折叠后续重复内容以节省上下文。"
)


def _digest(content: Any) -> str:
	try:
		text = str(content or "")
		return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
	except Exception:  # noqa: BLE001
		return ""


class IdenticalResultFold:
	"""跟踪 submit 内每个 (tool, semantic_key) 相邻输出的字节级一致性。

	``process()`` 返回 ``(text_to_store, folded)``：未命中折叠返回原文 + False；
	命中返回折叠/占位文本 + True。输出变化即重置连续计数（合法轮询豁免）。
	"""

	def __init__(self, *, fold_after: int = DEFAULT_FOLD_AFTER) -> None:
		self.fold_after = max(2, int(fold_after))
		#: key → (last_digest, seq)
		self._state: dict[str, tuple[str, int]] = {}

	def process(
		self,
		tool_name: str,
		input_data: Any,
		content: Any,
	) -> tuple[str, bool]:
		"""决定写入 store 的文本。返回 (text, folded)。"""
		key = f"{tool_name}\x00{semantic_key(tool_name, input_data)}"
		d = _digest(content)
		text = str(content or "")
		last_digest, seq = self._state.get(key, ("", 0))
		if d and d == last_digest:
			seq += 1
		else:
			seq = 1
		self._state[key] = (d, seq)
		if seq < self.fold_after:
			return text, False
		if seq == self.fold_after:
			return _FOLD_EXPLAIN.format(n=seq), True
		return _REPEAT_SHORT.format(n=seq), True

	def reset(self) -> None:
		self._state.clear()
