"""模型是否接受图片输入（供 Read 工具按需开启 vision）。

判定顺序：
1. ``XEYO_READ_VISION=0/1`` 强制关/开
2. 厂商 /models 的 modes/capabilities 含 vision/image
3. 模型 id 启发式（vision / gpt-4o / claude-3…）
"""

from __future__ import annotations

import os
from typing import Any


def supports_vision_input(
	*,
	provider: str = "",
	model: str = "",
	modes: dict[str, Any] | None = None,
) -> bool:
	raw = os.environ.get("XEYO_READ_VISION", "").strip().lower()
	if raw in ("0", "false", "off", "no"):
		return False
	if raw in ("1", "true", "on", "yes"):
		return True

	if isinstance(modes, dict):
		for key in ("vision", "image", "images", "multimodal", "supports_vision"):
			val = modes.get(key)
			if val is False or val in ("0", "false", "off", "none"):
				return False
			if val is True or val in ("1", "true", "on", "yes", "image", "vision"):
				return True
			if isinstance(val, (list, tuple, dict)) and val:
				return True

	mid = (model or "").strip().lower()
	if not mid:
		return False
	markers = (
		"vision",
		"gpt-4o",
		"gpt-4.1",
		"gpt-4-turbo",
		"gpt-5",
		"claude-3",
		"claude-4",
		"claude-sonnet-4",
		"claude-opus-4",
		"gemini",
		"flash-v",
		"vl-",
		"-vl",
	)
	return any(m in mid for m in markers)
