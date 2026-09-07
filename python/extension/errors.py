"""扩展层统一异常。"""

from __future__ import annotations


class ExtensionError(Exception):
	"""扩展层基类异常。"""


class ManifestError(ExtensionError):
	"""插件 manifest 非法（坏路径、缺字段、min_xeyo 不满足等）。

	调用方应跳过该插件并记录，不让单个坏插件搞挂启动。
	"""

	def __init__(self, message: str, *, name: str | None = None) -> None:
		super().__init__(message)
		self.message = message
		self.name = name

	def __str__(self) -> str:
		return f"[{self.name}] {self.message}" if self.name else self.message




class ConfigError(ExtensionError):
	"""settings.json 读写/迁移失败。"""


class PluginError(ExtensionError):
	"""插件安装/更新/卸载/漂移相关失败。"""


class PluginConflictError(PluginError):
	"""插件同名冲突（已存在，默认禁止覆盖他人安装）。"""
