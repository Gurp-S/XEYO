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


def materialize_references(messages: list[dict], *, provider: str, model: str) -> list[dict]:
    """Resolve stored media at encoding time without changing history rows."""
    count = sum(1 for row in messages
                for block in (row.get("content") if isinstance(row.get("content"), list) else ())
                if isinstance(block, dict) and block.get("type") == "image_url")
    output = []
    for row in messages:
        content = row.get("content")
        if row.get("role") not in {"user", "tool"} or not isinstance(content, list):
            output.append(row)
            continue
        blocks = None
        for index, block in enumerate(content):
            image = block.get("image_url") if isinstance(block, dict) and block.get("type") == "image_url" else None
            url = image.get("url") if isinstance(image, dict) else None
            if not isinstance(url, str) or not url.startswith("xeyo-media://"):
                continue
            if blocks is None:
                blocks = list(content)
            blocks[index] = tool_images([block], provider=provider, model=model, image_count=count)[0]
        output.append({**row, "content": blocks} if blocks is not None else row)
    return output
