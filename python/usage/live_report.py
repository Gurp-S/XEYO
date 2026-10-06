"""本机用量账本的实时报表：桌面端用量页的数据面。

与 A3 快照报告的分工
------------
快照那份（``scripts/memory_stack_eval`` → ``docs/A3-monitor.html``）是**离线证据**：
按天 upsert 进 ``quality_validation.json``（表D 的行），由 schtasks 每天跑一次。
界面要吃它，就得先点一次「立即快照」才看得到今天的数据。本模块直接读同一份账本
（``~/.xeyo/usage/events.jsonl`` 与 ``c2_events.jsonl``），打开页面就是最新，且：

* 只读：不落任何文件、不写任何状态、不碰厂商接口（厂商那条路要带 key 出网，
  见 ``server/routers/usage.py`` 的 ``/v1/usage``，本模块一行都不沾）。
* 全部聚合在调用方线程里做完（路由是同步 ``def``，FastAPI 丢线程池），不占事件循环
  ⇒ 聊天流式不受影响。
* 记忆化按**文件状态**（路径 + mtime_ns + size）判定，账本一变就重算，不存在
  「界面还拿旧的」；账本没变时零成本。

口径
--
与生成器 ``_a3_snapshot_one_day`` 逐项对齐（日 / 分模型 / 分会话 / 分轮次、
无价目三分类、命中率 = hit/(hit+miss)、小时直方图按**轮次**首笔时间分桶）。
两处有意的不同：

1. 生成器给「账本里没有 ``session_id`` 的历史行」按**全局**最近一条用户消息猜归属，
   而那条消息可能来自另一个会话——猜出来的轮次标题是假的。本模块不猜：这些行归进
   一个 ``未归类（账本没有会话归属）`` 桶，并把笔数如实报成 ``unattributed_requests``。
2. 生成器的 ``accepted`` 只有快照过的天才存在；本模块把「有快照行且已验收 /
   有快照行未验收 / 根本没有快照行」分成 ``true / false / null`` 三态下发。

对账由 ``tests/test_usage_live_report.py`` 钉住：同一份账本，本模块的日合计与
生成器的日合计逐字段相等（除上面第 1 条那种行）。
"""

from __future__ import annotations

import bisect
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from usage import ledger as _ledger
from usage.pricing import BJ

__all__ = [
	"DAY_PATTERN",
	"LedgerUnreadable",
	"QUALITY_JSON",
	"report_summary",
	"report_day",
	"reset_caches_for_tests",
]

#: 轮次标签是用户消息原文，界面只渲染一行；与报告数据面同一截断长度。
_MAX_LABEL_CHARS = 160

#: ``?day=`` 的取值形态：账本按北京时间落 ``day`` 字段，日就是 ``YYYY-MM-DD``。
#: 校验只留这一道正则（不另加长度约束）——多加一道就会有两种失败回法
#: （``{"detail":[...]}`` 与 ``{"error":{...}}``），前端按 type 分文案时得先猜状态码。
#: 路由用它把畸形取值挡成 422（调用方错误），不让它退化成 500。
DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_RE = DAY_PATTERN

#: 会话键形态：账本里的 ``session_id`` 是我们自己生成的键，但账本是可以被外部脚本
#: 或旧版本写坏的文本。这里挡掉任何能拼出路径的取值（``..`` / 分隔符），落文件名仍
#: 只经 ``session.persistence.transcript_path`` 的白名单映射。
_SID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")

#: 单日下钻最多下发多少条「每枪」事件行。实测本机最忙一天 4,933 笔（2026-09-14），
#: 上界留了余量；超出只影响下钻列表（并如实报 ``events_truncated``），
#: 日合计与分模型 / 分会话仍然完整。
_MAX_DETAIL_EVENT_ROWS = 8000

#: 系统注入块的开头（引擎留痕 / 后台任务 / 通报片段），与生成器
#: ``scripts.memory_stack_eval._INJECTED_PREFIXES`` 同一份清单（对账见测试）。
#: 它们也是 role=user，不滤掉就会把「[Resume]」当成一轮真实用户输入，轮次标题与轮数一起虚高。
_INJECTED_PREFIXES = (
	"[Resume]",
	"[Background jobs]",
	"[Background Job]",
	"[继续当前任务]",
	"[继续]",
	"[System]",
	"[system]",
	"[你]",
	"<user_message",
	"<tool_output",
	"[Reminder]",
	"<system-reminder",
)

#: 无会话归属的行归进这一桶（分会话表里的 session_id 值）。
UNATTRIBUTED_SID = "(none)"
UNATTRIBUTED_LABEL = "未归类（账本没有会话归属）"

#: 表D 里 A3 快照行的前缀。
A3_ROW_PREFIX = "deploy_project_mode_"

#: 快照验收行的落点：与 ``scripts.memory_stack_eval.QUALITY_JSON`` 同一处文件，
#: 等式由 tests/test_usage_live_report.py 钉住（生成器挪位置必须同时改这里）。
QUALITY_JSON = (
	Path(__file__).resolve().parents[1] / "memory" / "simulator" / "out" / "quality_validation.json"
)


class LedgerUnreadable(RuntimeError):
	"""账本**存在却读不出**（权限 / IO 故障）。

	与「没有账本」（``missing_store``）、「有文件但一行有效记录都没有」
	（``empty_store``）是三件事：前两者是正面答案（界面说「本机还没有用量记录」），
	只有这一种是故障，由路由翻成 500。
	"""


# ── 单值收口：读不出的一律 None，绝不悄悄落成 0 ─────────────────────────────


def _has_number(value: Any) -> bool:
	return (
		isinstance(value, (int, float))
		and not isinstance(value, bool)
		and float(value) == float(value)
	)


def _int(value: Any) -> int:
	"""计数器取值：只认真数值。缺键 / bool / 字符串 / NaN 落 0，但调用方另有一列
	``rows_without_counters`` 记分母，不把「没写」和「写了 0」混成同一件事。"""
	return int(float(value)) if _has_number(value) else 0


def _text(value: Any) -> str:
	"""压成可安全上屏的文本：丢 C0/C1 控制符，解码残骸 U+FFFD 换成可见的 ``?``（保留中文）。

	与 ``server/routers/control.py::_a3_text`` 同一套规则（对账见测试）。控制符直接丢——
	它们不占位也不改变语义；U+FFFD 换成 ``?`` 而不是删掉：删掉会把 ``a\\ufffdb`` 与 ``ab``
	两个不同的会话键压成同一个字符串，那是静默改写身份。
	"""
	s = value if isinstance(value, str) else ("" if value is None else str(value))
	if len(s) > _MAX_LABEL_CHARS:
		s = s[:_MAX_LABEL_CHARS] + "…"
	cleaned = "".join(
		"?" if c == "\ufffd" else c
		for c in s
		if not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F)
	)
	return cleaned.strip()


# ── 金额：未知 ≠ 免费（与生成器 _cost_accumulate / _cost_fields 同式）────────


def _empty_bucket() -> dict[str, Any]:
	return {
		"requests": 0,
		"prompt_tokens": 0,
		"cache_hit": 0,
		"cache_miss": 0,
		"output": 0,
		"tokens": 0,
		"cost": 0.0,
		"cost_priced": 0,
		"cost_unknown": 0,
	}


def _cost_accumulate(bucket: dict[str, Any], ev: dict[str, Any]) -> None:
	raw = ev.get("cost_cny")
	value = float(raw) if _has_number(raw) else None
	if value is None:
		# 无可用价格：只计数，不加 0。把缺价按 0 累加等于把「费用未知」读成「免费」。
		bucket["cost_unknown"] = int(bucket["cost_unknown"]) + 1
		return
	bucket["cost"] = float(bucket["cost"]) + value
	bucket["cost_priced"] = int(bucket["cost_priced"]) + 1


def _cost_fields(bucket: dict[str, Any]) -> dict[str, Any]:
	priced = int(bucket["cost_priced"])
	return {
		"cost_cny": None if priced == 0 else round(float(bucket["cost"]), 6),
		"cost_unknown_requests": int(bucket["cost_unknown"]),
	}


def _add_event(bucket: dict[str, Any], ev: dict[str, Any]) -> None:
	bucket["requests"] = int(bucket["requests"]) + 1
	bucket["prompt_tokens"] = int(bucket["prompt_tokens"]) + _int(ev.get("prompt_tokens"))
	bucket["cache_hit"] = int(bucket["cache_hit"]) + _int(ev.get("cache_hit"))
	bucket["cache_miss"] = int(bucket["cache_miss"]) + _int(ev.get("cache_miss"))
	bucket["output"] = int(bucket["output"]) + _int(ev.get("output"))
	bucket["tokens"] = int(bucket["tokens"]) + _int(ev.get("tokens"))
	_cost_accumulate(bucket, ev)


def _view(bucket: dict[str, Any]) -> dict[str, Any]:
	"""聚合桶 → 对外字段。命中率分母为 0 时是 ``null``，不是 0。"""
	hit = int(bucket["cache_hit"])
	miss = int(bucket["cache_miss"])
	total = hit + miss
	return {
		"requests": int(bucket["requests"]),
		"prompt_tokens": int(bucket["prompt_tokens"]),
		"cache_hit": hit,
		"cache_miss": miss,
		"hit_rate": round(hit / total, 4) if total else None,
		"output": int(bucket["output"]),
		"tokens": int(bucket["tokens"]),
		**_cost_fields(bucket),
	}


# ── 记忆化：按文件状态失效，绝不在账本变化后回旧值 ──────────────────────────

_LOCK = threading.RLock()
#: 日聚合缓存：键 = 账本文件状态。同一把键下同时缓存中间态与已下发的日行，
#: 所以"打开页面 = 摘要 + 一天下钻"只会真算一次。
_AGG_CACHE: dict[Any, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
#: C2 计数：键 = c2_events.jsonl 文件状态。
_C2_CACHE: dict[Any, dict[str, int]] = {}
#: 每 session 的用户消息索引：键 = (路径, mtime_ns, size)。
_TURNS_CACHE: dict[Any, tuple[list[float], list[str]]] = {}
#: 验收判据：键 = (quality_validation.json 路径, mtime_ns, size)。
_ACCEPTED_CACHE: dict[Any, dict[str, bool]] = {}
_CACHE_MAX = 4


def reset_caches_for_tests() -> None:
	"""只给测试用：换隔离目录后必须能丢掉上一个现场。"""
	with _LOCK:
		_AGG_CACHE.clear()
		_C2_CACHE.clear()
		_TURNS_CACHE.clear()
		_ACCEPTED_CACHE.clear()


def _stat_key(path: Path) -> tuple[str, int, int] | None:
	"""文件状态键；不存在回 ``None``（缺文件是一种正面事实，不是故障）。"""
	try:
		st = path.stat()
	except FileNotFoundError:
		return None
	except OSError as exc:  # 权限 / IO 故障：不能谎报成"没有这个文件"
		raise LedgerUnreadable(f"{path}: {exc}") from exc
	return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def _bounded(cache: dict[Any, Any]) -> None:
	while len(cache) > _CACHE_MAX:
		cache.pop(next(iter(cache)))


def _events_and_store() -> tuple[list[dict[str, Any]], dict[str, Any]]:
	"""一次扫描同时拿到事件与存储事实（``usage.ledger`` 自己按文件状态缓存解析）。"""
	snapshot = _ledger._read_snapshot()
	if snapshot.store == "unreadable_store":
		raise LedgerUnreadable(f"usage ledger unreadable: {_ledger.events_path()}")
	return snapshot.events, snapshot.status()


def _c2_counts() -> dict[str, int]:
	"""每天的 C2（压缩）触发次数。文件不在 = 没有任何 C2，不是故障。"""
	path = _ledger.c2_events_path()
	key = _stat_key(path)
	if key is None:
		return {}
	cached = _C2_CACHE.get(key)
	if cached is not None:
		return cached
	try:
		rows = _ledger.read_c2_events()
	except OSError as exc:
		raise LedgerUnreadable(f"c2 ledger unreadable: {path}") from exc
	out: dict[str, int] = {}
	for ev in rows:
		day = str(ev.get("day") or "")
		if day:
			out[day] = out.get(day, 0) + 1
	with _LOCK:
		_C2_CACHE[key] = out
		_bounded(_C2_CACHE)
	return out


def _accepted_flags() -> dict[str, bool]:
	"""表D 里 A3 快照行的验收判据 ``{day: accepted}``。

	只为「这一天有没有被快照并验收」服务，读的是 10 MB 的 ``quality_validation.json``
	——按文件状态缓存，快照不跑就一次都不重读。文件不在 / 解析不了 ⇒ 空表（界面
	显示「未快照」这一档），不当成故障。
	"""
	key = _stat_key(QUALITY_JSON)
	if key is None:
		return {}
	cached = _ACCEPTED_CACHE.get(key)
	if cached is not None:
		return cached
	flags: dict[str, bool] = {}
	try:
		data = json.loads(QUALITY_JSON.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		data = None
	if isinstance(data, dict):
		rows = data.get("rows")
		if isinstance(rows, dict):
			for case_id, row in rows.items():
				name = str(case_id or "")
				if not name.startswith(A3_ROW_PREFIX) or not isinstance(row, dict):
					continue
				day = _text(name[len(A3_ROW_PREFIX):])
				if _DAY_RE.match(day):
					flags[day] = bool(row.get("accepted"))
	with _LOCK:
		_ACCEPTED_CACHE[key] = flags
		_bounded(_ACCEPTED_CACHE)
	return flags


# ── 轮次边界：只读账本里出现过的会话文件 ────────────────────────────────────


def _is_injected(text: Any) -> bool:
	t = text.strip() if isinstance(text, str) else ""
	if not t:
		return True
	return any(t.startswith(p) for p in _INJECTED_PREFIXES)


def _user_turns(sid: str) -> tuple[list[float], list[str]]:
	"""一个会话的真实用户消息 ``(ts 升序, 标题)``。

	按 (路径, mtime_ns, size) 缓存 ⇒ 会话在跑时下一次请求只重读那一个文件。
	生成器那版要全盘扫 1,991 个文件 / 243 MB，用在"打开页面就要出数"的路径上不可接受；
	这里只碰账本点过名的会话（本机实测 280 个 / 104 MB 冷读 0.99 s，热读毫秒级）。
	"""
	from session.persistence import transcript_path

	path = transcript_path(sid)
	key = _stat_key(path)
	if key is None:
		return [], []
	cached = _TURNS_CACHE.get(key)
	if cached is not None:
		return cached
	ts: list[float] = []
	labels: list[str] = []
	try:
		with path.open("r", encoding="utf-8", errors="replace") as f:
			for line in f:
				# 先做便宜的形状筛：绝大多数行是 assistant / tool。
				if '"role"' not in line or '"user"' not in line:
					continue
				try:
					rec = json.loads(line)
				except ValueError:
					continue
				if not isinstance(rec, dict) or rec.get("role") != "user":
					continue
				content = rec.get("content")
				if not isinstance(content, str) or _is_injected(content):
					continue
				t = rec.get("ts")
				if not _has_number(t):
					continue
				ts.append(float(t))
				labels.append(content)
	except OSError as exc:
		raise LedgerUnreadable(f"session transcript unreadable: {path}") from exc
	with _LOCK:
		_TURNS_CACHE[key] = (ts, labels)
		_bounded(_TURNS_CACHE)
	return ts, labels


def _turn_of(turns: tuple[list[float], list[str]], ts: float) -> tuple[str, str]:
	"""把一笔事件归到它之前最近的一条用户消息（与生成器 ``_turn_label_for`` 同式）。"""
	ts_arr, lbl_arr = turns
	if not ts_arr:
		return "(auto)", "未归类（会话里没有真实用户消息）"
	i = bisect.bisect_right(ts_arr, ts) - 1
	if i < 0:
		return "(auto)", "未归类（早于该会话第一条用户消息）"
	raw = (lbl_arr[i] or "").strip().replace("|", "/").replace("\n", " ")
	if len(raw) > 40:
		raw = raw[:40] + "…"
	return f"t{i}", _text(raw or f"消息{i}")


# ── 聚合 ──────────────────────────────────────────────────────────────────


def _ts_sort_key(ts: float | None, sid: str) -> tuple[int, float, str]:
	"""轮次排序键：时间戳读不出的排在最前（它们不该冒充"这一天最早"）。"""
	return (0 if ts is None else 1, float(ts) if ts is not None else 0.0, sid)


def _hour_of(value: Any) -> int:
	"""小时桶与 ``day`` 字段同时区（北京时间）：一天之内不该出现两种口径。

	生成器用的是渲染机本地小时；本机与北京同偏移，两边逐格相等（对账见测试）。
	"""
	if not _has_number(value):
		return -1
	try:
		return datetime.fromtimestamp(float(value), tz=BJ).hour
	except (ValueError, OSError, OverflowError):
		return -1


def _aggregate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
	"""账本事件 → 按日升序的聚合中间态（含分模型 / 分会话 / 分轮次）。"""
	turn_map: dict[str, tuple[list[float], list[str]]] = {}
	days: dict[str, dict[str, Any]] = {}
	for ev in events:
		if not isinstance(ev, dict):
			continue
		day = _text(ev.get("day"))
		if not _DAY_RE.match(day):
			continue
		d = days.get(day)
		if d is None:
			d = days[day] = {
				"day": day,
				"bucket": _empty_bucket(),
				"models": {},
				"sessions": {},
				"turns": {},
				"unattributed": 0,
				"rows_without_counters": 0,
			}
		_add_event(d["bucket"], ev)
		if not any(_has_number(ev.get(k)) for k in ("cache_hit", "cache_miss", "output")):
			d["rows_without_counters"] += 1

		provider = _text(ev.get("provider") or "unknown").lower() or "unknown"
		model = _text(ev.get("model") or "unknown") or "unknown"
		_add_event(d["models"].setdefault((provider, model), _empty_bucket()), ev)

		raw_sid = _text(ev.get("session_id"))
		sid = raw_sid if raw_sid and _SID_RE.match(raw_sid) else ""
		_add_event(
			d["sessions"].setdefault(sid or UNATTRIBUTED_SID, _empty_bucket()), ev
		)
		if not sid:
			d["unattributed"] += 1

		ts = float(ev["ts"]) if _has_number(ev.get("ts")) else None
		if sid:
			turns = turn_map.get(sid)
			if turns is None:
				turns = turn_map[sid] = _user_turns(sid)
			turn_id, label = _turn_of(turns, ts if ts is not None else 0.0)
		else:
			turn_id, label = "(unattributed)", UNATTRIBUTED_LABEL
		tkey = (sid or UNATTRIBUTED_SID, turn_id)
		tb = d["turns"].get(tkey)
		if tb is None:
			tb = d["turns"][tkey] = {
				"session_id": sid or UNATTRIBUTED_SID,
				"label": label,
				"model": "",
				"first_ts": ts,
				"last_ts": ts,
				"bucket": _empty_bucket(),
				"events": [],
			}
		_add_event(tb["bucket"], ev)
		tb["model"] = _text(ev.get("model")) or tb["model"]
		# 时间戳读不出的行不参与 min/max：把 None 顶成 0 会把这一轮"搬到 1970 年"，
		# 小时直方图就多出一根假柱，而 hour_unknown 反而永远是 0。
		if ts is not None:
			tb["first_ts"] = ts if tb["first_ts"] is None else min(tb["first_ts"], ts)
			tb["last_ts"] = ts if tb["last_ts"] is None else max(tb["last_ts"], ts)
		tb["events"].append(ev)
	return [days[k] for k in sorted(days)]


def _aggregated() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
	"""(日中间态, 日行, 事件, 存储事实)。中间态与日行同键缓存，一次算完给两个端点用。"""
	events, store = _events_and_store()
	key = _stat_key(_ledger.events_path())
	cached = _AGG_CACHE.get(key)
	if cached is None:
		with _LOCK:
			cached = _AGG_CACHE.get(key)
		if cached is None:
			agg = _aggregate(events)
			c2, accepted = _c2_counts(), _accepted_flags()
			cached = (agg, [_day_row(a, c2=c2, accepted=accepted) for a in agg])
			with _LOCK:
				_AGG_CACHE[key] = cached
				_bounded(_AGG_CACHE)
	return cached[0], cached[1], events, store


def _hour_counts(rows: list[dict[str, Any]]) -> tuple[list[int], int]:
	"""轮次 → 24 桶（按每轮首笔时间）。分不了桶的计入 ``hour_unknown``，不静默丢。"""
	counts = [0] * 24
	unknown = 0
	for t in rows:
		ts = t.get("first_ts")
		h = _hour_of(ts)
		if h < 0:
			unknown += 1
		else:
			counts[h] += 1
	return counts, unknown


def _model_rows(models: dict[Any, dict[str, Any]]) -> list[dict[str, Any]]:
	out = []
	for (provider, model), bucket in sorted(
		models.items(), key=lambda kv: (-int(kv[1]["requests"]), kv[0][0], kv[0][1])
	):
		out.append({"provider": provider, "model": model, **_view(bucket)})
	return out


def _session_rows(sessions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
	return [
		{"session_id": sid, **_view(bucket)}
		for sid, bucket in sorted(
			sessions.items(), key=lambda kv: (-int(kv[1]["requests"]), kv[0])
		)
	]


def _event_row(ev: dict[str, Any]) -> dict[str, Any]:
	return {
		"ts": round(float(ev["ts"]), 3) if _has_number(ev.get("ts")) else None,
		"provider": _text(ev.get("provider") or "unknown").lower(),
		"model": _text(ev.get("model") or "unknown"),
		"prompt_tokens": _int(ev.get("prompt_tokens")),
		"cache_hit": _int(ev.get("cache_hit")),
		"cache_miss": _int(ev.get("cache_miss")),
		"output": _int(ev.get("output")),
		"tokens": _int(ev.get("tokens")),
		"cost_cny": round(float(ev["cost_cny"]), 8) if _has_number(ev.get("cost_cny")) else None,
		"cost_source": _text(ev.get("cost_source")) or None,
		"kind": _text(ev.get("kind")) or None,
		"attempt": _int(ev.get("attempt")) or None,
		"request_id": _text(ev.get("request_id")) or None,
	}


def _turn_rows(
	turns: list[dict[str, Any]],
	*,
	with_events: bool = False,
	event_budget: int | None = None,
) -> list[dict[str, Any]]:
	"""轮次行（升序）。``event_budget`` 只在 ``with_events`` 时生效：从**最新**的轮次
	往前分配每枪原文的额度，拿不到额度的轮次照样出现在列表里（合计也在），只是原文
	行为空、``events_truncated`` 报出被省掉的条数——截断只削最旧的下钻，不削合计。
	"""
	out = []
	for t in sorted(turns, key=lambda r: _ts_sort_key(r["first_ts"], r["session_id"])):
		first = t["first_ts"]
		last = t["last_ts"]
		row = {
			"session_id": t["session_id"],
			"label": t["label"],
			"model": t["model"],
			"first_ts": round(float(first), 3) if first is not None else None,
			"last_ts": round(float(last), 3) if last is not None else None,
			**_view(t["bucket"]),
			# 摘要面不带 events 原文：它是体积主体（报告 10 MB 里 99% 是它）。
			"event_count": len(t["events"]),
			"_events": t["events"],
		}
		out.append(row)
	if not with_events:
		for row in out:
			row.pop("_events")
		return out
	budget = 0 if event_budget is None else max(0, int(event_budget))
	unlimited = event_budget is None
	for row in reversed(out):
		raw = row.pop("_events")
		take = len(raw) if unlimited else min(len(raw), budget)
		row["events"] = [_event_row(e) for e in raw[:take]]
		row["events_truncated"] = len(raw) - take
		budget -= take
	return out


def _day_row(agg: dict[str, Any], *, c2: dict[str, int], accepted: dict[str, bool]) -> dict[str, Any]:
	day = agg["day"]
	turns = list(agg["turns"].values())
	hours, hour_unknown = _hour_counts(
		[{"first_ts": t["first_ts"]} for t in turns]
	)
	return {
		"day": day,
		# 三态：true=快照且已验收 / false=快照但未验收 / null=这一天从没进过快照。
		"accepted": accepted.get(day),
		"snapshot": day in accepted,
		**_view(agg["bucket"]),
		"c2_count": int(c2.get(day, 0)),
		"sessions": sum(1 for k in agg["sessions"] if k != UNATTRIBUTED_SID),
		"unattributed_sessions": 1 if UNATTRIBUTED_SID in agg["sessions"] else 0,
		"unattributed_requests": int(agg["unattributed"]),
		"turns": len(turns),
		"hour_counts": hours,
		"hour_unknown": hour_unknown,
		"rows_without_counters": int(agg["rows_without_counters"]),
		"by_model": _model_rows(agg["models"]),
	}


def _source_facts(events: list[dict[str, Any]], store: dict[str, Any]) -> dict[str, Any]:
	path = _ledger.events_path()
	key = _stat_key(path)
	size: int | None = None
	if key is not None:
		try:
			size = path.stat().st_size
		except OSError:
			size = None
	return {
		"kind": "live_ledger",
		"path": str(path),
		"dir": str(_ledger.usage_dir()),
		"rows": len(events),
		"store": store.get("store"),
		"store_raw_lines": store.get("store_raw_lines"),
		"store_unparsable_lines": store.get("store_unparsable_lines"),
		"mtime": round(key[1] / 1e9, 3) if key else None,
		"bytes": size,
	}


def report_summary(*, max_days: int = 366) -> dict[str, Any]:
	"""全区间日摘要：用量页首屏、日列表、历史表、Token 活动热力图只吃这一份。"""
	_, rows, events, store = _aggregated()
	span = max(1, min(3660, int(max_days)))
	rows = rows[-span:] if span < len(rows) else rows
	return {
		"ok": True,
		"live": True,
		"generated_at": datetime.now(tz=BJ).isoformat(timespec="seconds"),
		"source": _source_facts(events, store),
		"day_count": len(rows),
		"days": rows,
	}


def report_day(day: str) -> dict[str, Any]:
	"""某一天的下钻：日摘要 + 分会话 + 分轮次（每轮带每枪事件行）。"""
	if not _DAY_RE.match(day or ""):
		raise ValueError(f"invalid day: {day!r}")
	agg, rows, events, store = _aggregated()
	target = next((a for a in agg if a["day"] == day), None)
	summary = next((r for r in rows if r["day"] == day), None)
	if target is None or summary is None:
		# 账本可读、这一天没有行：这是正面答案（missing=true），不是故障。
		return {
			"ok": True,
			"live": True,
			"generated_at": datetime.now(tz=BJ).isoformat(timespec="seconds"),
			"source": _source_facts(events, store),
			"day": day,
			"missing": True,
			"summary": None,
			"sessions": [],
			"turns": [],
			"events_truncated": 0,
		}
	turns = _turn_rows(
		list(target["turns"].values()), with_events=True, event_budget=_MAX_DETAIL_EVENT_ROWS
	)
	return {
		"ok": True,
		"live": True,
		"generated_at": datetime.now(tz=BJ).isoformat(timespec="seconds"),
		"source": _source_facts(events, store),
		"day": day,
		"missing": False,
		"summary": summary,
		"sessions": _session_rows(target["sessions"]),
		"turns": turns,
		# 单日每枪行的总量：>0 表示下钻列表被截过（日合计与分模型/分会话不受影响）。
		"events_truncated": sum(int(t["events_truncated"]) for t in turns),
	}
