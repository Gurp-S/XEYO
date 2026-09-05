from __future__ import annotations

import base64
import io

import pytest

from media_store import materialize_image_url, materialize_media_ref, save_image
from model.deepseek import _normalize_messages_for_openai
from model.openai_compat import image_max_dimension

Image = pytest.importorskip("PIL.Image")


def _png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (12, 34, 56))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_max_dimension_uses_provider_rules(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XEYO_MAX_IMAGE_DIMENSION_DEEPSEEK", raising=False)
    assert image_max_dimension("deepseek", "deepseek-v4-flash-vision-exp") == 8192
    assert image_max_dimension("deepseek", "deepseek-v4-flash-vision-exp", image_count=16) == 4096
    assert image_max_dimension("openai", "gpt-4o") == 6000


def test_save_preserves_original_and_materialize_resizes_only_when_needed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("XEYO_MEDIA_DIR", str(tmp_path / "media"))
    raw = _png(100, 80)
    asset = save_image(raw, filename="small.png")
    assert asset.width == 100
    assert asset.height == 80
    assert asset.bytes == len(raw)

    unchanged = materialize_media_ref(asset.media_ref, provider="deepseek", model="vision")
    assert base64.b64decode(unchanged.split(",", 1)[1]) == raw

    large = save_image(_png(9000, 100), filename="large.png")
    resized_url = materialize_media_ref(large.media_ref, provider="deepseek", model="vision")
    resized = Image.open(io.BytesIO(base64.b64decode(resized_url.split(",", 1)[1])))
    assert max(resized.size) == 8192

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect"},
                {"type": "image_url", "image_url": {"url": large.media_ref}},
            ],
        }
    ]
    wire = _normalize_messages_for_openai(
        messages,
        provider="deepseek",
        model="deepseek-v4-flash-vision-exp",
    )
    assert wire[0]["content"][1]["image_url"]["url"].startswith("data:image/")


def test_data_url_under_limit_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XEYO_MAX_IMAGE_DIMENSION_OPENAI", "6000")
    raw = _png(100, 80)
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    assert materialize_image_url(data_url, provider="openai", model="gpt-4o") == data_url
