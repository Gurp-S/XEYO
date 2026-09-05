"""Screenshot 工具：schema、权限、结果附件。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import tool_result_message
from permissions.gate import can_use_tool
from tools.catalog import build_default_registry
from tools.screenshot_tool import SCREENSHOT_TOOL_NAME, ScreenshotTool


def test_screenshot_registered() -> None:
	reg = build_default_registry(cwd=".")
	assert reg.get(SCREENSHOT_TOOL_NAME) is not None
	names = [s["name"] for s in reg.schemas()]
	assert SCREENSHOT_TOOL_NAME in names
	assert "SendToWeChat" in names
	shot = next(s for s in reg.schemas() if s["name"] == SCREENSHOT_TOOL_NAME)
	assert "capture the display" in shot["description"].lower()
	assert "wechat" in shot["description"].lower()
	assert "remote" in shot["description"].lower()


def test_screenshot_gate_requires_ask() -> None:
	# 二元 API：ASK → DENY；完整路径走 ToolRegistry 挂起。
	assert not can_use_tool("Screenshot", {}, cwd=".").allowed
	from permissions.filesystem import PermissionDecision
	from permissions.policy import evaluate_policy

	r = evaluate_policy("Screenshot", {}, cwd=".")
	assert r.decision == PermissionDecision.ASK


def _patch_capture(
	monkeypatch: pytest.MonkeyPatch, shot: Path, *, preview: Path | None = None
) -> None:
	def _cap(*, monitor: int = 1, preview_max_side: int = 1280) -> Path:
		return shot

	def _preview(path: Path, *, max_bytes: int = 280_000) -> bytes:
		src = preview if preview and preview.is_file() else path
		return src.read_bytes()

	monkeypatch.setattr("channels.filehelper.screenshot.capture_primary", _cap)
	monkeypatch.setattr("channels.filehelper.screenshot.preview_png", _preview)


@pytest.mark.asyncio
async def test_screenshot_tool_attaches_image(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	shot = tmp_path / "shot.png"
	shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
	_patch_capture(monkeypatch, shot)
	monkeypatch.setattr("channels.remote_deliver.wechat_remote_ready", lambda: False)

	tool = ScreenshotTool()
	result = await tool.execute({"view": True}, AbortController())
	assert result.is_error is False
	assert str(shot) in result.content
	assert result.images and result.images[0].startswith("data:image/png;base64,")
	assert "WeChat copy" not in result.content

	msg = tool_result_message(
		"call1",
		"Screenshot",
		result.content,
		images=result.images,
	)
	assert isinstance(msg.content, list)
	types = [b.get("type") for b in msg.content if isinstance(b, dict)]
	assert "tool_result" in types
	assert "image_url" in types


@pytest.mark.asyncio
async def test_screenshot_without_view_returns_path_only(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	shot = tmp_path / "shot.png"
	shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
	_patch_capture(monkeypatch, shot)
	monkeypatch.setattr("channels.remote_deliver.wechat_remote_ready", lambda: False)

	result = await ScreenshotTool().execute({}, AbortController())
	assert result.is_error is False
	assert str(shot) in result.content
	assert result.images is None
	assert "view=true" in result.content


@pytest.mark.asyncio
async def test_screenshot_sends_to_wechat(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	shot = tmp_path / "shot.png"
	preview = tmp_path / "shot.preview.png"
	shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
	preview.write_bytes(b"\x89PNG\r\n\x1a\n" + b"p" * 40)
	sent: list[Path] = []

	async def _send(path: Path, *, as_image: bool | None = None) -> str:
		sent.append(path)
		assert as_image is True
		return f"sent image to WeChat (iLink): {path.name}"

	_patch_capture(monkeypatch, shot, preview=preview)
	monkeypatch.setattr("channels.remote_deliver.wechat_remote_ready", lambda: True)
	monkeypatch.setattr("channels.remote_deliver.send_remote_file", _send)

	result = await ScreenshotTool().execute({}, AbortController())
	assert result.is_error is False
	assert "WeChat copy is sending in the background" in result.content
	assert "sent image to WeChat" not in result.content
	for _ in range(50):
		if sent:
			break
		await asyncio.sleep(0)
	assert sent == [preview]


@pytest.mark.asyncio
async def test_screenshot_does_not_wait_for_wechat_cdn(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	shot = tmp_path / "shot.png"
	shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
	sent: list[Path] = []

	async def _send(path: Path, *, as_image: bool | None = None) -> str:
		await asyncio.sleep(0.35)
		sent.append(path)
		return f"sent image to WeChat (iLink): {path.name}"

	_patch_capture(monkeypatch, shot)
	monkeypatch.setattr("channels.remote_deliver.wechat_remote_ready", lambda: True)
	monkeypatch.setattr("channels.remote_deliver.send_remote_file", _send)

	t0 = time.perf_counter()
	result = await ScreenshotTool().execute({}, AbortController())
	elapsed = time.perf_counter() - t0
	assert result.is_error is False
	assert elapsed < 0.15
	assert sent == []
	assert "WeChat copy is sending in the background" in result.content
	for _ in range(40):
		if sent:
			break
		await asyncio.sleep(0.02)
	assert sent == [shot]


@pytest.mark.asyncio
async def test_send_to_wechat_errors_without_remote(tmp_path: Path) -> None:
	from tools.send_to_wechat_tool import SendToWeChatTool

	f = tmp_path / "note.txt"
	f.write_text("hi", encoding="utf-8")
	tool = SendToWeChatTool(cwd=str(tmp_path))
	result = await tool.execute({"path": str(f)}, AbortController())
	assert result.is_error
	assert "SendToWeChat failed" in result.content
