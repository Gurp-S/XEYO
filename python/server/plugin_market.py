"""插件市场 registry：``<home>/plugin-market.json`` 白名单源读取。

市场只做「来源浏览/检索」的 registry（默认关，见 :meth:`ExtensionConfig.plugin_market_enabled`）。
真正的安装限制由企业 ``plugin_deny`` 一票否决 + ``plugin_market_allow`` 白名单过滤。
坏读 → 空 registry（skip-and-log），不让单个坏文件搞挂市场查询。

registry 形状：
.. code-block:: jsonc

	{
	  "version": 1,
	  "sources": [
	    {"name": "filesystem-helper", "source": "github:owner/repo", "description": "..."}
	  ]
	}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from memory.instruction import xeyo_home

_log = logging.getLogger(__name__)


def market_registry_path() -> Path:
	return xeyo_home() / "plugin-market.json"


def load_market_registry() -> list[dict[str, Any]]:
	"""返回市场源列表；坏读/缺文件 → []。"""
	path = market_registry_path()
	if not path.is_file():
		return []
	try:
		raw = json.loads(path.read_text(encoding="utf-8"))
		if isinstance(raw, dict) and isinstance(raw.get("sources"), list):
			return [s for s in raw["sources"] if isinstance(s, dict)]
		_log.warning("plugin-market.json at %s is not a valid registry; using empty", path)
		return []
	except (OSError, json.JSONDecodeError) as e:
		_log.warning("bad plugin-market.json at %s: %s; using empty", path, e)
		return []
