"""内存远程任务存储：queued → running → done | error。"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

JobStatus = Literal["queued", "running", "waiting_permission", "stopping", "done", "error"]


@dataclass
class JobRecord:
	job_id: str
	session_id: str
	text: str
	status: JobStatus = "queued"
	final_text: str | None = None
	error: str | None = None
	created_at: float = field(default_factory=time.time)
	updated_at: float = field(default_factory=time.time)
	images: list[str] | None = None
	reply_peer: str | None = None
	reply_ctx: str | None = None

	def to_public(self) -> dict[str, object]:
		out: dict[str, object] = {
			"job_id": self.job_id,
			"session_id": self.session_id,
			"status": self.status,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}
		if self.status == "done":
			out["final_text"] = self.final_text or ""
		if self.status == "error":
			out["error"] = self.error or "unknown error"
		return out


class JobStore:
	"""内存任务表。容量有界（默认 256）：超出时优先淘汰最旧的终态任务，
	仍不足再淘汰最旧任务，防止长期运行下记录（含全文）无界累积。"""

	def __init__(self, *, max_jobs: int = 256) -> None:
		self._lock = threading.Lock()
		self._jobs: dict[str, JobRecord] = {}
		self._max_jobs = max(4, int(max_jobs))

	def create(
		self,
		*,
		session_id: str,
		text: str,
		images: list[str] | None = None,
		reply_peer: str | None = None,
		reply_ctx: str | None = None,
	) -> JobRecord:
		job_id = f"job-{uuid.uuid4().hex[:12]}"
		rec = JobRecord(
			job_id=job_id,
			session_id=session_id,
			text=text,
			images=list(images) if images else None,
			reply_peer=reply_peer,
			reply_ctx=reply_ctx,
		)
		with self._lock:
			self._jobs[job_id] = rec
			self._evict_locked()
		return rec

	def _evict_locked(self) -> None:
		if len(self._jobs) <= self._max_jobs:
			return
		# dict 保插入序：终态任务按创建顺序淘汰最旧的。
		terminal_ids = [
			jid
			for jid, r in self._jobs.items()
			if r.status in ("done", "error")
		]
		while len(self._jobs) > self._max_jobs and terminal_ids:
			self._jobs.pop(terminal_ids.pop(0), None)
		if len(self._jobs) > self._max_jobs:
			# 全部在跑（异常情况）：按创建顺序淘汰最旧。
			for jid in list(self._jobs.keys()):
				if len(self._jobs) <= self._max_jobs:
					break
				self._jobs.pop(jid, None)

	def get(self, job_id: str) -> JobRecord | None:
		with self._lock:
			return self._jobs.get(job_id)

	def mark_running(self, job_id: str) -> None:
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None:
				return
			rec.status = "running"
			rec.updated_at = time.time()

	def mark_done(self, job_id: str, final_text: str) -> None:
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None:
				return
			rec.status = "done"
			rec.final_text = final_text
			rec.error = None
			rec.updated_at = time.time()

	def mark_waiting_permission(self, job_id: str) -> None:
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None:
				return
			rec.status = "waiting_permission"
			rec.updated_at = time.time()

	def mark_stopping(self, job_id: str) -> None:
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None:
				return
			rec.status = "stopping"
			rec.updated_at = time.time()

	def mark_error(self, job_id: str, error: str) -> None:
		with self._lock:
			rec = self._jobs.get(job_id)
			if rec is None:
				return
			rec.status = "error"
			rec.error = error
			rec.updated_at = time.time()

	def recent(self, n: int = 8, *, session_id: str | None = None) -> list[JobRecord]:
		with self._lock:
			items = list(self._jobs.values())
		if session_id is not None:
			items = [r for r in items if r.session_id == session_id]
		items.sort(key=lambda r: r.created_at, reverse=True)
		return items[: max(0, n)]
