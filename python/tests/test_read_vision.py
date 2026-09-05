"""Read vision 开关与图片压缩冒烟。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.abort import AbortController
from model.vision_capability import supports_vision_input
from tools.catalog import apply_read_vision, build_default_registry
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.file_read_tool.vision_media import compress_image_for_llm


def test_supports_vision_heuristics(monkeypatch):
	monkeypatch.delenv("XEYO_READ_VISION", raising=False)
	assert supports_vision_input(model="deepseek-v4-flash-vision-exp") is True
	assert supports_vision_input(model="deepseek-chat") is False
	monkeypatch.setenv("XEYO_READ_VISION", "0")
	assert supports_vision_input(model="deepseek-v4-flash-vision-exp") is False
	monkeypatch.setenv("XEYO_READ_VISION", "1")
	assert supports_vision_input(model="deepseek-chat") is True


def test_apply_read_vision_updates_schema():
	reg = build_default_registry(cwd=".")
	apply_read_vision(reg, enabled=False)
	off = next(s for s in reg.schemas() if s["name"] == "Read")
	assert "vision on" not in off["description"].lower()
	apply_read_vision(reg, enabled=True)
	on = next(s for s in reg.schemas() if s["name"] == "Read")
	assert "vision on" in on["description"].lower() or "image/pdf" in on["description"].lower()


@pytest.mark.asyncio
async def test_read_image_when_vision_on(tmp_path: Path):
	pytest.importorskip("PIL")
	from PIL import Image

	img_path = tmp_path / "dot.png"
	Image.new("RGB", (64, 64), color=(10, 20, 30)).save(img_path)

	tool = FileReadTool(cwd=str(tmp_path))
	tool.set_vision_enabled(True)
	result = await tool.execute(
		{"file_path": str(img_path)},
		AbortController(),
	)
	assert not result.is_error
	assert result.images and result.images[0].startswith("data:image/")


@pytest.mark.asyncio
async def test_read_image_rejected_when_vision_off(tmp_path: Path):
	pytest.importorskip("PIL")
	from PIL import Image

	img_path = tmp_path / "dot.png"
	Image.new("RGB", (8, 8), color=(1, 2, 3)).save(img_path)
	tool = FileReadTool(cwd=str(tmp_path))
	tool.set_vision_enabled(False)
	result = await tool.execute(
		{"file_path": str(img_path)},
		AbortController(),
	)
	assert result.is_error


def test_compress_image_for_llm_shrinks():
	pytest.importorskip("PIL")
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (4000, 3000), color=(200, 100, 50)).save(buf, format="PNG")
	raw = buf.getvalue()
	data_url, meta = compress_image_for_llm(raw, max_dimension=512)
	assert data_url.startswith("data:image/")
	assert meta["width"] <= 512
	assert meta["height"] <= 512
