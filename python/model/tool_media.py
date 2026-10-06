"""Tool images use a user media row after the complete tool-result batch."""
from typing import Any

from media_store import materialize_image_url


def tool_images(content: Any, *, provider: str, model: str, image_count: int) -> list[dict]:
    images = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "image_url":
            continue
        image_url = block.get("image_url")
        if not isinstance(image_url, dict):
            continue
        url = str(image_url.get("url") or "")
        if url.startswith(("xeyo-media://", "data:image/")):
            url = materialize_image_url(url, provider=provider, model=model, image_count=image_count)
        images.append({**block, "image_url": {**image_url, "url": url}})
    return images


def append_tool_media(out: list[dict], images: list[dict]) -> None:
    if images:
        out.append({"role": "user", "content": list(images)})
        images.clear()
