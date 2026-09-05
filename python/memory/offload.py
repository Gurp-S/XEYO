"""memory/offload — L3 外部化：超长工具结果卸载到文件 + 固定预览引用。

Link②① 统一 C0/L3 截断：>OFFLOAD_THRESHOLD 的工具结果**直接 offload**（写文件 + 固定预览引用），
**不再走 C0 截断**（8192）——避免"先截断又 offload"的双重处理。

字节稳定红线：引用文本（路径/行数/固定预览）与文件内容都**确定性**，同消息同 uid 每次生成相同引用 → KV 前缀稳定。

可通过 env 开关：XEYO_TOOL_OFFLOAD=1 开启（默认关，旁路）；XEYO_TOOL_OFFLOAD_CHARS 阈值（默认 128）；
XEYO_TOOL_OFFLOAD_PREVIEW 预览长度（默认 128）。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

OFFLOAD_THRESHOLD = int(os.environ.get("XEYO_TOOL_OFFLOAD_CHARS", "128"))
_PREVIEW = int(os.environ.get("XEYO_TOOL_OFFLOAD_PREVIEW", "128"))
_ENV = "XEYO_TOOL_OFFLOAD"


def offload_enabled() -> bool:
	"""L3 offload 是否开启（旁路默认关，字节稳定不因未读工具破坏）。"""
	return os.environ.get(_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _safe(s: str) -> str:
	return re.sub(r"[^A-Za-z0-9_.-]", "_", s or "x")[:40]


def _offload_root() -> Path:
	base = os.environ.get("XEYO_OFFLOAD_DIR", "").strip()
	if base:
		return Path(base)
	return Path(os.getcwd()) / ".xeyo_offload"


def maybe_offload(raw: str, *, msg_idx: int, uid: str) -> tuple[str, str | None]:
	"""超长工具结果：写文件 + 返回固定预览引用。返回 (投影文本, offload文件路径或None)。"""
	if len(raw) <= OFFLOAD_THRESHOLD:
		return raw, None
	p = _offload_root() / f"{msg_idx}_{_safe(uid)}.tool.txt"
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(raw, encoding="utf-8")
	n = raw.count("\n") + (1 if raw else 0)
	head = raw[:_PREVIEW].replace("\n", " ")
	tail = raw[-_PREVIEW:].replace("\n", " ")
	return (
		f"[tool offloaded: {p} ({n} lines) 头: {head} 尾: {tail} | "
		f"需细节时用工具 offload_read(path='{p}') 按行读取]",
		str(p),
	)
