"""Result equality includes the existing visual payload, without storing it twice."""
import hashlib
from typing import Any


def observation_payload(content: Any, images: list[str] | None) -> Any:
    if not images:
        return content
    return (content, tuple(hashlib.sha256(str(url).encode("utf-8", "replace")).hexdigest() for url in images))
