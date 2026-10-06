"""请求 ↔ 折叠配对的**唯一**口径（旁路观测，不参与任何生产决策）。

存在的理由：所有"折叠当枪多付多少未命中"的算法都依赖"哪些厂商请求是折叠枪"，
而这件事此前没有单一实现——探针各写各的 ±2.5s 窗。实测（本机账本 263 次批准折叠）
折叠→其后第一个请求的时差 median 2.85s / p95 8.39s / max 17.8s，而相邻两次批准
折叠的间隔 p10 只有 7.2s ⇒ **任何固定秒窗都会把上一折叠的后续请求误配成下一折叠的
折叠枪**。因此这里不用秒窗，改用「下一个批准锚点为界」。

四类必须分开、不得混计的形状：

- ``pre_fold``      该会话第一个批准折叠之前的请求。
- ``fold_shot``     某次批准折叠之后、该锚点窗口内的**第一个**请求（缓存击穿只算它）。
- ``fold_retry``    与折叠枪同 ``request_id`` 或 ``attempt > 1`` 的紧随请求（重试会把
  同一次发射重复计费，必须从主统计里剔出去）。
- ``post_fold``     同一锚点窗口内的后续发射（它们享受折叠后的短投影，不是折叠代价）。

还有两种"折叠发生了但没有对应请求"的情况：锚点窗口内一个请求都没有
（``fold_without_request``，投影建好却没发出去/会话结束），以及**被拒绝的判定**
（``fold=False``）——被拒不是锚点，但它是"评估枪号"，按裁定必须与"成功折叠枪号"
分开计数，所以这里单独暴露 ``assessments``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

#: 角色标签（对外只认这四个 + ``pre_fold``）。
ROLE_PRE_FOLD = "pre_fold"
ROLE_FOLD_SHOT = "fold_shot"
ROLE_FOLD_RETRY = "fold_retry"
ROLE_POST_FOLD = "post_fold"


def _rows(path: Path) -> list[dict[str, Any]]:
	"""按行读 JSONL；坏行跳过而不是抛（账本可能被并发写截断）。"""
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			row = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(row, dict):
			out.append(row)
	return out


def read_fold_events(usage_dir: Path) -> list[dict[str, Any]]:
	"""读折叠判定账本（执行**和**被拒都在里面）。

	不在 ``usage/ledger.py`` 里加读取器：写侧留在那儿，读侧独立，避免把在途改动
	卷进这条旁路线。
	"""
	return _rows(Path(usage_dir) / "fold_events.jsonl")


def read_vendor_requests(usage_dir: Path) -> list[dict[str, Any]]:
	"""读厂商请求账本（计费口径的唯一来源）。"""
	return _rows(Path(usage_dir) / "events.jsonl")


def _ts(row: dict[str, Any]) -> float:
	try:
		return float(row.get("ts") or 0.0)
	except (TypeError, ValueError):
		return 0.0


def _int(row: dict[str, Any], key: str) -> int:
	try:
		return int(row.get(key) or 0)
	except (TypeError, ValueError):
		return 0


def _attempt_gt_one(row: dict[str, Any]) -> bool:
	raw = row.get("attempt")
	if raw is None:
		return False
	try:
		return int(raw) > 1
	except (TypeError, ValueError):
		return False


@dataclass(frozen=True)
class PairedRequest:
	"""一条厂商请求 + 它被配到的折叠锚点信息。"""

	ts: float
	session_id: str
	role: str
	prompt_tokens: int
	cache_hit: int
	cache_miss: int
	completion_tokens: int
	cost_cny: float
	request_id: str
	anchor_ts: float | None
	shots_since_fold: int
	billed: bool


@dataclass(frozen=True)
class PairingReport:
	requests: tuple[PairedRequest, ...]
	anchors: int
	fold_without_request: int
	assessments: int
	rejections: int

	def by_role(self) -> dict[str, int]:
		out = {
			ROLE_PRE_FOLD: 0,
			ROLE_FOLD_SHOT: 0,
			ROLE_FOLD_RETRY: 0,
			ROLE_POST_FOLD: 0,
		}
		for req in self.requests:
			out[req.role] = out.get(req.role, 0) + 1
		return out


def _session_groups(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
	groups: dict[str, list[dict[str, Any]]] = {}
	for row in rows:
		groups.setdefault(str(row.get("session_id") or ""), []).append(row)
	for rows_in in groups.values():
		rows_in.sort(key=_ts)
	return groups


def pair_requests_to_folds(
	requests: Iterable[dict[str, Any]],
	folds: Iterable[dict[str, Any]],
) -> PairingReport:
	"""把厂商请求按「下一个批准锚点为界」配到折叠上。

	纯函数：只吃两类账本行，不读文件、不写文件、不碰任何生产状态 ⇒ 离线台与生产
	账本可以用同一个实现，数字不会因取数路径不同而分叉。
	"""
	req_groups = _session_groups(requests)
	fold_groups = _session_groups(folds)
	paired: list[PairedRequest] = []
	anchors_total = 0
	orphan_anchors = 0
	assessments = 0
	rejections = 0

	for sid in sorted(set(req_groups) | set(fold_groups)):
		reqs = req_groups.get(sid, [])
		all_folds = fold_groups.get(sid, [])
		assessments += len(all_folds)
		rejections += sum(1 for r in all_folds if r.get("fold") is not True)
		anchors = sorted(_ts(r) for r in all_folds if r.get("fold") is True)
		anchors_total += len(anchors)

		# 每个锚点的窗口 = [anchor_ts, next_anchor_ts)；窗口内第一个请求才是折叠枪。
		first_of: dict[int, PairedRequest] = {}
		seen_in_window: dict[int, int] = {}
		out_rows: list[PairedRequest] = []
		for req in reqs:
			ts = _ts(req)
			anchor_index = -1
			for a_index, a_ts in enumerate(anchors):
				if a_ts <= ts:
					anchor_index = a_index
				else:
					break
			base = dict(
				ts=ts,
				session_id=sid,
				prompt_tokens=_int(req, "prompt_tokens"),
				cache_hit=_int(req, "cache_hit"),
				cache_miss=_int(req, "cache_miss"),
				completion_tokens=_int(req, "completion_tokens"),
				cost_cny=float(req.get("cost_cny") or 0.0),
				request_id=str(req.get("request_id") or ""),
				billed=float(req.get("cost_cny") or 0.0) > 0.0,
			)
			if anchor_index < 0:
				out_rows.append(PairedRequest(role=ROLE_PRE_FOLD, anchor_ts=None,
				                             shots_since_fold=0, **base))  # type: ignore[arg-type]
				continue
			anchor_ts = anchors[anchor_index]
			seen = seen_in_window.get(anchor_index, 0)
			seen_in_window[anchor_index] = seen + 1
			if seen == 0:
				shot = PairedRequest(role=ROLE_FOLD_SHOT, anchor_ts=anchor_ts,
				                     shots_since_fold=0, **base)  # type: ignore[arg-type]
				first_of[anchor_index] = shot
				out_rows.append(shot)
				continue
			shot = first_of[anchor_index]
			same_call = bool(base["request_id"]) and base["request_id"] == shot.request_id
			role = ROLE_FOLD_RETRY if (same_call or _attempt_gt_one(req)) else ROLE_POST_FOLD
			out_rows.append(PairedRequest(role=role, anchor_ts=anchor_ts,
			                             shots_since_fold=seen, **base))  # type: ignore[arg-type]
		orphan_anchors += len(anchors) - len(first_of)
		paired.extend(out_rows)

	paired.sort(key=lambda r: (r.session_id, r.ts))
	return PairingReport(
		requests=tuple(paired),
		anchors=anchors_total,
		fold_without_request=orphan_anchors,
		assessments=assessments,
		rejections=rejections,
	)


def fold_shot_extra_miss(report: PairingReport) -> dict[str, Any]:
	"""折叠枪相对同锚点窗口内后续发射的**每请求**未命中增量（允许为负）。

	只统计 ``fold_shot`` 与 ``post_fold``；``fold_retry`` 会把同一次发射重复计费，
	``pre_fold`` 没有可比的投影状态，两者都不进这个数。
	"""
	shots = [r.cache_miss for r in report.requests if r.role == ROLE_FOLD_SHOT]
	posts = [r.cache_miss for r in report.requests if r.role == ROLE_POST_FOLD]
	return {"fold_shot_n": len(shots), "post_fold_n": len(posts),
	        "fold_shot_miss_median": _median(shots), "post_fold_miss_median": _median(posts),
	        "extra_miss_median": _median(shots) - _median(posts)}


def _median(values: list[int]) -> float:
	if not values:
		return 0.0
	values = sorted(values)
	mid = len(values) // 2
	if len(values) % 2:
		return float(values[mid])
	return (values[mid - 1] + values[mid]) / 2.0
