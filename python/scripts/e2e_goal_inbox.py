"""E2E：goal 自动续跑链 + mid-turn inbox 排水（真实 uvicorn 后端 + 真 HTTP）。

背景（2026-09-05 事故）：goal 合成轮走 httpx ASGITransport 自调用，其内联执行 +
全量缓冲让整个 turn 跑在 driver 预约 task 里 → ①chat.py 让位自取消合成轮
②settlement _schedule 见 pending 未 done 而 skip（链条每轮停摆）③admit 在
turn 结束后与 mark_candidate CAS 竞速。修复后 submit_synthetic 为分离式 ASGI
调用（响应头即返回 + http.disconnect）。本脚本在**生产形态**（真 uvicorn 子进程、
真网络 HTTP、不经任何 ASGITransport）下端到端验证两条主链：

1. goal 链：人类消息（自动建 goal）→ arm → 合成轮「继续」×3（共享唤醒预算 3）
   → 每轮真实跑完并 admit（rounds 1→4）→ 预算耗尽自然停。断言链条**连续推进**
   （旧 bug 表现为 round 1 永不执行 / 停在 round 1 之后）。
2. inbox 链：长回合进行中投递第二条消息（queue_if_busy）→ 202 排队 → 回合
   settle 后自动排水合成投递 → mock 上游看到第二条消息作为独立轮次。

用法：
    .venv/Scripts/python.exe scripts/e2e_goal_inbox.py
退出码 0 = 全部通过；1 = 存在失败（stdout 有逐步 [PASS]/[FAIL]）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
PY_DIR = REPO / "python"
sys.path.insert(0, str(REPO))

from scripts.smoke_p0p1.mock_llm import MockLLMServer, _render  # noqa: E402

PASS = "\x1b[32m[PASS]\x1b[0m"
FAIL = "\x1b[31m[FAIL]\x1b[0m"
_results: list[tuple[bool, str]] = []


def check(cond: bool, label: str, detail: str = "") -> bool:
	_results.append((bool(cond), label))
	print(f"{PASS if cond else FAIL} {label}" + (f" — {detail}" if detail else ""), flush=True)
	return bool(cond)


class Dispatcher:
	"""脚本化 mock 上游：按「最后一条 user 消息」决定回复；记录主链请求。"""

	def __init__(self) -> None:
		self.lock = threading.Lock()
		# 每条记录：{"last_user": str, "tools": bool, "t": float}
		self.requests: list[dict] = []

	@staticmethod
	def _last_user(body: dict) -> str:
		for m in reversed(body.get("messages") or []):
			if m.get("role") == "user":
				c = m.get("content")
				return c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
		return ""

	def dispatch(self, body: dict) -> list[str]:
		has_tools = bool(body.get("tools"))
		last_user = self._last_user(body)
		with self.lock:
			self.requests.append(
				{"last_user": last_user, "tools": has_tools, "t": time.time()}
			)
		if not has_tools:
			# 旁路（标题增强等）：不进主脚本，最小 content。
			return _render({"content": "（skipped）"})
		text = "默认回复"
		if "开始目标任务" in last_user:
			text = "目标已设定，开始执行。"
		elif last_user.strip().startswith("继续"):
			# 拉长合成轮时长，为「合成轮运行中投递」竞态场景留窗口。
			time.sleep(3.0)
			text = "继续推进完成。"
		elif "补充指令" in last_user:
			text = "收到补充指令并处理。"
		elif "长任务" in last_user:
			# 拉长首回合，给 inbox 排队留窗口。
			time.sleep(2.5)
			text = "长任务完成。"
		return _render({"content": text})

	def main_requests(self) -> list[dict]:
		with self.lock:
			return [r for r in self.requests if r["tools"]]


def _free_port() -> int:
	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
		s.bind(("127.0.0.1", 0))
		return int(s.getsockname()[1])


def _wait_health(client: httpx.Client, url: str, timeout_s: float) -> bool:
	deadline = time.time() + timeout_s
	while time.time() < deadline:
		try:
			if client.get(url, timeout=2.0).status_code == 200:
				return True
		except Exception:  # noqa: BLE001
			time.sleep(0.3)
	return False


def _wait(fn, timeout_s: float, interval: float = 0.5):
	deadline = time.time() + timeout_s
	last = None
	while time.time() < deadline:
		last = fn()
		if last:
			return last
		time.sleep(interval)
	return last


def main() -> int:
	try:
		sys.stdout.reconfigure(encoding="utf-8")
	except Exception:  # noqa: BLE001
		pass

	tmp_root = Path(tempfile.mkdtemp(prefix="xeyo-e2e-goal-inbox-"))
	ws = tmp_root / "ws"
	ws.mkdir(parents=True, exist_ok=True)

	# --- 模拟 LLM（mock LLM） -------------------------------------------------------
	disp = Dispatcher()
	mock = MockLLMServer(disp.dispatch)
	mock.start()
	global _MOCK_BASE
	_MOCK_BASE = mock.base_url

	# --- 真实后端（子进程，生产形态）------------------------------------
	port = _free_port()
	env = dict(os.environ)
	env.update(
		{
			"XEYO_HTTP_PORT": str(port),
			"XEYO_HTTP_HOST": "127.0.0.1",
			"XEYO_ALLOW_LOCAL_MODEL": "1",
			"XEYO_GOAL_AUTO_CREATE": "1",
			"XEYO_SESSIONS_DIR": str(tmp_root / "sessions"),
			"XEYO_USAGE_DIR": str(tmp_root / "usage"),
			"XEYO_SPILL_DIR": str(tmp_root / "spill"),
			"XEYO_UI_CWD": str(ws),
			"XEYO_HOME": str(tmp_root / "home"),
			"XEYO_TOOL_AGING": "0",
			"PYTHONIOENCODING": "utf-8",
		}
	)
	env["XEYO_HOME"] = str(tmp_root / "home")
	os.makedirs(env["XEYO_HOME"], exist_ok=True)
	log_path = tmp_root / "backend.log"
	log_fh = open(log_path, "w", encoding="utf-8", errors="replace")
	proc = subprocess.Popen(
		[sys.executable, "-m", "server"],
		cwd=str(PY_DIR),
		env=env,
		stdout=log_fh,
		stderr=subprocess.STDOUT,
	)
	base = f"http://127.0.0.1:{port}"
	ok_boot = False
	try:
		with httpx.Client() as c:
			ok_boot = _wait_health(c, f"{base}/health", 60)
		if not ok_boot:
			raise RuntimeError("backend /health not ready in 60s")
		print(f"{PASS} 后端启动（uvicorn :{port}）", flush=True)

		_run_goal_chain(base, ws, disp)
		_run_inbox_chain(base, ws, disp)
		_run_race_chain(base, ws, disp)
	except Exception as exc:  # noqa: BLE001
		import traceback

		check(False, "e2e 运行异常", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")
	finally:
		proc.terminate()
		try:
			proc.wait(timeout=10)
		except Exception:  # noqa: BLE001
			proc.kill()
		mock.stop()
		log_fh.close()
		try:
			log_text = log_path.read_text(encoding="utf-8", errors="replace")
			tail = "\n".join(log_text.splitlines()[-40:])
			print("\n----- backend.log tail -----\n" + tail, flush=True)
		except Exception:  # noqa: BLE001
			pass

	failed = [label for ok, label in _results if not ok]
	print("\n===== E2E 结果 =====", flush=True)
	print(f"通过 {len(_results) - len(failed)}/{len(_results)}")
	if failed:
		for label in failed:
			print(f"  FAIL: {label}")
		return 1
	print("ALL GREEN")
	return 0


def _headers() -> dict[str, str]:
	return {"Authorization": "Bearer local"}


def _chat_body(sid: str, text: str, ws: Path, **extra) -> dict:
	return {
		"model": "mock-model",
		"messages": [{"role": "user", "content": text}],
		"session_id": sid,
		"stream": True,
		"provider": "local",
		"base_url": _MOCK_BASE,
		"workspace": str(ws),
		**extra,
	}


_MOCK_BASE = ""


def _run_goal_chain(base: str, ws: Path, disp: Dispatcher) -> None:
	sid = "e2e-goal-rounds"
	with httpx.Client(timeout=120.0) as client:
		# ① 人类消息：整流排空 = turn 1 完整跑完（含 goal 自动创建）。
		r = client.post(
			f"{base}/v1/chat/completions",
			json=_chat_body(sid, "开始目标任务", ws),
			headers=_headers(),
		)
		if not check(r.status_code == 200, "① 人类回合 HTTP 200", f"got {r.status_code}"):
			return
		_ = r.text  # 排空 SSE 至 [DONE]

		# ② goal 已自动创建并绑定。
		goal = _wait(
			lambda: client.get(f"{base}/v1/sessions/{sid}/goal").json() or None,
			10,
		)
		if not check(
			bool(goal and goal.get("goal_id")), "② goal 自动创建并绑定", json.dumps(goal or {}, ensure_ascii=False)[:200]
		):
			return
		check(goal.get("status") == "active", "③ goal 初始 active", f"status={goal.get('status')}")

		# ③ arm → 合成轮自动推进（唤醒预算 3 → rounds 1→4）。
		arm = client.post(
			f"{base}/v1/sessions/{sid}/goal/round-driver",
			json={"action": "arm"},
		)
		if not check(arm.status_code == 200, "④ arm 成功", f"got {arm.status_code}"):
			return

		def _rounds():
			g = client.get(f"{base}/v1/sessions/{sid}/goal").json()
			return int(g.get("rounds") or 0)

		final_rounds = _wait(lambda: (_rounds() if _rounds() >= 4 else None), 90)
		check(
			final_rounds == 4,
			"⑤ 合成轮连续推进到 cap（rounds 1→4，无停摆）",
			f"rounds={final_rounds}",
		)
		cont = sum(
			1
			for r_ in disp.main_requests()
			if r_["last_user"].strip().startswith("继续")
		)
		check(
			cont == 3,
			"⑥ mock 上游收到 3 个「继续」合成轮（分离式提交真实跑通）",
			f"continuations={cont}",
		)
		snap = client.get(f"{base}/v1/sessions/{sid}/goal").json()
		check(
			snap.get("status") == "active" and not snap.get("pending_complete"),
			"⑦ 预算耗尽自然停，goal 保持 active 无候选",
			f"status={snap.get('status')} pending={snap.get('pending_complete')}",
		)
		# ⑧ driver armed；第 4 次预约会在 consume_wake 落空后自行收尾（≤2s 防抖+余量），
		# 轮询等待悬挂预约清空。
		def _drv_settled():
			d = client.get(f"{base}/v1/sessions/{sid}/goal").json().get("driver") or {}
			return d if (d.get("pending") is False and d.get("activation") == "armed") else None

		drv = _wait(_drv_settled, 15)
		check(
			bool(drv),
			"⑧ driver armed 且无悬挂预约（预算耗尽后预约自然收尾）",
			json.dumps(drv or {}, ensure_ascii=False),
		)


def _cont_count(disp: Dispatcher) -> int:
	return sum(
		1
		for r in disp.main_requests()
		if r["last_user"].strip().startswith("继续")
	)


def _marker_count(disp: Dispatcher, marker: str) -> int:
	return sum(1 for r in disp.main_requests() if marker in r["last_user"])


def _run_race_chain(base: str, ws: Path, disp: Dispatcher) -> None:
	"""竞态场景：goal 合成轮 × 人类消息 / inbox 排队的碰撞窗口。

	- 竞态 A：arm 后 2s 防抖窗口内人类消息到达 → yield_to_human 作废预约，
	  人类消息直接执行；settle 后 goal 轮恰好恢复一次（不丢、不双跑）。
	- 竞态 B：合成轮**运行中**投递消息 → 202 排队 → 轮 settle 后 inbox 排水，
	  随后 goal 链继续推进（无死锁、无重复投递）。
	"""
	sid = "e2e-race"
	cont0 = _cont_count(disp)
	supp_c0 = _marker_count(disp, "补充指令C")
	with httpx.Client(timeout=180.0) as client:
		# ① 初始人类回合 + goal。
		r = client.post(
			f"{base}/v1/chat/completions",
			json=_chat_body(sid, "开始目标任务", ws),
			headers=_headers(),
		)
		if not check(r.status_code == 200, "① 初始回合 HTTP 200", f"got {r.status_code}"):
			return
		_ = r.text

		def _rounds() -> int:
			try:
				resp = client.get(f"{base}/v1/sessions/{sid}/goal")
				if resp.status_code != 200:
					return 0
				return int(resp.json().get("rounds") or 0)
			except Exception:  # noqa: BLE001 — 轮询瞬时抖动（连接复位等）不中断
				return 0

		def _pending_false():
			d = client.get(f"{base}/v1/sessions/{sid}/goal").json().get("driver") or {}
			return d if d.get("pending") is False else None

		# ---- 竞态 A：arm 后立即人类消息（防抖窗口内让位）----
		client.post(f"{base}/v1/sessions/{sid}/goal/round-driver", json={"action": "arm"})
		rb = client.post(
			f"{base}/v1/chat/completions",
			json=_chat_body(sid, "补充指令B：让位验证", ws, queue_if_busy=True),
			headers=_headers(),
		)
		check(
			rb.status_code == 200,
			"A① arm 后 2s 防抖窗口内人类消息 → 直接执行（让位预约），非 202",
			f"got {rb.status_code}",
		)
		_ = rb.text  # 排空 B 回合
		r2s = _wait(lambda: _rounds() if _rounds() >= 2 else None, 60)
		if r2s is None:
			g = client.get(f"{base}/v1/sessions/{sid}/goal").json()
			_diag = {
				"driver": g.get("driver"),
				"status": g.get("status"),
				"timeline": [f"{r['t']:.1f}:{r['last_user'][:24]}" for r in disp.main_requests()[-8:]],
			}
		else:
			_diag = {}
		check(
			r2s is not None,
			"A② B settle 后 goal 轮恢复（rounds 1→2）",
			json.dumps(_diag, ensure_ascii=False)[:400],
		)
		client.post(f"{base}/v1/sessions/{sid}/goal/round-driver", json={"action": "disarm"})
		check(_wait(_pending_false, 15) is not None, "A③ disarm 后无悬挂预约")
		_wait(lambda: _cont_count(disp) >= cont0 + 1, 30)
		check(
			_cont_count(disp) == cont0 + 1,
			"A④ 恢复的 goal 轮恰好一个（不丢不双跑）",
			f"delta={_cont_count(disp) - cont0}",
		)
		check(_rounds() == 2, "A⑤ 轮号精确：rounds==2", f"rounds={_rounds()}")

		# ---- 竞态 B：合成轮运行中投递 → 202 → 排水 → 链继续 ----
		supp_c_before = _marker_count(disp, "补充指令C")
		client.post(f"{base}/v1/sessions/{sid}/goal/round-driver", json={"action": "arm"})
		r3s = _wait(lambda: _rounds() if _rounds() >= 3 else None, 60)
		_diag = {}
		if r3s is None:
			g = client.get(f"{base}/v1/sessions/{sid}/goal").json()
			_diag = {
				"driver": g.get("driver"),
				"status": g.get("status"),
				"timeline": [f"{r['t']:.1f}:{r['last_user'][:24]}" for r in disp.main_requests()[-8:]],
			}
		check(
			r3s is not None,
			"B① 重 arm 后合成轮 2 开跑（rounds 2→3）",
			json.dumps(_diag, ensure_ascii=False)[:400],
		)
		if r3s is None:
			return
		# 此刻合成轮 turn 正在跑（mock 3s）→ 窗口内投递 C。
		rc = client.post(
			f"{base}/v1/chat/completions",
			json=_chat_body(sid, "补充指令C：排队验证", ws, queue_if_busy=True),
			headers=_headers(),
		)
		queued = False
		try:
			queued = rc.status_code == 202 and rc.json().get("queued") is True
		except Exception:  # noqa: BLE001
			pass
		check(queued, "B② 合成轮运行中投递 → 202 排队", f"got {rc.status_code}")
		check(
			_wait(lambda: _marker_count(disp, "补充指令C") == supp_c_before + 1, 60) is not None,
			"B③ 轮 settle 后 inbox 自动排水，C 恰好投递一次（不丢不重）",
		)
		check(
			_wait(lambda: _rounds() >= 6, 120) is not None,
			"B④ inbox 投递恢复唤醒预算后 goal 链继续推进（rounds→6，无死锁）",
			f"rounds={_rounds()}",
		)
		client.post(f"{base}/v1/sessions/{sid}/goal/round-driver", json={"action": "disarm"})
		check(_wait(_pending_false, 15) is not None, "B⑤ 收尾 disarm，无悬挂预约")
		snap = client.get(f"{base}/v1/sessions/{sid}/inbox").json()
		check(
			len(snap.get("items") or []) == 0,
			"B⑥ inbox 队列清空",
			json.dumps(snap, ensure_ascii=False)[:120],
		)
		check(_marker_count(disp, "补充指令C") == supp_c0 + 1, "B⑦ C 全程仅投递一次")


def _run_inbox_chain(base: str, ws: Path, disp: Dispatcher) -> None:
	sid = "e2e-inbox"
	with httpx.Client(timeout=120.0) as client:
		# ① 长回合：流保持打开（turn 运行中）。
		n_before = len(disp.main_requests())
		with client.stream(
			"POST",
			f"{base}/v1/chat/completions",
			json=_chat_body(sid, "长任务开始", ws),
			headers=_headers(),
		) as resp:
			if not check(resp.status_code == 200, "① 长回合 HTTP 200", f"got {resp.status_code}"):
				return
			# ② 回合进行中投递第二条 → 应 202 排队（而非 409）。
			r2 = client.post(
				f"{base}/v1/chat/completions",
				json=_chat_body(sid, "补充指令：处理附件", ws, queue_if_busy=True),
				headers=_headers(),
			)
			queued_ok = False
			try:
				body2 = r2.json()
				queued_ok = r2.status_code == 202 and body2.get("queued") is True
			except Exception:  # noqa: BLE001
				body2 = {"raw": r2.text[:200]}
			check(
				queued_ok,
				"② 忙时投递返回 202 排队",
				f"status={r2.status_code} body={json.dumps(body2, ensure_ascii=False)[:160]}",
			)
			snap = client.get(f"{base}/v1/sessions/{sid}/inbox").json()
			check(
				len(snap.get("items") or []) == 1,
				"③ inbox 队列可见 1 条待投递",
				json.dumps(snap, ensure_ascii=False)[:200],
			)
			# ③ 排空长回合至完成（settle 触发 inbox 排水）。
			_ = "".join(resp.iter_text())

		# ④ settle 后自动排水：mock 上游看到「补充指令」作为独立轮次。
		def _delivered():
			reqs = disp.main_requests()
			for i, r_ in enumerate(reqs):
				if i > n_before and "补充指令" in r_["last_user"]:
					return i
			return None

		idx = _wait(_delivered, 45, 0.5)
		check(idx is not None, "④ settle 后 inbox 自动投递（合成轮到达 mock 上游）")
		snap = client.get(f"{base}/v1/sessions/{sid}/inbox").json()
		check(
			len(snap.get("items") or []) == 0,
			"⑤ 投递后队列清空",
			json.dumps(snap, ensure_ascii=False)[:160],
		)


if __name__ == "__main__":
	sys.exit(main())
