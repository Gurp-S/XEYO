"""本地模型授权位：决定 ``provider="local"`` 是否被引擎接受。

历史口径只有环境变量 ``XEYO_ALLOW_LOCAL_MODEL=1``（``server/deps.local_model_enabled``）。
那条口径的问题是：**授权面在产品之外**——用户在设置面板里开关不了它，必须动环境变量
或 .bat 才能用上自己刚配好的本地模型。

本模块把授权位并到产品面：``settings.local_models.enabled`` 为真即放行。语义上这是
「用户在本机显式启用了本地模型服务」这一动作的直接后果，与
``server/deps._is_user_configured_base_url``「用户显式配置过的地址放行」同一哲学。

两个来源是 **OR**：环境变量保留为无 GUI 场景（评测 / 脚本 / CI）的通道，
设置面板是产品通道。**默认仍然不放行**——两边都没开时 ``provider="local"`` 照旧被拒。
"""

from __future__ import annotations

import os


def _env_enabled() -> bool:
	return os.environ.get("XEYO_ALLOW_LOCAL_MODEL", "").strip().lower() in (
		"1",
		"true",
		"yes",
		"on",
	)


def local_model_allowed(cwd: str | None = None) -> bool:
	"""``provider="local"`` 是否被接受：环境变量 **或** 设置面板启用。"""
	if _env_enabled():
		return True
	try:
		from localmodels import config

		return bool(config.store(cwd).get("enabled"))
	except Exception:  # noqa: BLE001 — 配置不可读时按"未启用"处理（fail-closed）
		return False
