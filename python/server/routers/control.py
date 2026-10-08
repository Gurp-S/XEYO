"""Control 域路由：打断、权限确认、提问作答、计划批准。"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from engine.plan import default_plan_engine
from permissions.ask_store import default_ask_store
from permissions.store import default_permission_store
from rewind.blob_gc import (
    _flag,
    _int_env,
    read_rewind_gc_config,
    rewind_gc_config_state,
    write_rewind_gc_config,
)
from server.deps import _MAX_USER_CHARS, _pool, api_error
from server.local_gate import require_loopback
from server.routers.extensions import require_workspace_arg
from common.errors import safe_error_detail

router = APIRouter(tags=["control"])

#: 身份键长度上界：与 ``sessions._MAX_ID_CHARS`` 同档（会话 / 请求 / grant id 实测
#: 都是 ``uuid4().hex`` 的 12–32 位），留足余量又挡掉「把整篇文档当 id 发过来」。
_MAX_ID_CHARS = 128


def _require_store_id(raw: Any, *, field: str) -> str:
	"""挂起项句柄（request_id / turn_id / grant_id）的边缘校验。

	复用 ``sessions._require_stable_id``（延迟导入，避开路由之间的导入环），不另立
	判据：空白 / 控制字符 / 超长 / 带路径分隔符一律 422，原样返回合法值。

	为什么这些 in-process 句柄也要校验：存储层自己还会再归一化一次——
	``PermissionGrantStore.revoke`` 对 key 做 ``strip()``，于是
	``" 9b8bde015466"`` 与 ``"9b8bde015466"`` 打到**同一条 grant**，
	撤销动作删掉的是另一个身份的数据。边缘先拒，执行层才有唯一身份。
	"""
	from server.routers.sessions import _require_stable_id

	return _require_stable_id(raw, field=field)


class MemorySwitchBody(BaseModel):
	"""记忆系统开关 POST 体：只收开关更新（值域校验在 memory.memory_switches）。"""

	workspace: str | None = Field(default=None, max_length=1024)
	updates: dict[str, Any] = Field(default_factory=dict)


@router.get("/v1/settings/memory")
def get_memory_switches(
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""记忆系统开关生效值（settings.memory > 默认），供设置面板读取。

	``switches`` 每项带 ``exposed``（是否 GUI 暴露）/ ``ignored``（运行时是否忽略该键）/
	``effective``（运行时真值）——前端按 ``exposed`` 过滤、按 ``effective`` 显示。
	``stale`` = settings.memory 里的已删/未知残留键（只读报告，不写盘；POST 时才清理）。
	"""
	_ = authorization
	require_loopback(request)
	from memory.memory_switches import current, stale_keys
	from server.deps import CWD

	ws = require_workspace_arg(workspace) or (CWD or "")
	try:
		return {"ok": True, "switches": current(ws or None), "stale": stale_keys(ws or None)}
	except Exception as exc:  # noqa: BLE001 — 读不出状态既不以裸 500 逃出，也不谎报成"没配"
		raise api_error(500, safe_error_detail(exc), "memory_settings_unreadable") from exc


@router.post("/v1/settings/memory")
def post_memory_switches(
	body: MemorySwitchBody,
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""应用记忆系统开关：settings.json 原子写 + 实时写 os.environ（运行时立即生效）。

	``save`` 顺带清掉 settings.memory 里的已删/未知残留键（运行时本就不读）；
	``pruned`` 回执被清理的键名，便于审计。
	"""
	_ = authorization
	require_loopback(request)
	from memory.memory_switches import MEMORY_SWITCHES, apply_to_environ, current, prune_stale, save
	from server.deps import CWD

	# 相对 workspace（``..`` / ``a/b``）按**服务端进程 cwd**取根，等于让调用方把
	# memory 段写进任意目录的 .xeyo/settings.json；空白照旧回退已登记 cwd。
	ws = require_workspace_arg(workspace) or require_workspace_arg(body.workspace) or (CWD or "")
	allowed = {k for (k, *_rest) in MEMORY_SWITCHES}
	bad = [k for k in body.updates if k not in allowed]
	if bad:
		# 本路由族的取值回执约定是 200 + ok:false（test_memory_switches 钉住）；
		# 这里只给未知键名截断，避免把调用方任意长的串整段反射回响应体。
		return {"ok": False, "error": f"未知记忆开关: {', '.join(map(str, bad))}"[:200]}
	try:
		# 先清两侧残留键（home + workspace）；无残留则零写入。回执用于审计。
		# save 内部也会再清一次（幂等），此处先做是为了拿到"本次清掉了哪些"的准确回执。
		pruned = prune_stale(ws or None)
		saved = save(body.updates, ws or None)
		applied = apply_to_environ(ws or None)
		return {
			"ok": True,
			"memory": saved,
			"applied_env": applied,
			"pruned": pruned,
			"switches": current(ws or None),
			"stale": [],
		}
	except ValueError as exc:  # 非法取值：200 + ok:false（本路由族钉死的取值回执）
		return {"ok": False, "message": safe_error_detail(exc)}
	except Exception as exc:  # noqa: BLE001 — 写盘 / 环境桥接失败不是"没生效"，是失败
		raise api_error(500, safe_error_detail(exc), "memory_settings_write_failed") from exc


@router.post("/v1/settings/memory/snapshot")
def run_memory_snapshot(request: Request) -> dict[str, Any]:
	"""手动运行一次 A3 日常监控快照（复用 --monitor-daily，按天 upsert 天然去重）。

	与每日计划任务（本地 A3 监控批处理 + schtasks）写同一处证据：docs/12 表D
	的 ``deploy_project_mode_<day>`` 行，同一天重复点只覆盖不新增。
	"""
	require_loopback(request)
	import re
	import subprocess
	import sys
	from pathlib import Path

	py_dir = Path(__file__).resolve().parents[2]
	try:
		proc = subprocess.run(
			[sys.executable, "-m", "scripts.memory_stack_eval", "--monitor-daily"],
			cwd=str(py_dir),
			capture_output=True,
			text=True,
			timeout=120,
		)
	except Exception as exc:  # noqa: BLE001 — 内部异常痕迹不外漏
		return {"ok": False, "error": safe_error_detail(exc)}
	raw = proc.stdout or ""
	out = "\n".join(raw.splitlines()[-6:])
	# 从监控输出解析真实日（ledger 的本地日），避免 UTC 与本地日不一致。
	# auto 会补齐「上次快照日之后 → ledger 最新日」的所有天，故列出全部、day 取最新那天。
	days = re.findall(r"deploy_project_mode_(\S+)", raw)
	return {
		"ok": proc.returncode == 0,
		"day": days[-1] if days else None,
		"days": days,
		"rc": proc.returncode,
		"tail": out,
	}


@router.get("/v1/settings/memory/report")
def memory_report(request: Request) -> dict[str, Any]:
	"""A3 监控报告（``docs/A3-monitor.html``）的落点与元信息，供设置页「打开报告」按钮用。

	路径取生成器里的同一常量（``scripts.memory_stack_eval.A3_HTML``），不在此复制路径字面量，
	避免报告换位置后两端漂移；``url`` 是可直接交给系统浏览器的 ``file://`` 链接。
	报告不存在时返回 ``ok=false/exists=false``（按钮据此禁用），不报错。
	"""
	require_loopback(request)
	import re
	from pathlib import Path

	from scripts.memory_stack_eval import A3_HTML

	path = Path(A3_HTML)
	try:
		url = path.as_uri()
	except ValueError:  # 非绝对路径等异常形态
		url = ""
	info: dict[str, Any] = {"ok": False, "exists": False, "path": str(path), "url": url}
	if not path.is_file():
		return info
	try:
		text = path.read_text(encoding="utf-8", errors="replace")
		st = path.stat()
	except OSError as exc:  # noqa: BLE001 — 报告**存在**却读不出：不能谎报成"尚未生成"
		raise api_error(500, safe_error_detail(exc), "memory_report_unreadable") from exc
	m = re.search(r'"generated_at":\s*"([^"]+)"', text)
	return {
		**info,
		"ok": True,
		"exists": True,
		"bytes": st.st_size,
		"mtime": round(st.st_mtime, 3),
		"generated_at": m.group(1) if m else None,
		# 日期集合：payload 里每天出现两次（day 行 + total.detail），set 去重即天数清单。
		"days": sorted(set(re.findall(r'"day": "(\d{4}-\d{2}-\d{2})"', text))),
	}


@router.get("/v1/settings/memory/report/view")
def memory_report_view(request: Request) -> Any:
	"""把 A3 报告当网页交给浏览器（系统默认浏览器 / 工作区预览面板）。

	为什么要多这一跳：桌面壳的 ``shell:allow-open`` scope 只放行 ``mailto:`` / ``tel:`` /
	``http(s)://`` —— ``file://`` 被插件**默认拒绝**（见其 scope 正则），故按钮直接开
	``file://`` 会报 Scoped command argument failed regex validation。这里用 loopback http
	出一个只读入口：既不用放宽壳的 scope，也不用把 ``file:`` 引进预览面板（面板同样明令禁
	``file:``）。只服务生成器写的那一个路径，不接受调用方传入路径。
	"""
	require_loopback(request)
	from pathlib import Path

	from fastapi.responses import FileResponse

	from scripts.memory_stack_eval import A3_HTML
	from server.deps import api_error

	path = Path(A3_HTML)
	if not path.is_file():
		raise api_error(404, "A3 report not generated yet", "not_found")
	return FileResponse(
		path,
		media_type="text/html; charset=utf-8",
		headers={"Cache-Control": "no-store"},
	)


# ── A3 报告的结构化数据面（把内嵌 JSON 交给 GUI 原生渲染，不再贴网页）──────────────
#
# 报告 HTML 有 10 MB，其中 99.2 % 是生成器内嵌的 ``window.__A3__`` payload
# （``scripts.memory_stack_eval.render_a3_html``）。payload 每天形如
# ``{day, total, by_model, by_session, by_turn, accepted}``，而 ``total`` 就是**整个
# detail 字典本身**——于是 ``by_turn`` 被原地嵌了两份（实测 18 天里约 5.1 MB 是重复的
# ``total.by_turn``），且每轮的 ``events`` 又是 ``by_turn`` 的体积主体。这两个重复面
# 就是"不能整份发给前端"的原因，也是下面裁剪函数的唯一依据。

#: 每天下发哪些标量：只取 detail 里的数字字段。``ledger_dir`` 是服务端绝对路径，
#: 界面用不上（文件路径另由 ``source.path`` 给），故不带。
#: ``cost_unknown_requests`` 与 ``cost_cny`` 成对下发：前者是该日无价目行数，
#: >0 时界面把金额标成「部分未知」（没有它，前端无从区分「就是 0」与「缺价」）。
_A3_SUMMARY_FIELDS = (
	"requests",
	"prompt_tokens",
	"cache_hit",
	"cache_miss",
	"hit_rate",
	"c2_count",
	"output",
	"cost_cny",
	"cost_unknown_requests",
)

#: ``?day=`` 的取值形态：报告按本地日 upsert，日就是 ``YYYY-MM-DD``。固定正则而不是
#: 宽松字符串——这条路由与 ``report/view`` 同族，靠**结构**保证调用方参数碰不到路径。
#: 校验只留这一道（不给 pydantic 加 ``max_length``）：加了就会有一种失败回
#: ``{"detail":[...]}``、另一种回 ``{"error":{...}}``，前端按 type 分文案时得先猜状态码。
_A3_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 轮次标签是用户消息原文，界面只渲染一行；截断后补省略号，避免把长文本整段反射回前端。
_A3_LABEL_CHARS = 160


def _a3_text(value: Any) -> str:
	"""压成可安全上屏的文本：去掉 C0/C1 控制符，解码残骸 U+FFFD 换成可见的 ``?``（保留中文）。

	控制符直接丢——它们本就不占位、不改变语义；U+FFFD 换成 ``?`` 而不是删掉：删掉会把
	``a\ufffdb`` 与 ``ab`` 两个不同的 session_id 压成同一个字符串，那是静默改写身份。
	"""
	s = value if isinstance(value, str) else ("" if value is None else str(value))
	if len(s) > _A3_LABEL_CHARS:
		s = s[:_A3_LABEL_CHARS] + "…"
	cleaned = "".join(
		"?" if c == "\ufffd" else c
		for c in s
		if not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F)
	)
	return cleaned.strip()


def _a3_key_fp(value: Any) -> str:
	"""Key 指纹的安全形态。

	``usage.ledger.key_fingerprint`` 的正常输出是 ``…`` + 末 4 位字母数字，但历史账本行
	里有解码残骸（实测 ``~/.xeyo/usage/events.jsonl`` 存在 ``'\\ufffd\\ufffd6962'`` 这种
	形态）——原样上屏就是乱码。这里统一压成 ``…<尾 4 位>``；残骸多到没有可信尾时给
	``hex:`` 形态（指纹本身已是截断摘要，十六进制化不额外泄凭据）。
	"""
	s = _a3_text(value)
	tail = "".join(c for c in s if c.isascii() and c.isalnum())[-4:]
	if len(s) and not tail:
		return "hex:" + s.encode("utf-8", "replace").hex()[:16]
	return f"…{tail}" if tail else ""


def _a3_clean(value: Any, *, field: str = "") -> Any:
	"""递归清洗要下发的子集：字符串安全化、非有限数变 None，其余原样（只读，不改盘）。"""
	if isinstance(value, dict):
		return {str(k): _a3_clean(v, field=str(k)) for k, v in value.items()}
	if isinstance(value, list):
		return [_a3_clean(v, field=field) for v in value]
	if isinstance(value, bool) or value is None:
		return value
	if isinstance(value, (int, float)):
		return value if math.isfinite(float(value)) else None
	if field == "key_fp":
		return _a3_key_fp(value)
	return _a3_text(value)


def _a3_hour_counts(by_turn: list[Any]) -> tuple[list[int], int]:
	"""按**服务端本地时区**给每轮的 ``first_ts`` 分 24 桶（与报告原图的口径一致：
	生成器的 ``hourOf(ts)`` 用的也是渲染机本地小时）。分不了桶的计入 ``unknown``，
	不静默丢。"""
	counts = [0] * 24
	unknown = 0
	for row in by_turn:
		ts = row.get("first_ts") if isinstance(row, dict) else None
		try:
			counts[datetime.fromtimestamp(float(ts)).hour] += 1  # type: ignore[arg-type]
		except (TypeError, ValueError, OSError, OverflowError):
			unknown += 1
	return counts, unknown


def _a3_day_summary(day_row: dict[str, Any]) -> dict[str, Any]:
	"""一天：只留标量 + 分模型 + 计数 + 小时直方图。``total`` 里重复的明细整体不带。"""
	total = day_row.get("total") if isinstance(day_row.get("total"), dict) else {}
	by_model = total.get("by_model") if isinstance(total.get("by_model"), list) else []
	by_session = total.get("by_session") if isinstance(total.get("by_session"), list) else []
	by_turn = total.get("by_turn") if isinstance(total.get("by_turn"), list) else []
	hours, hour_unknown = _a3_hour_counts(by_turn)
	summary: dict[str, Any] = {
		"day": _a3_text(total.get("day") or day_row.get("day")),
		"accepted": bool(day_row.get("accepted")),
	}
	for name in _A3_SUMMARY_FIELDS:
		summary[name] = _a3_clean(total.get(name))
	# 报告 payload 的 detail 里**没有** sessions 字段（生成器只写了 ledger_dir/by_*），
	# 旧网页的"会话数"KPI 因此恒为 0。这里给真值：by_session 的行数。
	summary["sessions"] = len(by_session)
	summary["turns"] = len(by_turn)
	summary["hour_counts"] = hours
	summary["hour_unknown"] = hour_unknown
	summary["by_model"] = [_a3_clean(m) for m in by_model]
	return summary


def _a3_turn_row(turn: dict[str, Any]) -> dict[str, Any]:
	"""一轮（一条用户消息）的明细行：``events`` 换成条数，其余字段照原语义下发。"""
	row = {k: _a3_clean(v, field=str(k)) for k, v in turn.items() if k != "events"}
	events = turn.get("events")
	row["event_count"] = len(events) if isinstance(events, list) else 0
	return row


def _a3_read_payload() -> tuple[dict[str, Any], dict[str, Any]]:
	"""读报告 HTML 并解出内嵌 payload；所有失败都回**结构化错误**，不裸 500、不谎报"尚未生成"。

	与 ``memory_report`` / ``memory_report_view`` 共用同一个 ``A3_HTML`` 常量与同一套
	判据：不存在 404、存在却读不出 500。解析不缓存——10 MB 全文实测读 + 解 0.2 s，
	而缓存会引入"报告已刷新但界面还拿旧的"这类难查状态。
	"""
	from pathlib import Path

	from scripts.memory_stack_eval import A3_HTML

	path = Path(A3_HTML)
	if not path.is_file():
		raise api_error(404, "A3 report not generated yet", "not_found")
	try:
		text = path.read_text(encoding="utf-8", errors="replace")
		st = path.stat()
	except OSError as exc:  # noqa: BLE001 — 报告**存在**却读不出：不能谎报成"尚未生成"
		raise api_error(500, safe_error_detail(exc), "memory_report_unreadable") from exc
	source = {"path": str(path), "bytes": st.st_size, "mtime": round(st.st_mtime, 3)}
	m = re.search(r"window\.__A3__\s*=\s*(.*?)</script>", text, re.S)
	if not m:
		raise api_error(
			500,
			"embedded A3 payload (window.__A3__) not found in report html",
			"memory_report_unparsable",
		)
	blob = m.group(1).replace("<\\/", "</")
	try:
		payload = json.loads(blob)
	except (ValueError, TypeError) as exc:  # noqa: BLE001 — 生成器改了内嵌形态也归这一档
		raise api_error(
			500,
			f"embedded A3 payload is not valid json: {safe_error_detail(exc)}",
			"memory_report_unparsable",
		) from exc
	if not isinstance(payload, dict) or not isinstance(payload.get("days"), list):
		raise api_error(
			500, "embedded A3 payload has unexpected shape", "memory_report_unparsable"
		)
	return payload, source


@router.get("/v1/settings/memory/report/data")
def memory_report_data(
	request: Request,
	day: str | None = Query(default=None),
) -> Any:
	"""A3 报告的结构化数据：不带 ``day`` 回全区间摘要，带 ``day=YYYY-MM-DD`` 回那天的会话/轮次明细。

	存在的意义就是替代 iframe：报告 HTML 99.2 % 体积是内嵌 JSON，但没有一条路由把它交给
	前端，于是界面只能贴网页。这里只下发界面要渲染的那部分——按审计结论砍掉两处冗余：
	``total``（原地重嵌了整份 detail，含第二份 ``by_turn``）与每轮的 ``events`` 原始数组。

	``?day=`` 让下钻不必再取整份 payload：18 天摘要 ≈ 15 KB，单日明细（含 2 MB 级
	``by_turn`` 裁出来的行）≈ 70 KB。失败一律走 HTTP 错误码（404 未生成 / 500 读不出
	或解析不了），detail 是 ``{message, type}``，前端按 type 出中文产品文案。
	"""
	require_loopback(request)

	if day is not None and not _A3_DAY_RE.match(day):
		raise api_error(404, f"no such day in report: {day}", "not_found")

	payload, source = _a3_read_payload()
	generated_at = payload.get("generated_at")
	rows = [r for r in payload["days"] if isinstance(r, dict)]

	if day is None:
		return JSONResponse(
			{
				"ok": True,
				"generated_at": _a3_text(generated_at),
				"source": source,
				"day_count": len(rows),
				"days": [_a3_day_summary(r) for r in rows],
			},
			headers={"Cache-Control": "no-store"},
		)

	target = next((r for r in rows if _a3_text(r.get("day")) == day), None)
	if target is None:
		raise api_error(404, f"no such day in report: {day}", "not_found")
	total = target.get("total") if isinstance(target.get("total"), dict) else {}
	by_session = total.get("by_session") if isinstance(total.get("by_session"), list) else []
	by_turn = total.get("by_turn") if isinstance(total.get("by_turn"), list) else []
	return JSONResponse(
		{
			"ok": True,
			"generated_at": _a3_text(generated_at),
			"source": source,
			"day": day,
			"summary": _a3_day_summary(target),
			"sessions": [_a3_clean(s) for s in by_session],
			"turns": [_a3_turn_row(t) for t in by_turn if isinstance(t, dict)],
		},
		headers={"Cache-Control": "no-store"},
	)


class InterruptRequest(BaseModel):
	#: 会话 id 只做长度上界：``SessionPool.interrupt`` / ``TurnRunner.mark_stopping``
	#: 都是**精确键**的进程内字典（无 strip / 无文件名归一化），``"victim "`` 打不到
	#: ``victim``，落不存在的 id 也只是幂等 no-op——所以这里不套固定点（那会破坏
	#: 已钉死的幂等 stop 契约），只挡超长串。
	session_id: str = Field(max_length=_MAX_ID_CHARS)


@router.post("/v1/interrupt")
def interrupt(body: InterruptRequest, request: Request) -> dict[str, Any]:
	require_loopback(request)
	from server.inbox_registry import InboxPersistenceError, get_inbox_registry

	pause_error = False
	try:
		get_inbox_registry().pause(body.session_id)
	except InboxPersistenceError:
		pause_error = True
	try:
		from engine.turn_runner import get_turn_runner

		get_turn_runner().mark_stopping(body.session_id, reason="user_stop")
	except Exception:
		pass
	ok = _pool.interrupt(body.session_id)
	if pause_error:
		raise api_error(503, "inbox pause could not be persisted", "inbox_unavailable")
	return {"ok": ok}


class PermissionResolveRequest(BaseModel):
	request_id: str = Field(max_length=_MAX_ID_CHARS)
	approved: bool
	actor: str = Field(default="desktop", max_length=_MAX_ID_CHARS)
	#: allow / deny / remind；缺省时由 approved 推导（兼容旧客户端）。
	#: 认不得的非空值一律 422——静默按 approved 兜底等于替用户改写裁决。
	outcome: str | None = Field(default=None, max_length=32)
	#: T10：approved 且 remember=True 时记 always-allow grant（"don't ask again"）。
	remember: bool = False


def _resolve_miss_reason(store: Any, request_id: str) -> str:
	"""resolve() 为什么没生效：句柄不存在，还是已经被别的表面裁决过。

	权限与提问两个存储同形状（内存 dict + ``item.resolved``），这里只读不写。
	GUI 要的就是这一层区分：``already_resolved`` 不是失败（远程/微信已经答过，
	重试永远修不好，界面却写"提交失败请重试"）；``no_such_request`` 通常是服务重启
	清掉了内存挂起项。取不到观测就退回空串，让界面用通用措辞，不猜原因。
	"""
	try:
		item = store.get(request_id)
	except Exception:  # noqa: BLE001 — 观测旁路不得影响裁决本身
		return ""
	if item is None:
		return "no_such_request"
	if getattr(item, "resolved", False):
		return "already_resolved"
	return ""


@router.post("/v1/permission/resolve")
def permission_resolve(body: PermissionResolveRequest, request: Request) -> dict[str, Any]:
	"""前端/微信确认或拒绝一个挂起的权限请求。"""
	require_loopback(request)
	request_id = _require_store_id(body.request_id, field="request_id")
	choice = (body.outcome or "").strip().lower() or None
	if choice not in (None, "allow", "deny", "remind"):
		# 裁决语义有歧义绝不猜：此前拼错的 outcome 会静默回落到 ``approved``，
		# 实测 ``{"approved": true, "outcome": "deny-all"}`` 把一次拒绝意图
		# 变成了**放行**，还连带落了永久的 always-allow grant。
		raise api_error(
			422, "outcome must be allow / deny / remind", "invalid_request"
		)
	store = default_permission_store()
	miss = _resolve_miss_reason(store, request_id)
	ok = store.resolve(request_id, body.approved, actor=body.actor, choice=choice)
	grant_id = ""
	if ok and body.remember and body.approved and choice in (None, "allow"):
		# T10：按 (tool, 规则指纹) 记 always-allow；Bash=命令前缀，其他=matched_rule。
		item = store.get(request_id)
		if item is not None:
			from permissions.store import default_grant_store, grant_fingerprint

			fp = grant_fingerprint(
				item.tool_name,
				item.tool_input,
				matched_rule=item.matched_rule,
				command_summary=item.command_summary,
				mcp_target=str(getattr(item, "mcp_target", "") or ""),
			)
			grant = default_grant_store().add(
				# 网关调用：以解析后的目标注册名落库（原生/网关路径同一身份）。
				tool_name=str(getattr(item, "mcp_target", "") or "") or item.tool_name,
				fingerprint=fp,
				scope=store.workspace_of(request_id) or "",
				actor=body.actor,
			)
			grant_id = grant.grant_id if grant else ""
	return {
		"ok": ok,
		"request_id": request_id,
		"grant_id": grant_id,
		**({} if ok else {"reason": miss}),
	}


@router.get("/v1/permissions/grants")
def list_permission_grants(request: Request, scope: str | None = None) -> dict[str, Any]:
	"""T10：列出 always-allow 授权（可按工作区过滤），供 GUI 管理。"""
	require_loopback(request)
	from permissions.store import default_grant_store

	# 相对 scope 会被 ``PermissionGrantStore.list`` 按服务端进程 cwd 取根，实测
	# ``?scope=ws`` 让一个确有授权的工作区报成 ``grants: []``（"什么都没授权"的假绿）。
	# 语义：**不发 scope = 列全部**（GUI 就这么调）；发了但是空白 = 意图不明的过滤条件，
	# 既不静默放宽成"列全部"（那会把别的工作区的授权算到这个过滤上），也不静默清空。
	if scope is not None and not str(scope).strip():
		raise api_error(422, "scope is blank", "invalid_request")
	want_scope = require_workspace_arg(scope, field="scope")
	grants = [
		{
			"grant_id": g.grant_id,
			"tool_name": g.tool_name,
			"fingerprint": g.fingerprint,
			"scope": g.scope,
			"created_at": g.created_at,
			"expires_at": g.expires_at,
			"actor": g.actor,
		}
		for g in default_grant_store().list(scope=want_scope or None)
	]
	return {"ok": True, "grants": grants}


@router.delete("/v1/permissions/grants/{grant_id}")
def revoke_permission_grant(grant_id: str, request: Request) -> dict[str, Any]:
	"""T10：撤销一个 always-allow 授权（审计 permission.grant.revoked）。"""
	require_loopback(request)
	from permissions.store import default_grant_store

	# grant_id 是 store handle，且 revoke() 自己 strip() —— 未校验时
	# ``DELETE /v1/permissions/grants/%20<id>`` 实测返回 200 ok:true 并**删掉了
	# <id> 那条真实授权**。固定点校验后这类写法 422、零删除。
	gid = _require_store_id(grant_id, field="grant_id")
	ok = default_grant_store().revoke(gid)
	# ok:false 的唯一来源是"台账里没有这条"（loopback 与 id 形态都在前面 4xx 掉了）。
	# 不写 reason 时客户端只能念"撤销失败，请重试"——而重试永远修不好一条已消失的授权。
	return {"ok": ok, "grant_id": gid, **({} if ok else {"reason": "grant_not_found"})}


class AskUserResolveRequest(BaseModel):
	request_id: str = Field(max_length=_MAX_ID_CHARS)
	#: 作答文本会成为工具结果进模型注意力，上界与 chat 的用户消息同档。
	answer: str = Field(max_length=_MAX_USER_CHARS)
	actor: str = Field(default="desktop", max_length=_MAX_ID_CHARS)


@router.post("/v1/ask/resolve")
def ask_user_resolve(body: AskUserResolveRequest, request: Request) -> dict[str, Any]:
	"""前端/微信提交对一个挂起提问（AskUserQuestion）的作答。"""
	require_loopback(request)
	request_id = _require_store_id(body.request_id, field="request_id")
	ask_store = default_ask_store()
	miss = _resolve_miss_reason(ask_store, request_id)
	ok = ask_store.resolve_answer(request_id, body.answer, actor=body.actor)
	return {"ok": ok, "request_id": request_id, **({} if ok else {"reason": miss})}


class PlanApproveRequest(BaseModel):
	approved: bool
	actor: str = Field(default="desktop", max_length=_MAX_ID_CHARS)


class RewindGcSettings(BaseModel):
	keep_recent: int | None = None
	max_bytes: int | None = None


@router.get("/v1/settings/rewind-gc")
def get_rewind_gc_settings(request: Request) -> dict[str, Any]:
	"""回溯 blob GC 设置（设计 §36 §9.1）：读取持久化配置 + 环境默认。"""
	require_loopback(request)
	cfg = read_rewind_gc_config()
	return {
		**cfg,
		# 文件坏了与"没设置过"是两件事：read 侧两者返回同一份空默认，控制面必须
		# 把区别带出来，否则调用方会以为自己写过的值还在生效。
		"config_state": rewind_gc_config_state(),
		"defaults": {
			"enabled": _flag("XEYO_BLOB_GC_ENABLED", default=False),
			"dry_run": _flag("XEYO_BLOB_GC_DRY_RUN", default=True),
			"max_bytes": _int_env("XEYO_BLOB_GC_MAX_BYTES", None),
		},
	}


@router.put("/v1/settings/rewind-gc")
def put_rewind_gc_settings(body: RewindGcSettings, request: Request) -> dict[str, Any]:
	"""写入回溯 blob GC 设置；非法取值 422，写盘失败结构化 500。

	此前非法值走 ``200 + ok:false``：GUI 的 ``setRewindGcSettings`` 只看
	``res.ok``，于是"keep_recent=0 被拒"在前端渲染成**保存成功**（假绿）；
	而 ``write_rewind_gc_config`` 的 ``mkdir`` 失败（父路径被占位 / 只读盘）
	以 ``FileExistsError`` 裸逃出路由。
	"""
	require_loopback(request)
	if body.keep_recent is not None and body.keep_recent < 1:
		raise api_error(422, "keep_recent must be >= 1", "invalid_request")
	if body.max_bytes is not None and body.max_bytes < 0:
		raise api_error(422, "max_bytes must be >= 0", "invalid_request")
	try:
		saved = write_rewind_gc_config(
			keep_recent=body.keep_recent,
			max_bytes=body.max_bytes,
		)
	except OSError as exc:
		raise api_error(500, safe_error_detail(exc), "rewind_gc_write_failed") from exc
	return {"ok": True, **saved}


@router.post("/v1/plan/{turn_id}/approve")
def plan_approve(turn_id: str, body: PlanApproveRequest, request: Request) -> dict[str, Any]:
	"""批准或拒绝一个 Plan 模式下已经产出的实现计划。"""
	require_loopback(request)
	tid = _require_store_id(turn_id, field="turn_id")
	ok = default_plan_engine().resolve(
		tid, body.approved, actor=body.actor
	)
	return {"ok": ok, "request_id": tid, "approved": body.approved}
