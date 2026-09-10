"""会话首轮环境嗅探（#8：turn=0 注入 pwd+ls 清单，零 LLM 调用）。

背景：``WorkspaceContext`` 只是 contextvars 的 cwd 绑定——没有「会话首轮把
目录事实一次注入」的逻辑。模型每开新会话常见前几轮瞎猜路径 / 重复 ``ls``/
``pwd`` 探路，白烧 LLM 轮次。本模块在**会话第一轮模型调用前**由引擎注入一份
**有界**的目录清单（纯引擎执行，不耗 LLM 调用、不消耗工具轮次）。

边界纪律：
- **有界**：只列一层、按字符预算截断（≈2KB），大仓不会把首轮上下文撑爆；
  目录不递归——递归探索留给模型按需做；
- **一次**：仅当投影历史里还没有任何 assistant 消息（新会话/无前文）时注入；
  续跑/同会话二次提问（历史含 assistant）不重复注入；
- **投影-only**：经 ``append_env_notice_pair`` 进入请求，不进 MessageStore /
  JSONL（与 T_now 环境声道同源）；side 会话与子代理不注入（窄任务不需要）；
- 旁路开关：``XEYO_FIRST_SNIFF=0`` 关闭（消融/对比用）。
"""

from __future__ import annotations

import os
from typing import Any, Optional

#: 注入文本的字符预算（防超长文件名/海量目录撑爆首轮上下文）。
_MAX_TEXT_CHARS = 2_000
#: 单条 path 显示上限（超长截断防布局崩坏）。
_MAX_NAME_CHARS = 120
#: 总条数上限（超出计数提示，不硬截断后仍然受字符预算约束）。
_MAX_ENTRIES = 80

_ENV_FLAG = "XEYO_FIRST_SNIFF"


def enabled() -> bool:
	"""旁路开关：默认开；XEYO_FIRST_SNIFF=0 关闭（消融/对比用）。"""
	raw = (os.environ.get(_ENV_FLAG, "") or "").strip()
	if not raw:
		return True
	return str(raw).lower() not in ("0", "off", "false", "no")


def is_first_engine_turn(projected: list[dict[str, Any]] | None) -> bool:
	"""历史里没有 assistant 消息 = 即将发出的第一轮模型调用。"""
	for m in projected or []:
		if isinstance(m, dict) and m.get("role") == "assistant":
			return False
	return True


def build_first_sniff_text(cwd: str) -> str:
	"""构建首轮注入文本：pwd + 顶层条目清单（有界）。cwd 无效返回空串。

	格式（供模型按需再深入）：
	    # 工作区概览（引擎注入 · 会话首轮 · 一次性）
	    cwd: <abs>
	    [d] docs/    [f] README.md   ...
	    （共 N 项，仅列前 M 项；按需用 ls/Read 深入）
	"""
	if not cwd or not isinstance(cwd, str):
		return ""
	# 观测域一致性：嗅探必须与模型的动作走同一通道（宿主 / 容器路由）。容器路由下
	# 宿主 scratch 是空目录，读它会注入一份模型看不到的清单——那是不该说的话。
	# 不可观测（None）→ 不注入（沉默），而不是退化成宿主结果。
	try:
		from tools.exec_channel import model_workspace

		display, entries = model_workspace(cwd)
	except Exception:  # noqa: BLE001 — 观测失败静默，不影响主路径
		return ""
	if entries is None:
		return ""
	if not entries:
		return f"cwd: {display}\n(空目录)" if display else ""

	# 目录优先 + 名字排序（确定性输出，便于缓存/回归）。
	entries.sort(key=lambda t: (t[1] != "d", t[0].lower()))

	lines: list[str] = [f"cwd: {display}"]
	chars = len(lines[0])
	count = 0
	truncated = 0
	for name, kind in entries:
		display = name if len(name) <= _MAX_NAME_CHARS else name[:_MAX_NAME_CHARS - 1] + "…"
		line = f"[{kind}] {display}/" if kind == "d" else f"[{kind}] {display}"
		cost = len(line) + 1
		if count >= _MAX_ENTRIES or chars + cost > _MAX_TEXT_CHARS:
			truncated += 1
			continue
		lines.append(line)
		chars += cost
		count += 1
	total = len(entries)
	if truncated or count < total:
		lines.append(f"（{total} 项，仅列 {count} 项——按需用 ls/Read 深入）")
	else:
		lines.append(f"（共 {total} 项；按需用 ls/Read 深入）")
	text = "\n".join(lines)
	return text if len(text) <= _MAX_TEXT_CHARS + 400 else text[:_MAX_TEXT_CHARS]


def maybe_first_sniff_text(
	projected: list[dict[str, Any]] | None,
	cwd: str,
	*,
	subagent: bool = False,
	side: bool = False,
) -> str:
	"""首轮嗅探装配入口：非 side / 非子代理 / 开关开 / 确系首轮 → 返回文本。"""
	if side or subagent or not enabled():
		return ""
	if not is_first_engine_turn(projected):
		return ""
	try:
		return build_first_sniff_text(cwd)
	except Exception:  # noqa: BLE001 — 嗅探失败静默，不影响主路径
		return ""
