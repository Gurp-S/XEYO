# -*- coding: utf-8 -*-
"""可见性原语：**臂对称**的针 +「原文锚点为主 / 合成串降级为并列证据」。

为什么单独成模块：判定器一旦与投影渲染同源，臂间比较就**结构性**失效。
投影把 ``node.error_sig`` 原样写进热层（``assemble.py``：``失败: {sig}``），
而 ``error_sig`` 是**合成串**——``extract_error_sig`` 走多 group 拼接、``_refine_sig``
把异常名与编号行用 ``": "`` 焊起来（``textutil.py``），原文里根本不存在这个串
（PowerShell 把同一条消息切成 ``ResourceUnavailable: \r\nLine |\r\n   2 …``）。
于是「谁把签名抄进热层，谁就得满分」：压缩臂天然命中、原文臂天然漏失。
2026-09-21 实测（``_wsc_out/_qa_probe_sig.py``）：workspace_ui_controls /
workspace_window_layout 的 17 条带签名失败里 4 条签名在原文不可命中 ⇒
``V3`` 报出 wsc 15/15 vs nocompress 6/15，`E1` 21/22 vs 11/22。

判据纪律（三条，全部由 ``tests/test_failure_modes_judge.py`` 钉死）：

1. **主指标只用原文锚点**（从节点原文抽的连续词块）⇒ 两侧同源、对称；
2. **合成串只作并列证据**（``synth_only`` 列），不进主指标——它衡量的是「投影有没有
   抄签名」，不是「模型看不看得到信息」；
3. **两侧同一归一化**（``_norm``）。历史事故：只归一化一侧，nocompress 臂被误判成 0.47。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 锚点最小长度：更短的词块（``error`` / ``failed``）在两条臂上都能命中，没有区分度。
MIN_ANCHOR = 12

#: 无空白连续词块：标识符 / 路径 / 带标点的异常名。
_CHUNK_RE = re.compile(r"[A-Za-z0-9_./\\:@#+$%~^()\[\]{}<>=!?;,'-]{12,}")
#: 中文连续串：阈值交给 ``info_len`` 判（中文单字信息量 ≈ 两个拉丁字符）。
_HAN_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]{4,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_DIGITS_RE = re.compile(r"\d+")
_QUOTES_RE = re.compile(r"[\"'`\\]+")
_WS_RE = re.compile(r"\s+")

#: 运行器样板（每个工具结果都有）——留作锚点只会在 hostile 臂上制造假命中。
_BOILERPLATE = (
	"chunk id", "wall time", "process exited with code", "original token count",
	"output:", "system:", "elapsed", "duration",
)


def info_len(text: str) -> int:
	"""信息量近似：ASCII 字母数字/路径符号记 1、中文记 2。

	不能用字符数当阈值——``补齐超时回归测试`` 只有 8 个字符却是完整短语，而
	``4.7565`` 有 6 个字符却几乎无信息。实测：按字符数卡 12/16 会让中文 TODO 项
	**全部抽不出针**（V6 直接变 not_applicable）。
	"""
	cjk = len(_CJK_RE.findall(text))
	ascii_n = sum(1 for ch in text if ch.isascii() and (ch.isalnum() or ch in "._-/\\:"))
	return ascii_n + 2 * cjk


def _norm(text: str) -> str:
	"""检索用归一化：去引号反斜杠、数字→``#``、空白折叠。**两侧必须同走这一条**。

	只归一化一侧会把「压缩后可见」判成可见、把「原文可见」判成不可见
	（实测 nocompress 臂被误判成 0.47，见模块 docstring 第 3 条）。
	"""
	s = _QUOTES_RE.sub("", str(text or ""))
	s = _DIGITS_RE.sub("#", s)
	return _WS_RE.sub(" ", s)


def visible(text: str, needle: str) -> bool:
	"""归一化子串命中（保留旧签名，供既调用点与夹具使用）。"""
	n = _norm(needle)
	return bool(n) and n in _norm(text)


def _is_boilerplate(chunk: str) -> bool:
	low = _WS_RE.sub(" ", chunk.strip().lower())
	return any(low == b or low.startswith(b) for b in _BOILERPLATE)


def raw_anchors(text: str, *, min_len: int = MIN_ANCHOR, limit: int = 6) -> tuple[str, ...]:
	"""从**原文**抽锚点：最长的若干连续词块（确定性排序，同输入同输出）。

	锚点必须来自原文，不能来自任何渲染/合成产物——这正是本模块存在的理由。
	数字在归一化阶段会变 ``#``，故纯数字块（时间戳/计数）先剔除，避免把
	「到处都是的数字」当锚点。
	"""
	if not text:
		return ()
	chunks = set(_CHUNK_RE.findall(text)) | set(_HAN_CHUNK_RE.findall(text))
	out: list[str] = []
	for raw_chunk in chunks:
		# 先剥首尾标点再量长度：`ResourceUnavailable:` 剥掉冒号仍是 18 字符，照收；
		# `ParserError:` 剥后只剩 11 —— 它本身不够格当锚点，靠 ``fallback_anchor`` 兜底
		# （否则这类短名失败会被判成"不可见"，实测 4 条失败踩过这个假阴）。
		c = raw_chunk.strip("'-.,:;")
		if _is_boilerplate(c):
			continue
		# 阈值用信息量而不是字符数：中文 6 字 ≈ 拉丁 12 字符。
		if info_len(c) < min_len:
			continue
		digits = sum(ch.isdigit() for ch in c)
		if digits and digits * 5 >= len(c) * 3:  # 数字占比 ≥60%：时间戳 / 计数
			continue
		out.append(c)
	out.sort(key=lambda s: (-info_len(s), s))
	return tuple(out[:limit])


def fallback_anchor(text: str, *, width: int = 48, min_len: int = 16) -> str:
	"""无长词块时的兜底针：正文（``Output:`` 之后）折叠空白的头部片段。

	散文型失败（``The term 'head' is not recognized as a name of a cmdlet``）里没有
	≥12 字符的连续词块 ⇒ 旧实现抽不出锚点，``visible_any`` 直接返回 False，把**上界臂
	也判成不可见**（假阴）。兜底针与主锚点同口径（字符串子串、两侧同一归一化），
	因此不破坏臂对称。
	"""
	body = str(text or "")
	if "Output:" in body:
		body = body.split("Output:", 1)[-1]
	body = _WS_RE.sub(" ", body).strip()
	if info_len(body) < min_len:
		return ""
	return body[:width].strip()


def anchors_for(text: str, *, min_len: int = MIN_ANCHOR, limit: int = 6) -> tuple[str, ...]:
	"""判定用的针：长词块优先，抽不到则退回正文头部兜底针（**抽不到 = 判不了**）。

	返回空元组表示「这条事件无法建针」——调用方必须把它计成 ``unanchored``
	（移出分母），**不得**当成"不可见"。
	"""
	chunks = raw_anchors(text, min_len=min_len, limit=limit)
	if chunks:
		return chunks
	fb = fallback_anchor(text, min_len=max(min_len, 16))
	return (fb,) if fb else ()


def visible_any(text: str, anchors: tuple[str, ...] | list[str]) -> bool:
	"""任一原文锚点命中即算可见（主指标口径）。"""
	norm = _norm(text)
	if not norm:
		return False
	for a in anchors or ():
		n = _norm(a)
		if n and n in norm:
			return True
	return False


def synth_key(sig: str, n: int = 32) -> str:
	"""合成签名的可检索核心片段（去数字/引号、截断）——**只作并列证据**。"""
	s = _QUOTES_RE.sub("", str(sig or ""))
	s = _DIGITS_RE.sub("#", s)
	return _WS_RE.sub(" ", s).strip()[:n]


def derivable_from_raw(text: str, key: str, *, min_chunk: int = 8) -> bool:
	"""合成串的**全部长词块**是否都能在原文里找到（乱序，只要求都在）。

	这是给 ``synth_only=0`` 的补充口径：合成串整串不在原文（拼接产物），但它的
	组成部分可能都在 ⇒ 说明「原文足以推出这条签名」，与「投影抄了签名」不是
	同一件事。只作证据字段，不参与主指标。
	"""
	chunks = [c for c in _CHUNK_RE.findall(str(key or "")) if len(c) >= min_chunk]
	if not chunks:
		return False
	return all(visible(text, c) for c in chunks)


@dataclass(frozen=True)
class Visibility:
	"""一次可见性判定的完整证据：主口径 + 合成串旁证 + 可判性。

	``unanchored`` 是**判定模式**的属性，不是"锚点为空"的同义词：
	- 由 ``judge()`` 产出且建不出针 ⇒ ``unanchored=True``（该事件移出分母）；
	- 由调用方直接构造的**事实型**判定（"这一轮有没有新信息"这类由轨迹自身决定的题，
	  针就是事件本身）⇒ 保持 ``False``，照常进分母。
	"""

	raw_hit: bool = False
	synth_hit: bool = False
	anchors: tuple[str, ...] = ()
	synth_key: str = ""
	derivable: bool = False
	unanchored: bool = False

	@property
	def synth_only(self) -> bool:
		"""只有合成串命中 ⇒ 投影抄了签名但原文不支持（不计入主指标）。"""
		return bool(self.synth_hit and not self.raw_hit)

	def as_dict(self) -> dict:
		return {"raw_hit": self.raw_hit, "synth_hit": self.synth_hit,
		        "synth_only": self.synth_only, "derivable": self.derivable,
		        "unanchored": self.unanchored,
		        "anchors": list(self.anchors[:3]), "synth_key": self.synth_key}


def judge(text: str, *, raw: tuple[str, ...] | list[str] = (), synth: str = "") -> Visibility:
	"""一次判定：原文锚点（主）+ 合成签名（旁证）。

	建不出原文针 ⇒ ``unanchored=True``：调用方必须把它移出分母
	（判不了既不是失败也不是满分）。
	"""
	anchors = tuple(raw or ())
	key = synth_key(synth) if synth else ""
	return Visibility(
		raw_hit=visible_any(text, anchors),
		synth_hit=bool(key) and visible(text, key),
		anchors=anchors,
		synth_key=key,
		derivable=bool(key) and derivable_from_raw(text, key),
		unanchored=not anchors,
	)


class VisibilityLedger:
	"""汇总 N 条判定的主/旁证计数（答案构造器用）。"""

	def __init__(self) -> None:
		self.total = 0
		self.raw_yes = 0
		self.synth_only = 0
		self.derivable_yes = 0
		self.unanchored = 0
		self.events: list[dict] = []

	def add(self, vis: Visibility, **evidence) -> None:
		self.events.append({**vis.as_dict(), **evidence})
		if vis.unanchored:
			# 判不了就不进分母（缺数据既不是失败也不是满分）。
			self.unanchored += 1
			return
		self.total += 1
		self.raw_yes += int(vis.raw_hit)
		self.synth_only += int(vis.synth_only)
		self.derivable_yes += int(vis.derivable)


def ledger_pair(ledger: VisibilityLedger) -> tuple[int, int, int, list[dict]]:
	"""``(raw_yes, total, synth_only, evidence)``——失败侧证据只留前若干条。"""
	return ledger.raw_yes, ledger.total, ledger.synth_only, ledger.events


__all__ = [
	"MIN_ANCHOR",
	"Visibility",
	"VisibilityLedger",
	"_norm",
	"anchors_for",
	"derivable_from_raw",
	"fallback_anchor",
	"info_len",
	"judge",
	"ledger_pair",
	"raw_anchors",
	"synth_key",
	"visible",
	"visible_any",
]
