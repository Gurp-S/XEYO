"""实际投影增益门（旁路候选）：比较对象换成**两个完整 WSC 候选的长度差**。

要替换的旧口径（`runtime._c2_gain_enough` 默认支）：

```
left_chars  = 待压缩区的区间字符统计
summary_chars = 摘要文本长度（摘要为空时 = 确定性摘要的长度）
放行条件      = left_chars - summary_chars >= params.c2_min_gain_chars
```

那是**估算**：`left_chars` 是消息原文的字符数，而发射面上这段区域会变成什么，取决于
尾部预算、工具输出裁剪、`[REQUESTS]` 逐字保留的最后几条、句柄 `Read` 行等一串投影规则。
实测过这种估算会偏（同一段区域，发射面比原文短，短多少逐会话不同），所以顾问裁定
"比较对象换成两个完整 WSC 候选的长度差"，门槛常数（4,000 字符）**复用、不新造**。

形态：显式离线调用，不接入生产旗标或请求链。用同一份快照拍两张候选：

- `keep` = 这一枪不折（折叠入口全部钉死，游标不许动）
- `fold` = 这一枪折（收益门钉成放行，走生产自己的 C2 支）

两臂各自深拷贝 `WorkingSnapshot`，并换成**一次性会话名**（`_trial_id`）——取回视图与头快照
都按会话名落文件，影子档那一条事故（`wsc_shadow.view_path_for` 的约束 3）说得很清楚：
与生产共写一份视图文件会让生产头里的 `Read(offset=…)` 行号静默指错内容。测完即删这两个
trial 产物。

已知偏差（方向保守，写清楚而不是藏起来）：trial 的视图文件名比生产的长，`fold` 臂每渲染
一条 `Read(...)` 就多几个字符 ⇒ `saved_chars` 被**低估** ⇒ 这道门只会比真值更严，不会更松。
"""

from __future__ import annotations

import hashlib
import logging
from contextlib import contextmanager
from dataclasses import dataclass

#: 记账里标注这条增益是谁算的、用什么尺算的（估算值必须注明计数器）。
GAIN_ARM_CANDIDATE = "wsc_candidate_pair"
GAIN_ARM_ESTIMATE = "c2_region_minus_summary"
GAIN_COUNTER = "serialized_projection_content_char_count"


@dataclass(frozen=True)
class CandidatePair:
	"""同一决策点上两臂的发射面长度（字符）。"""

	keep_chars: int
	fold_chars: int

	@property
	def saved_chars(self) -> int:
		#: 允许为负：候选差为负意味着"折了反而更长"，那正是该拒的形态，不许截成 0。
		return self.keep_chars - self.fold_chars


def gain_ok(pair: CandidatePair, min_gain_chars: int) -> bool:
	return pair.saved_chars >= int(min_gain_chars or 0)


def _serialize(proj) -> str:
	"""与投影长度同口径的字符数：只数会被发出去的内容。"""
	out = []
	for m in proj or ():
		c = m.get("content") if isinstance(m, dict) else None
		if isinstance(c, str):
			out.append(c)
		elif isinstance(c, list):
			for b in c:
				if isinstance(b, dict):
					t = b.get("text") or b.get("content")
					if isinstance(t, str):
						out.append(t)
		elif c is not None:
			out.append(str(c))
	return "\n".join(out)


def _trial_id(sid: str) -> str:
	"""一次性会话名：trial 的产物必须与生产会话**不同文件**。

刻意做成**定长短名**（15 字符）：`_safe()` 会把会话名截到 40/64 字符，
拿 `f"{sid}#gain-trial"` 当 trial 名时，长 sid 会被截回原样 ⇒ trial 与生产**同名**，
那就是影子档事故里"覆盖生产取回视图行号"的同一形态。哈希名不存在这个问题。
"""
	digest = hashlib.sha1(str(sid or "").encode("utf-8")).hexdigest()[:12]
	return f"gt-{digest}"


@contextmanager
def _arm(*, fold: bool):
	"""把折叠入口钉成一条臂，并挡住嵌套投影回到本门（否则无限递归）。

	- `fold=False` ⇒ `try_extend_c2` 拒绝、`_c2_gain_enough` 拒绝、`note_c2` 不动游标
	  ⇒ 这一臂就是"这一枪不折"的发射面。
	- `fold=True` ⇒ `_c2_gain_enough` 钉成放行，`note_c2` 保持真身，`try_extend_c2`
	  **用 `force=True` 调真身**。这里是第二轮才抓到的坑：`force` 不放开 ⇒ 扩展支里的 θ 门
	  自己拒掉 ⇒ "折了的那一臂"根本没折 ⇒ 两臂逐字相同、`saved_chars ≡ 0`，
	  而这道门拿到 0 之后判"不折"——**结论只是把 θ 的回答抄回来，不是独立测量**。
	"""
	import copy

	import memory.runtime as rt
	from memory.working import WorkingSnapshot

	real_gain, real_ext, real_note = rt._c2_gain_enough, rt.try_extend_c2, rt.note_c2

	def stub_gain(*args, **kwargs):
		"""签名跟着 `_c2_gain_enough` 的新关键字参数走（account/cwd/context_limit）。"""
		return fold

	def stub_ext(working, messages, new_cursor, params, force=False, account=None, cwd=None):
		if account is not None:
			account["fold"] = False
			account["reason"] = "gain_trial_keep"
			account["forced"] = bool(force)
		return False

	def forced_ext(working, messages, new_cursor, params, force=False, account=None, cwd=None):
		"""反事实臂：这一枪**真折一次**会发出去什么，与 θ 此刻放不放行无关。"""
		return real_ext(working, messages, new_cursor, params, force=True, account=account, cwd=cwd)

	def stub_note(snap: WorkingSnapshot, new_cursor: int) -> None:
		pass

	rt._c2_gain_enough = stub_gain
	if fold:
		rt.try_extend_c2 = forced_ext
	else:
		rt.try_extend_c2, rt.note_c2 = stub_ext, stub_note
	# 扩展支里的软水位钩子会吃掉一次"精算名额"，trial 不该占额度。
	real_admit = None
	try:
		from memory import wsc_watermark as _wm

		real_admit = _wm.admit_assessment
		_wm.admit_assessment = lambda *a, **k: _wm.REASON_OK if fold else _wm.REASON_DISABLED
	except Exception:  # noqa: BLE001 - 钩子不在时 trial 照跑
		pass
	try:
		yield copy
	finally:
		rt._c2_gain_enough = real_gain
		rt.try_extend_c2 = real_ext
		if not fold:
			rt.note_c2 = real_note
		if real_admit is not None:
			try:
				from memory import wsc_watermark as _wm

				_wm.admit_assessment = real_admit
			except Exception:  # noqa: BLE001
				pass


def measure_pair(messages, working, new_cursor, *, cwd, context_limit):
	"""两臂各拍一份投影，返回 `(keep_chars, fold_chars)`；任何异常 ⇒ ``None``。

	绝不改动传入的 `working`：两臂都在深拷贝上跑，且用一次性会话名 ⇒ 取回视图与头快照
	落在与生产**不同的文件**里（`_trial_id`），测完即删。
	"""
	import memory.runtime as rt

	trial_sid = _trial_id(str(getattr(working, "session_id", "") or ""))
	lens = []
	try:
		for fold in (False, True):
			with _arm(fold=fold):
				proj = rt.project_for_model(
					messages, _trial_snapshot(working, trial_sid),
					context_limit=context_limit, cwd=cwd
				)
			lens.append(len(_serialize(proj)))
		return CandidatePair(keep_chars=lens[0], fold_chars=lens[1])
	except Exception:  # noqa: BLE001 - 旁路测量失败不许挡主链，调用方退回估算口径并记 arm
		# 必须留痕：这条 except 曾把一处签名不匹配藏成"永远 saved=0"，两轮测试才抓出来。
		logging.getLogger(__name__).debug("gain candidate measurement failed", exc_info=True)
		return None
	finally:
		_drop_trial_files(cwd, trial_sid)


def _drop_trial_files(cwd, trial_sid: str) -> None:
	from memory import wsc_projection, wsc_watermark

	wsc_projection._STATE.pop(wsc_projection._state_key(trial_sid, cwd), None)
	wsc_watermark.reset_session(trial_sid)
	try:
		from memory.wsc_head_store import path_for as head_path_for
		from memory.wsc_projection import _view_path_for

		for p in (_view_path_for(str(cwd or ""), trial_sid), head_path_for(trial_sid)):
			try:
				p.unlink(missing_ok=True)
			except OSError:
				pass
	except Exception:  # noqa: BLE001 - 清场失败不许把主链带倒
		logging.getLogger(__name__).debug("gain trial cleanup failed", exc_info=True)


def _trial_snapshot(working, trial_sid: str):
	"""深拷贝 + 一次性 session id：trial 不能往生产会话账上写任何东西。"""
	import copy

	trial = copy.deepcopy(working)
	trial.session_id = trial_sid
	return trial


def account_fields(pair: CandidatePair | None) -> dict[str, object]:
	"""新立字段（不原地改 `saved_net` 的含义）：进 `fold_events` 的账目。"""
	if pair is None:
		return {"gain_arm": GAIN_ARM_ESTIMATE, "projection_saved_tokens": None,
		        "gain_counter": None}
	return {
		"gain_arm": GAIN_ARM_CANDIDATE,
		"projection_saved_tokens": pair.saved_chars // 4,
		"projection_keep_chars": pair.keep_chars,
		"projection_fold_chars": pair.fold_chars,
		"gain_counter": GAIN_COUNTER,
	}
