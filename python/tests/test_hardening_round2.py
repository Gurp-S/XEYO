"""第二轮加固测试：媒体缓存 / JobStore 淘汰 / git 单进程 / journal 缓存 / 计价非阻塞。"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


# ---------- B6: 图片物化 LRU 缓存 ----------


def _tiny_png_bytes() -> bytes:
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (4, 4), color=(200, 10, 10)).save(buf, format="PNG")
	return buf.getvalue()


def test_media_ref_materialization_cached(tmp_path, monkeypatch):
	import media_store
	from media_store import materialize_media_ref, save_image

	monkeypatch.setenv("XEYO_MEDIA_DIR", str(tmp_path))
	media_store._data_url_cache.clear()

	asset = save_image(_tiny_png_bytes(), filename="t.png")

	calls = {"n": 0}
	orig_inspect = media_store._inspect_image

	def counting(raw):
		calls["n"] += 1
		return orig_inspect(raw)

	monkeypatch.setattr(media_store, "_inspect_image", counting)
	url1 = materialize_media_ref(asset.media_ref)
	url2 = materialize_media_ref(asset.media_ref)
	assert url1 == url2 and url1.startswith("data:image/png;base64,")
	assert calls["n"] == 1, "第二次物化应命中缓存，不再做 Pillow 校验"


def test_media_data_url_cached(tmp_path, monkeypatch):
	import media_store
	from media_store import materialize_image_url

	monkeypatch.setenv("XEYO_MEDIA_DIR", str(tmp_path))
	media_store._data_url_cache.clear()
	raw = _tiny_png_bytes()
	import base64

	data_url = f"data:image/png;base64,{base64.b64encode(raw).decode()}"

	calls = {"n": 0}
	orig = media_store._inspect_image

	def counting(b):
		calls["n"] += 1
		return orig(b)

	monkeypatch.setattr(media_store, "_inspect_image", counting)
	assert materialize_image_url(data_url) == data_url
	assert materialize_image_url(data_url) == data_url
	assert calls["n"] == 1, "同一 data URL 第二轮不应再 decode+verify"


# ---------- C10: JobStore 有界淘汰 ----------


def test_jobstore_prunes_oldest_terminal_jobs():
	from channels.jobs import JobStore

	store = JobStore(max_jobs=8)
	ids = []
	for i in range(12):
		rec = store.create(session_id="s", text=f"t{i}")
		ids.append(rec.job_id)
		store.mark_done(rec.job_id, f"r{i}")
	jobs = store.recent(100)
	assert len(jobs) <= 8
	# 最旧的已终态任务被淘汰，最新的保留
	assert ids[-1] in {j.job_id for j in jobs}
	assert ids[0] not in {j.job_id for j in jobs}


def test_jobstore_prefers_evicting_terminal_over_running():
	from channels.jobs import JobStore

	store = JobStore(max_jobs=4)
	running_ids = []
	for i in range(3):
		rec = store.create(session_id="s", text=f"run{i}")
		store.mark_running(rec.job_id)
		running_ids.append(rec.job_id)
	old_done = store.create(session_id="s", text="old")
	store.mark_done(old_done.job_id, "ok")
	extra = store.create(session_id="s", text="extra")
	store.mark_done(extra.job_id, "ok")
	remaining = {j.job_id for j in store.recent(100)}
	assert old_done.job_id not in remaining, "最旧终态任务应先被淘汰"
	assert extra.job_id in remaining
	assert set(running_ids) <= remaining, "运行中的任务不应被淘汰"


# ---------- C11: runner 会话锁字典有界 ----------


@pytest.mark.asyncio
async def test_runner_session_locks_bounded():
	from channels.jobs import JobStore
	from channels.runner import FinalOnlyRunner

	class _P:
		def is_busy(self, sid):
			return False

	runner = FinalOnlyRunner(_P(), JobStore())
	for i in range(600):
		await runner._lock_for(f"s{i}")
	assert len(runner._session_locks) <= 512


# ---------- B7: git status 单进程 ----------


def test_git_status_single_invocation(tmp_path, monkeypatch):
	from server import workspace_git as wg

	calls: list[list[str]] = []

	def fake_run_git(root, args, timeout=wg._GIT_TIMEOUT_S):
		calls.append(args)
		out = ""
		if args[:2] == ["status"] or "status" in args:
			out = (
				"## main...origin/main\n"
				"M  staged.txt\n"
				" M modified.txt\n"
				"?? untracked.txt\n"
			)
		class R:
			returncode = 0
			stdout = out
			stderr = ""

		return R()

	monkeypatch.setattr(wg, "_run_git", fake_run_git)
	(root := tmp_path / "ws").mkdir()
	(root / ".git").mkdir()
	payload = wg.read_git_status(str(root))

	assert len(calls) == 1, "status 应合并为一次 git 调用"
	assert payload["branch"] == "main"
	assert payload["clean"] is False
	assert [i["path"] for i in payload["staged"]] == ["staged.txt"]
	assert [i["path"] for i in payload["unstaged"]] == ["modified.txt"]
	assert [i["path"] for i in payload["untracked"]] == ["untracked.txt"]


# ---------- A4: rewind journal 读缓存正确性 ----------


def test_journal_transition_with_read_cache(tmp_path):
	from rewind.journal import OperationJournal

	j = OperationJournal("sess-j", sessions_dir=tmp_path, enabled=True)
	t1 = j.start_turn(revision_id=None)
	assert t1 is not None
	updated = j.transition_turn(t1.turn_id, "committed")
	got = j.get_turn(t1.turn_id)
	assert updated is not None and got is not None
	assert got.status == "committed"

	t2 = j.start_turn(revision_id=None)
	assert t2 is not None
	turns = j.list_turns(latest_only=True)
	assert len(turns) == 2
	statuses = {t.turn_id: t.status for t in turns}
	assert statuses[t1.turn_id] == "committed"
	assert statuses[t2.turn_id] == "running"


# ---------- A3: 计价过期后不阻塞调用方 ----------


def test_pricing_refresh_is_nonblocking(monkeypatch):
	import usage.pricing as pricing

	# 强制缓存过期 + 网络挂起：调用方必须立即返回（本地兜底价），不被 urlopen 卡住
	with pricing._pricing_lock:
		pricing._pricing_cache = (time.time() - 10**9, {"models": []})
		pricing._pricing_disk_loaded = True
		pricing._refresh_inflight = False

	class SlowResp:
		def __enter__(self):
			time.sleep(30)
			return self

		def __exit__(self, *a):
			return False

		def read(self):
			return b"{}"

	def slow_urlopen(req, timeout=2.0):
		return SlowResp()

	monkeypatch.setattr(pricing, "urlopen", slow_urlopen)
	t0 = time.perf_counter()
	price = pricing.get_model_pricing("deepseek", "deepseek-v4-flash", timeout=30.0)
	elapsed = time.perf_counter() - t0
	assert price is not None, "应立即回落本地兜底价"
	assert elapsed < 2.0, f"计价刷新不应阻塞调用方（耗时 {elapsed:.2f}s）"


# ---------- B9: ReadFileState LRU ----------


def test_read_file_state_bounded(tmp_path):
	from tools.fileio.read_state import FileStateEntry, ReadFileState

	st = ReadFileState(max_entries=8)
	for i in range(20):
		st.set(f"f{i}", FileStateEntry(content="x" * 100, timestamp=i))
	assert len(st._entries) <= 8
	# 最近写入的存活
	assert st.get("f19") is not None
	# 触碰的存活：先 get 刷新再塞新条目
	st.get("f12")
	st.set("f-new", FileStateEntry(content="", timestamp=0))
	assert st.get("f12") is not None