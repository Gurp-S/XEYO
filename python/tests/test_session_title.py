"""T5 会话标题回归：即时标题、sidecar 持久化、LLM 增强、rename 钉死。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.title import (
	DEFAULT_TITLE,
	MAX_TITLE_BYTES,
	enhance_with_model,
	ensure_instant_title,
	instant_title,
	read_title,
	title_sidecar_path,
	write_title,
)


# ---------- instant_title（即时标题）----------


def test_instant_title_strips_markdown_and_folds_whitespace():
	assert instant_title("# **帮我 看* 这段* 代码**") == "帮我 看 这段 代码"
	assert instant_title("第一行标题\n第二行细节") == "第一行标题"
	assert instant_title("- 列表项做标题") == "列表项做标题"
	assert instant_title("`code` 例子") == "code 例子"


def test_instant_title_cjk_byte_safe_truncation():
	long = "汉" * 100
	title = instant_title(long)
	assert len(title.encode("utf-8")) <= MAX_TITLE_BYTES
	assert set(title) == {"汉"}  # 没有半个字符的乱码
	assert len(title) == MAX_TITLE_BYTES // 3


def test_instant_title_fallbacks():
	assert instant_title("") == DEFAULT_TITLE
	assert instant_title("   \n\n  ") == DEFAULT_TITLE
	assert instant_title("###\n```") == DEFAULT_TITLE


# ---------- sidecar（侧挂）----------


def test_sidecar_roundtrip(tmp_path: Path):
	entry = write_title("s-t5", "测试标题", sessions_dir=tmp_path)
	assert entry["title"] == "测试标题"
	back = read_title("s-t5", sessions_dir=tmp_path)
	assert back is not None and back["title"] == "测试标题"
	assert title_sidecar_path("s-t5", sessions_dir=tmp_path).exists()


def test_pinned_cannot_be_overridden_automatically(tmp_path: Path):
	write_title("s-t5p", "用户起的标题", pinned=True, sessions_dir=tmp_path)
	# 自动路径（pinned=False）无效；显式 rename（pinned=True）可改。
	entry = write_title("s-t5p", "自动标题", sessions_dir=tmp_path)
	assert entry["title"] == "用户起的标题"
	entry2 = write_title("s-t5p", "再次改名", pinned=True, sessions_dir=tmp_path)
	assert entry2["title"] == "再次改名"


def test_ensure_instant_title_is_idempotent(tmp_path: Path):
	monkey_free_dir = tmp_path / "sd"
	first = write_title("s-t5i", "你好世界", sessions_dir=monkey_free_dir)
	assert first["title"] == "你好世界"
	assert read_title("s-t5i", sessions_dir=monkey_free_dir)["title"] == "你好世界"


def test_bad_sidecar_treated_as_missing(tmp_path: Path):
	p = title_sidecar_path("s-t5b", sessions_dir=tmp_path)
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text("not json{", encoding="utf-8")
	assert read_title("s-t5b", sessions_dir=tmp_path) is None
	p.write_text(json.dumps({"title": "   "}), encoding="utf-8")
	assert read_title("s-t5b", sessions_dir=tmp_path) is None


# ---------- LLM 增强 ----------


class _FakeClient:
	def __init__(self, text: str) -> None:
		self._text = text
		self.seen_prompt: str | None = None

	async def stream(self, messages, tools, abort):  # noqa: ANN001
		assert tools == []
		self.seen_prompt = str(messages[-1]["content"])
		from model.chunks import ModelChunk

		yield ModelChunk(kind="text_delta", text=self._text)


@pytest.mark.asyncio
async def test_enhance_applies_title_and_audits_before_dispatch(tmp_path: Path):
	from audit.log import AuditLog, default_audit_log, reset_default_audit_log

	log_path = tmp_path / "audit.jsonl"
	reset_default_audit_log()
	import audit.log as audit_mod

	audit_mod._default = AuditLog(log_path)  # type: ignore[attr-defined]
	# enhance_with_model 内部走默认 sessions dir（conftest 已隔离）。
	write_title("s-t5e", "即时标题")
	client = _FakeClient("融合改造讨论")
	result = await enhance_with_model("s-t5e", "原始长问题……", client)
	assert result == "融合改造讨论"
	assert read_title("s-t5e")["enhanced"] is True
	rows = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()]
	kinds = [r["kind"] for r in rows]
	assert kinds.index("title.enhance") < kinds.index("title.enhance.applied")
	assert client.seen_prompt.startswith("为下面的用户首条消息生成")


@pytest.mark.asyncio
async def test_enhance_rejects_empty_and_pinned(tmp_path: Path):
	from audit.log import AuditLog, default_audit_log, reset_default_audit_log

	log_path = tmp_path / "audit.jsonl"
	reset_default_audit_log()
	import audit.log as audit_mod

	audit_mod._default = AuditLog(log_path)  # type: ignore[attr-defined]
	# 空结果 → 拒绝，保留即时标题。
	write_title("s-t5r", "即时标题")
	assert await enhance_with_model("s-t5r", "问题", _FakeClient("")) is None
	assert read_title("s-t5r")["title"] == "即时标题"
	# pinned → 连请求都不发。
	write_title("s-t5rp", "钉死标题", pinned=True)
	quiet = _FakeClient("新标题")
	assert await enhance_with_model("s-t5rp", "问题", quiet) is None
	assert quiet.seen_prompt is None


# ---------- rename 端点 ----------


def test_rename_endpoint_pins_title():
	from fastapi import FastAPI
	from fastapi.testclient import TestClient
	from server.routers.sessions import router

	app = FastAPI()
	app.include_router(router)
	client = TestClient(app)
	resp = client.post(
		"/v1/sessions/unit-t5/rename", json={"title": "我的自定义标题"}
	)
	assert resp.status_code == 200, resp.text
	body = resp.json()
	assert body["title"] == "我的自定义标题" and body["pinned"] is True
	saved = read_title("unit-t5")
	assert saved is not None and saved["pinned"] is True
	resp2 = client.post("/v1/sessions/unit-t5b/rename", json={"title": "  "})
	assert resp2.status_code == 400


if __name__ == "__main__":
	import sys

	raise SystemExit(pytest.main([__file__, "-q"] + sys.argv[1:]))
