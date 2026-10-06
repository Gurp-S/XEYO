"""历史读取进入既有线程池；并发接口在磁盘读取结束前仍可响应。"""
import asyncio
import json
import threading

import httpx
from fastapi import FastAPI

from server.routers import sessions


def test_history_disk_read_does_not_block_other_requests(tmp_path, monkeypatch):
	path = tmp_path / "history.jsonl"
	path.write_text(json.dumps({"role": "user", "content": "hello", "ts": 1}) + "\n", encoding="utf-8")
	entered, release = threading.Event(), threading.Event()
	monkeypatch.setattr(sessions, "transcript_path", lambda sid: path)
	def paths(p):
		entered.set()
		release.wait(timeout=2)
		return [p]
	monkeypatch.setattr(sessions, "transcript_read_paths", paths)
	app = FastAPI()
	app.include_router(sessions.router)
	@app.get("/heartbeat")
	async def heartbeat():
		return {"ok": True}
	async def run():
		transport = httpx.ASGITransport(app=app)
		async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
			history = asyncio.create_task(client.get("/v1/sessions/sess_history_test/messages"))
			try:
				assert await asyncio.to_thread(entered.wait, 1)
				assert not history.done(), "history blocked the event loop until its read finished"
				response = await asyncio.wait_for(client.get("/heartbeat"), timeout=0.5)
				assert response.json() == {"ok": True}
				assert not history.done()
			finally:
				release.set()
			response = await history
			assert response.status_code == 200
			assert response.json()["messages"][0]["text"] == "hello"
	asyncio.run(run())
