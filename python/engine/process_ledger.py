"""process_ledger — 旁路(准入制 P3):副作用生命周期台账。

只登记并回收**引擎/会话显式创建**的进程/端口/锁(owner=session_id)。
绝不扫描或触碰台账之外的任何对象;cleanup/probe 可注入(单测、容器、
无 psutil 环境)。当前为旁路形态:独立模块 + 测试自证收益;并入
job_registry/query_loop 的真实接线在并行会话收口后进行。

设计约束:
- 纯执行层:不产生任何注意力文本注入(老板理念:引擎限制静默走执行层)。
- fail-safe:cleanup 只对被登记过的 key 调用;probe 判定已死则静默除名,
  不再调用 cleanup(死进程无需杀)。
- 幂等:register 重复键只保留最新;reap/sweep 可任意重复调用。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Callable

# ---------------------------------------------------------------------------
# 类型与缺省实现
# ---------------------------------------------------------------------------


class Kind(str, Enum):
	PROC = "proc"  # 进程(引擎/工具 spawn,含进程树首 pid)
	PORT = "port"  # 端口占用(登记 owner 由引擎侧获取持有 pid)
	LOCK = "lock"  # 锁文件 / pidfile


@dataclass
class Entry:
	kind: Kind
	key: str  # 唯一键(proc=pid str / port=端口 / lock=路径)
	owner: str  # 归属 session_id(空串=引擎进程级)
	turn_id: str = ""
	pid: int | None = None
	cmdline: str = ""
	note: str = ""
	created: float = field(default_factory=time.monotonic)

	def age(self, now: float | None = None) -> float:
		return (now if now is not None else time.monotonic()) - self.created


@dataclass
class ReapReport:
	considered: int = 0
	dead_purged: int = 0  # probe 已死,静默除名
	cleaned: int = 0  # cleanup 成功(杀/释放)后除名
	clean_failed: int = 0  # cleanup 失败,保留待下次
	dry_run: bool = False

	def __str__(self) -> str:
		tag = " [dry-run]" if self.dry_run else ""
		return (
			f"reap{tag}: considered={self.considered} dead_purged={self.dead_purged} "
			f"cleaned={self.cleaned} clean_failed={self.clean_failed}"
		)


# probe: Entry -> bool(是否仍存活/占用);cleanup: Entry -> bool(是否成功释放)
ProbeFn = Callable[[Entry], bool]
CleanupFn = Callable[[Entry], bool]


def _pid_alive(pid: int) -> bool:
	try:
		os.kill(pid, 0)
		return True
	except ProcessLookupError:
		return False
	except PermissionError:
		return True  # 存在但无权探查:按存活处理,不误杀也不误删
	except OSError:
		return False


def default_probe(entry: Entry) -> bool:
	"""缺省存活判定:有 pid 看 pid;锁文件看路径存在;其余按存活(等显式除名)。"""
	if entry.pid is not None:
		return _pid_alive(entry.pid)
	if entry.kind == Kind.LOCK:
		return os.path.exists(entry.key)
	if entry.kind == Kind.PORT:
		# 端口无 in-proc 判定手段 → 假设仍占用,由显式 unregister 或 cleanup 收口。
		return True
	return True


def _terminate_pid(pid: int) -> bool:
	"""尽力终止单个 pid(含其子进程树,平台相关)。返回是否成功发起。"""
	try:
		if os.name == "nt":
			import subprocess

			r = subprocess.run(
				["taskkill", "/PID", str(pid), "/T", "/F"],
				capture_output=True,
				timeout=10,
			)
			return r.returncode == 0
		# POSIX:优先进程组(引擎 spawn 建议 start_new_session=True)
		try:
			os.killpg(os.getpgid(pid), 15)  # SIGTERM
		except (ProcessLookupError, PermissionError, OSError):
			os.kill(pid, 15)
		return True
	except Exception:  # noqa: BLE001 — cleanup 尽力而为,失败留给下次 sweep
		return False


def default_cleanup(entry: Entry) -> bool:
	"""缺省清理:proc 杀进程树;lock 尝试删文件;port 依赖 pid(视同 proc)。"""
	if entry.pid is not None:
		return _terminate_pid(entry.pid)
	if entry.kind == Kind.LOCK:
		try:
			os.unlink(entry.key)
			return True
		except OSError:
			return False
	return False


# ---------------------------------------------------------------------------
# 台账
# ---------------------------------------------------------------------------


class ProcessLedger:
	"""进程/端口/锁生命周期台账(仅登记自建对象)。"""

	def __init__(
		self,
		*,
		probe: ProbeFn | None = None,
		cleanup: CleanupFn | None = None,
	) -> None:
		self._probe = probe or default_probe
		self._cleanup = cleanup or default_cleanup
		self._entries: dict[tuple[Kind, str], Entry] = {}
		self._lock = RLock()

	def register(
		self,
		kind: Kind,
		key: str,
		owner: str,
		*,
		turn_id: str = "",
		pid: int | None = None,
		cmdline: str = "",
		note: str = "",
	) -> bool:
		"""登记一个副作用对象。返回是否新登记(重复键=更新为最新,返回 False)。"""
		k = (kind, key)
		entry = Entry(
			kind=kind,
			key=key,
			owner=owner,
			turn_id=turn_id,
			pid=pid,
			cmdline=cmdline,
			note=note,
		)
		with self._lock:
			added = k not in self._entries
			self._entries[k] = entry
			return added

	def unregister(self, kind: Kind, key: str) -> bool:
		with self._lock:
			return self._entries.pop((kind, key), None) is not None

	def list(self, *, owner: str | None = None, kind: Kind | None = None) -> list[Entry]:
		with self._lock:
			out = [
				e
				for e in self._entries.values()
				if (owner is None or e.owner == owner)
				and (kind is None or e.kind == kind)
			]
			return sorted(out, key=lambda e: (e.owner, e.kind.value, e.key))

	def _matching(
		self, *, owner: str | None, kind: Kind | None
	) -> list[Entry]:
		with self._lock:
			return [
				e
				for e in self._entries.values()
				if (owner is None or e.owner == owner)
				and (kind is None or e.kind == kind)
			]

	def reap(
		self,
		*,
		owner: str | None = None,
		kind: Kind | None = None,
		dry_run: bool = False,
	) -> ReapReport:
		"""收口:owner 关闭/会话结束/异常路径时统一回收匹配项。

		先 probe:已死 → 静默除名(不调 cleanup);仍存活 → 调 cleanup;
		cleanup 成功 → 除名;失败 → 保留(下次 sweep 再试)。dry_run 只报告不动手。
		"""
		targets = self._matching(owner=owner, kind=kind)
		report = ReapReport(considered=len(targets), dry_run=dry_run)
		with self._lock:
			for e in targets:
				key = (e.kind, e.key)
				if self._entries.get(key) is not e:
					continue  # 已被并发除名
				if not self._probe(e):
					report.dead_purged += 1
					self._entries.pop(key, None)
					continue
				if dry_run:
					continue
				ok = False
				try:
					ok = self._cleanup(e)
				except Exception:  # noqa: BLE001 — cleanup 尽力而为
					ok = False
				if ok:
					report.cleaned += 1
					self._entries.pop(key, None)
				else:
					report.clean_failed += 1
		return report

	def sweep(
		self,
		active_owners: set[str],
		*,
		grace_s: float = 60.0,
		now: float | None = None,
	) -> ReapReport:
		"""孤儿兜底:owner 不在 active 且超过宽限期 → 清理;在 active → 只除名已死者。"""
		now_t = now if now is not None else time.monotonic()
		report = ReapReport()
		with self._lock:
			targets = list(self._entries.values())
		for e in targets:
			key = (e.kind, e.key)
			with self._lock:
				if self._entries.get(key) is not e:
					continue
				if not self._probe(e):
					report.dead_purged += 1
					self._entries.pop(key, None)
					continue
			if e.owner in active_owners:
				continue  # owner 存活中的对象由 reap 负责
			if e.age(now_t) < grace_s:
				continue  # 宽限期内不误伤刚关闭正在收尾的对象
			report.considered += 1
			ok = False
			try:
				ok = self._cleanup(e)
			except Exception:  # noqa: BLE001
				ok = False
			with self._lock:
				if ok:
					report.cleaned += 1
					self._entries.pop(key, None)
				else:
					report.clean_failed += 1
		return report

	def count(self) -> int:
		with self._lock:
			return len(self._entries)

	def snapshot(self) -> list[dict]:
		"""诊断/报告用(JSON 友好)。"""
		return [
			{
				"kind": e.kind.value,
				"key": e.key,
				"owner": e.owner,
				"turn_id": e.turn_id,
				"pid": e.pid,
				"cmdline": e.cmdline,
				"age_s": round(e.age(), 3),
				"note": e.note,
			}
			for e in self.list()
		]


# ---------------------------------------------------------------------------
# 旁路便捷入口(XEYO_PROC_LEDGER 门控;默认关,关时零行为差异)
# ---------------------------------------------------------------------------

_DEFAULT: "ProcessLedger | None" = None


def get_ledger() -> "ProcessLedger":
	"""进程级默认台账(懒建,线程安全由内部 RLock 保证)。"""
	global _DEFAULT
	if _DEFAULT is None:
		_DEFAULT = ProcessLedger()
	return _DEFAULT


def ledger_enabled() -> bool:
	"""旁路开关:``XEYO_PROC_LEDGER`` ∈ {1,true,on,yes} 时登记开启。"""
	v = os.environ.get("XEYO_PROC_LEDGER", "").strip().lower()
	return v in {"1", "true", "on", "yes"}


def _auto_owner() -> str:
	try:
		from engine.workspace_context import get_workspace_context

		ws = get_workspace_context()
		if ws is not None and getattr(ws, "session_id", ""):
			return str(ws.session_id)
	except Exception:  # noqa: BLE001 — owner 推导失败回退引擎级
		pass
	return "engine"


def register_process(
	pid: int,
	*,
	cmdline: str = "",
	owner: str | None = None,
	note: str = "",
) -> bool:
	"""登记一个引擎 spawn 的进程(proc 树首 pid)。门控关闭时静默跳过。"""
	if not ledger_enabled() or not pid:
		return False
	return get_ledger().register(
		Kind.PROC,
		str(pid),
		owner if owner is not None else _auto_owner(),
		pid=int(pid),
		cmdline=str(cmdline or "")[:200],
		note=note,
	)


def unregister_process(pid: int) -> bool:
	"""除名(释放=引擎责任终止)。门控关闭时为对称 no-op。"""
	if not ledger_enabled() or not pid:
		return False
	return get_ledger().unregister(Kind.PROC, str(pid))


def leftovers(*, owner: str | None = None) -> list[Entry]:
	"""报告当前仍存活的台账对象(诊断/收益度量用;不清理)。"""
	ledger = get_ledger()
	out: list[Entry] = []
	for e in ledger.list(owner=owner):
		try:
			if ledger._probe(e):
				out.append(e)
		except Exception:  # noqa: BLE001 — 探活失败不挡报告
			out.append(e)
	return out


# ---------------------------------------------------------------------------
# CLI / 自检
# ---------------------------------------------------------------------------

if __name__ == "__main__":
	import argparse
	import json
	import sys

	ap = argparse.ArgumentParser(description="ProcessLedger 旁路诊断")
	ap.add_argument("--snapshot", action="store_true", help="输出当前台账快照(JSON)")
	ap.add_argument("--reap-owner", metavar="SESSION", help="对指定 owner 执行收口")
	ap.add_argument("--dry-run", action="store_true", help="只报告不清理")
	ap.add_argument("--selfcheck", action="store_true", help="内置假件跑一遍自检")
	args = ap.parse_args()

	ledger = ProcessLedger()

	if args.selfcheck:
		alive = {"p1": True}
		calls: list[str] = []

		def fake_probe(e: Entry) -> bool:
			return alive.get(e.key, True)

		def fake_cleanup(e: Entry) -> bool:
			calls.append(e.key)
			alive[e.key] = False
			return True

		l2 = ProcessLedger(probe=fake_probe, cleanup=fake_cleanup)
		l2.register(Kind.PROC, "p1", "s1", pid=1)
		l2.register(Kind.PROC, "p2", "s2", pid=2)
		l2.register(Kind.LOCK, "f.lock", "s1")
		# p2 一开始就死
		alive["p2"] = False
		r = l2.reap(owner="s1")
		assert r.cleaned == 2, r
		assert r.dead_purged == 0, r
		r2 = l2.sweep({"s2"}, grace_s=0.0)
		assert r2.dead_purged == 1, r2  # p2 已死被除名
		assert l2.count() == 0
		assert sorted(calls) == ["f.lock", "p1"]
		print("selfcheck OK:", r, "|", r2)
		sys.exit(0)

	if args.snapshot:
		json.dump(ledger.snapshot(), sys.stdout, ensure_ascii=False, indent=2)
		sys.exit(0)
	if args.reap_owner:
		rep = ledger.reap(owner=args.reap_owner, dry_run=args.dry_run)
		print(rep)
		sys.exit(0)
	ap.print_help()
