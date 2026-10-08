"""终态裁定分类：权限层拒绝是**限制事实**，不是待修缺陷。

口径来自本会话的明确约束：

- 「⑥拒绝分类可以做，**拒绝结果不能直接等同目标终态**」⇒ 拒绝既不进
  ``[UNRESOLVED]``（它不是"还在的坑"），也**不得**被标成已解决；
- 「移出错误段后，必须保留仍有效的限制事实及其来源」⇒ 进 ``[CONSTRAINTS]``
  的文本必须原样带签名，并在行内内联 ``source=#<idx>``。

判据只认**原文里出现过的拒绝措辞**，不做任何推断；异常一律 fail-open 回
"未解决"侧（宁可多挂一条，不假装已裁定）。

实测背景（sess_mux0q86a_ea2kv9）：``[UNRESOLVED]`` 里 ``write failed: path_denied``
这类条目属权限层裁定，每次恢复都要人工重新裁定一次；9 条里的 1 条属该族。
"""

from __future__ import annotations

import re

#: 权限层拒绝的措辞面（来自产品实际发射的 detail/正文，见 ``permissions/policy.py``
#: 的 ``protected_metadata``、``write_store.py`` 的 ``path_denied``）。
_DENIAL_RE = re.compile(
	r"permission denied"
	r"|path_denied"
	r"|protected_metadata"
	r"|access is denied"
	r"|\[errno\s*13\]",
	re.I,
)


def is_terminal_denial(sig: str) -> bool:
	"""签名是否属"权限层拒绝"（限制事实，不是缺陷）。"""
	return bool(_DENIAL_RE.search(str(sig or "")))


def partition_signatures(signatures: list[str] | tuple[str, ...]) -> tuple[list[str], list[str]]:
	"""把签名分成 ``(未解决, 限制)``；判据异常时全部留在未解决侧（fail-open）。"""
	unresolved: list[str] = []
	denials: list[str] = []
	try:
		for s in signatures:
			(denials if is_terminal_denial(s) else unresolved).append(s)
	except Exception:
		return list(signatures), []
	return unresolved, denials
