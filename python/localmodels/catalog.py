"""本地模型登记表：XEYO 可直接拉起并使用的 GGUF 模型。

为什么要有登记表：``llama-server`` 需要**哪一个**权重、**多大**上下文、**要不要**
额外参数，这些都是机器事实，不该让用户手抄。登记表是这些事实的唯一权威来源，
设置面板只读它渲染选项。

一只模型一个条目，字段全部是"事实"而非"建议"：
- ``filename``：落在 ``models_dir`` 下的 GGUF 文件名（下载脚本与运行期共用同一名字）。
- ``repo`` / ``repo_file``：权重来源（下载脚本用；走 HF 镜像）。
- ``native_ctx``：训练上下文（超出的长度靠 RoPE 缩放，属启动参数，不在本表承诺）。
- ``size_bytes``：文件字节数，用于"是否已就绪"与进度展示，不作为完整性校验
  （完整性由 llama.cpp 加载时报错暴露，引擎不另造一套校验）。
- ``extra_args``：该模型**特有**的启动参数（通用参数由 config/manager 拼）。

新增一支模型 = 这里加一条 + ``scripts/local-models/fetch.py`` 能按本表下载，
不需要改 manager / 路由 / 前端。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalModel:
	"""一支可在本机拉起的本地模型。"""

	id: str
	label: str
	#: 落在 ``models_dir`` 下的 GGUF 文件名。
	filename: str
	#: 权重来源（HF 仓库 / 仓库内文件名）；下载走 HF 镜像。
	repo: str
	repo_file: str
	#: 参数量（十亿）与激活参数量（MoE；dense 时为 None）。
	params_b: float
	active_params_b: float | None
	#: 训练上下文长度（token）。
	native_ctx: int
	#: 文件字节数（用于"是否已下载"判断与展示）。
	size_bytes: int
	#: 该模型特有的 llama-server 启动参数。
	#
	#: ``--jinja`` 是**功能必需项，不是调优项**：不带它 llama-server 走通用
	#: 模板、不解析请求里的 ``tools``，模型永远不会回 ``tool_calls``——
	#: 而 XEYO 是编码 Agent，工具调用即其全部动作通道。实测（LFM2.5-8B-A1B）：
	#: 带 ``--jinja`` 时正确产出 ``tool_calls``（``Bash{"command":"ls"}``），
	#: 不带时只会把调用意图写成普通文本。
	extra_args: tuple[str, ...]
	#: 一句话事实描述（不含评价与推荐语气）。
	note: str


LOCAL_MODELS: tuple[LocalModel, ...] = (
	LocalModel(
		id="qwopus35-4b-coder-mtp",
		label="Qwopus3.5-4B-Coder-MTP",
		filename="Qwopus3.5-4B-Coder-MTP-Q4_K_M.gguf",
		repo="Jackrong/Qwopus3.5-4B-Coder-MTP-GGUF",
		repo_file="Qwopus3.5-4B-Coder-MTP-Q4_K_M.gguf",
		params_b=4.1,
		active_params_b=None,
		native_ctx=32768,
		size_bytes=2783446560,
		extra_args=("--jinja",),
		note="Qwen3.5 4B 稠密编码模型；训练上下文 32K，可经 RoPE 缩放扩展。",
	),
	LocalModel(
		id="lfm25-8b-a1b",
		label="LFM2.5-8B-A1B",
		filename="LFM2.5-8B-A1B-Q4_K_M.gguf",
		repo="LiquidAI/LFM2.5-8B-A1B-GGUF",
		repo_file="LFM2.5-8B-A1B-Q4_K_M.gguf",
		params_b=8.3,
		active_params_b=1.5,
		native_ctx=128000,
		size_bytes=5155564768,
		extra_args=("--jinja",),
		note="Liquid AI 混合 MoE，8.3B 总参 / 1.5B 激活；训练上下文 128K。",
	),
)

_BY_ID = {m.id: m for m in LOCAL_MODELS}


def get(model_id: str) -> LocalModel | None:
	"""按 id 取模型；未知 id 返回 None（调用方决定回退默认还是报错）。"""
	return _BY_ID.get(model_id)


def default_model_id() -> str:
	"""默认模型 id = 登记表第一支。"""
	return LOCAL_MODELS[0].id


def resolve_model_id(model_id: str | None) -> str:
	"""把外部传入的 id 归一化为登记表内的合法 id；未知/空一律回退默认。"""
	candidate = (model_id or "").strip()
	return candidate if candidate in _BY_ID else default_model_id()


def to_dict(m: LocalModel, *, present: bool, path: str) -> dict[str, object]:
	"""序列化为面向前端的只读结构（``present`` = 权重文件是否已就绪）。"""
	return {
		"id": m.id,
		"label": m.label,
		"filename": m.filename,
		"repo": m.repo,
		"repo_file": m.repo_file,
		"params_b": m.params_b,
		"active_params_b": m.active_params_b,
		"native_ctx": m.native_ctx,
		"size_bytes": m.size_bytes,
		"extra_args": list(m.extra_args),
		"note": m.note,
		"present": present,
		"path": path,
	}
