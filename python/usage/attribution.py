"""用量事件「真实厂商」(vendor) 判定。

背景（2026-09-09 用量面板审计 P0-1）：账本里 ``provider`` 记的是「接入通道」
（deepseek / openai preset），不是模型所属厂商——glm 模型挂在 deepseek 通道、
deepseek-v4-flash 挂在 openai 通道的行真实存在。后果：按 provider 分组厂商错乱、
``estimate_cny`` 按 provider 查价目把模型套进错误的档位。

本模块为每一行推导与模型真实归属一致的 ``vendor``：
- 通道本身是本地 / 假模型（local / fake）时保持通道（本地推理不产生厂商消费）；
- 其次看 base_url 主机白名单（同一模型可由任意 OpenAI 兼容代理转发）；
- 再次看模型名前缀（deepseek→DeepSeek、glm→智谱、gpt→OpenAI、qwen→通义…）；
- 以上都判不出时回退到通道 provider（无从推断时通道即厂商）。

``provider`` 字段的「通道」语义保持不变（用于定位用的是哪条 API Key / 哪个 preset），
统计 / 计价 / 分组一律改用 ``vendor``。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

# 接入通道本身不是"模型厂商"的情形：本地推理与测试用假模型。
_NON_VENDOR_CHANNELS = frozenset({"local", "fake"})

# base_url 主机 → 厂商（优先于模型名前缀：同一模型可能经任意兼容网关转发）。
_HOST_VENDOR: dict[str, str] = {
	"api.deepseek.com": "deepseek",
	"api.openai.com": "openai",
	"open.bigmodel.cn": "zhipu",
	"bigmodel.cn": "zhipu",
	"dashscope.aliyuncs.com": "qwen",
	"api.moonshot.cn": "moonshot",
	"api.anthropic.com": "anthropic",
	"generativelanguage.googleapis.com": "google",
	"ark.cn-beijing.volces.com": "doubao",
	"hunyuan.tencentcloudapi.com": "tencent",
	"qianfan.baidubce.com": "baidu",
	"spark-api.xf-yun.com": "iflytek",
}

# 模型名前缀 → 厂商。按名字长度降序匹配，避免短前缀（o1/gpt…）抢先。
# 规则：``名字 == 前缀`` 或 ``名字以 前缀+分隔符 开头``；分隔符含 - / . : 与数字，
# 以覆盖 qwen2.5（无分隔符）这类命名。
_MODEL_PREFIX_VENDOR: dict[str, str] = {
	"deepseek": "deepseek",
	"chatglm": "zhipu",
	"glm": "zhipu",
	"codegeex": "zhipu",
	"gpt": "openai",
	"o4-mini": "openai",
	"o3-mini": "openai",
	"o1": "openai",
	"o3": "openai",
	"o4": "openai",
	"gpt-oss": "openai",
	"qwen": "qwen",
	"claude": "anthropic",
	"gemini": "google",
	"doubao": "doubao",
	"seed": "doubao",
	"moonshot": "moonshot",
	"kimi": "moonshot",
	"hunyuan": "tencent",
	"ernie": "baidu",
	"wenxin": "baidu",
	"spark": "iflytek",
	"minimax": "minimax",
	"abab": "minimax",
	"mistral": "mistral",
	"llama": "meta",
	"command-r": "cohere",
	"yi": "01ai",
}

# 前端面板厂商分组标题映射（与 usage 统计输出一致；新厂商在此登记 + 前端 VENDOR_LABEL 同步）。
VENDOR_LABEL: dict[str, str] = {
	"deepseek": "DeepSeek",
	"openai": "OpenAI",
	"zhipu": "智谱",
	"qwen": "通义千问",
	"moonshot": "Kimi",
	"doubao": "豆包",
	"tencent": "腾讯混元",
	"baidu": "百度文心",
	"iflytek": "讯飞星火",
	"anthropic": "Anthropic",
	"google": "Google",
	"minimax": "MiniMax",
	"meta": "Meta Llama",
	"mistral": "Mistral",
	"cohere": "Cohere",
	"01ai": "零一万物",
	"local": "本地模型",
	"fake": "Fake（测试）",
}


def vendor_label(vendor: str) -> str:
	"""厂商 id → 显示名（无映射时原样返回）。"""
	return VENDOR_LABEL.get((vendor or "").lower(), vendor or "unknown")


def _host_of(base_url: str | None) -> str:
	if not base_url:
		return ""
	try:
		return (urlsplit(base_url).hostname or "").lower()
	except ValueError:
		return ""


def vendor_from_host(base_url: str | None) -> str:
	"""按 base_url 主机名判厂商；白名单未命中返回空串。"""
	host = _host_of(base_url)
	if not host:
		return ""
	# 逐段匹配：ark.cn-beijing.volces.com 等长主机优先整串比对，其次含子串。
	if host in _HOST_VENDOR:
		return _HOST_VENDOR[host]
	for frag, vendor in _HOST_VENDOR.items():
		if frag in host:
			return vendor
	return ""


def vendor_from_model_name(model: str) -> str:
	"""按模型名前缀判厂商；判不出返回空串。"""
	name = (model or "").strip().lower()
	if not name:
		return ""
	for prefix, vendor in sorted(
		_MODEL_PREFIX_VENDOR.items(),
		key=lambda kv: -len(kv[0]),
	):
		if not prefix:
			continue
		if not name.startswith(prefix):
			continue
		if name == prefix:
			return vendor
		# 短前缀（≤3 字符）要求显式分隔符，避免 o1/gpt 之外的误命中。
		after = name[len(prefix):]
		c = after[:1]
		if c in ("-", "/", ".", ":", "_"):
			return vendor
		if len(prefix) > 3 and c.isdigit():
			# qwen2.5 / glm4 这类：前缀后紧跟数字即算命中。
			return vendor
	return ""


def canonical_vendor(
	*,
	model: str,
	provider: str,
	base_url: str | None = None,
) -> str:
	"""一行用量事件的真实厂商。

	优先级：通道语义(local/fake 保持) → base_url 主机 → 模型名前缀 → 回退通道。
	"""
	channel = (provider or "unknown").lower()
	if channel in _NON_VENDOR_CHANNELS:
		return channel
	vendor = vendor_from_host(base_url)
	if vendor:
		return vendor
	vendor = vendor_from_model_name(model)
	if vendor:
		return vendor
	return channel


# 上面的"模型名前缀 → 厂商"是顺序无关的纯函数表；对既有/未知行做**查询侧**兜底：
# 读账本时若行缺 vendor 字段（迁移前的旧行）仍能按模型名推断出正确归属。
def event_vendor(event: dict[str, Any]) -> str:
	"""读账本行时取 vendor：优先行内字段，缺失则现场推断（防迁移遗漏）。"""
	raw = event.get("vendor")
	if isinstance(raw, str) and raw.strip():
		return raw.strip().lower()
	return canonical_vendor(
		model=str(event.get("model") or ""),
		provider=str(event.get("provider") or ""),
	)
