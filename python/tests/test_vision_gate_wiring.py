"""接线自证（strict xfail）：Read 的 vision 门宣称按"厂商 /models 的 modes/capabilities"判定，
但那条判定在生产里**永远拿不到数据** —— 承载它的字段根本不存在。

`model/vision_capability.py` 的 docstring 写着三步顺序：
1) `XEYO_READ_VISION=0/1` 强制；2) 厂商 /models 的 modes/capabilities；3) 模型 id 启发式。
`server/session_pool.py:505` 也确实写了 `modes = getattr(cfg, "modes", None)`，
并在 `:511` 传进 `supports_vision_input(modes=...)`。
但 `ModelConfig`（同文件 :84）没有 `modes` 字段，全仓也没有任何地方往 cfg 上挂它 ⇒
那个 `getattr` **恒为 None**：第 2 步在生产里从来没被执行过，门实际上只剩启发式。
CLI/进程内路径（`engine/query_engine.py:1625`）连 `modes=` 都没传，同样只剩启发式。

后果是双向的，都落在 agent 执行上：
- 真支持图片但 id 里没有标记（私有部署/别名，如 `glm-4v-plus` 之外的一串自定义名）
  ⇒ Read 不发图 ⇒ 模型看不到用户让它看的图像；
- id 里有标记但实际不支持（如按启发式命中 `gemini`/`flash-v` 的兼容网关别名）
  ⇒ 发图 ⇒ 厂商 4xx。

为什么挂 xfail 而不直接修：补这一步要新增字段并把厂商行一路传到建表处
（`server/session_pool.py` 在他人手里、`model/vendor_models.py` 的产出没有下游持有者），
属于给链路加接口 = 机制面，等你拍。修法草案：
A. `ModelConfig` 加 `modes: dict[str, Any] | None = None`，在模型解析处从
   `normalize_vendor_model()` 的行里带出来；两个调用点都传（CLI 那侧同样补）。
B. 承认"只有启发式"，把 docstring 与 `getattr` 那句假接线删掉，别让人以为厂商能力在生效。
"""

import dataclasses

import pytest


@pytest.mark.xfail(
	strict=True,
	reason=(
		"已知断链（等裁定）：ModelConfig 没有 modes 字段 ⇒ session_pool 的 "
		"`getattr(cfg, \"modes\", None)` 恒 None，vision 门的\"厂商能力\"那一步从不执行；"
		"补字段属于给链路加接口（机制面），修法见本文件 docstring A/B。"
	),
)
def test_model_config_can_carry_vendor_declared_modes() -> None:
	from server.session_pool import ModelConfig

	names = {f.name for f in dataclasses.fields(ModelConfig)}
	assert "modes" in names, f"vision 门要读 cfg.modes，但 ModelConfig 没这个字段：{sorted(names)}"


def test_pool_reads_cfg_modes_by_getattr_default() -> None:
	"""自证这条门测的是真断口，不是我把源码读错了：现场读回那段代码。"""
	import inspect

	import server.session_pool as sp

	src = inspect.getsource(sp)
	assert 'getattr(cfg, "modes", None)' in src, "session_pool 里那句 modes 取值变了，本文件要重写"

	names = {f.name for f in dataclasses.fields(sp.ModelConfig)}
	# 现状：字段不存在 ⇒ getattr 永远走默认值 None。
	assert "modes" not in names
