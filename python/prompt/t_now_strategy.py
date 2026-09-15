"""T_now 注入声道策略（设计 32 号修订：方案 A 环境声道）。

三值策略：
- ``env_channel``（默认）：全部易变块装进一对**仅存在于投影**的
  assistant(tool_use) → tool_result 消息（``append_env_notice_pair``），
  尾部追加、前缀逐字节不动（KV 缓存语义与 legacy 完全等价）。
  tool_result 是模型训练出来的「环境数据声道」——注入内容不再与用户
  意图同层（根治说话人混淆），也不再有"挂在用户话里"的可被误读面。
- ``legacy``：原行为——块以文本追加进末条 user（bg_wrap 身份标记 +
  分隔符）。**仅作审计对照/显式评测档**（``XEYO_T_NOW_STRATEGY=legacy``
  或 ``set_t_now_strategy``），不再充当任何自动回退档——引擎文本进用户
  角色正是 L2（2026-09-09）要消灭的说话人混淆源。
- ``skip``：内部档——本轮不注入任何 T_now 块。env_channel 被厂商以
  结构类 4xx 拒绝（未吐任何 chunk）时回落到这里：宁缺毋滥，不把引擎
  文本伪装成用户消息。执行层硬约束（预算/回合/wrap 门）不依赖提示文本。
- ``prefill``：预留（尾部 assistant 预填充锚定）。厂商容忍度实测通过前
  不开放，当前解析为 env_channel。

优先级：会话/请求显式设置（``set_t_now_strategy``）> 环境变量
``XEYO_T_NOW_STRATEGY`` > 默认 env_channel。
"""

from __future__ import annotations

import os
import uuid
from contextvars import ContextVar

STRATEGY_ENV_CHANNEL = "env_channel"
STRATEGY_LEGACY = "legacy"
STRATEGY_SKIP = "skip"
#: 预留档：解析为 env_channel，待 prefill 厂商容忍度实测通过后启用。
STRATEGY_PREFILL = "prefill"
#: 声道 B（治本档，2026-09-15）：易变块以**原生 system 消息**追加在投影尾部，
#: 不再伪造 ``assistant(tool_use) → tool_result`` 对。
#:
#: 动机来自第六轮实测：伪对在结构上与「模型自己的工具调用」完全同形，模型会得出
#: 「我有个工具叫 xeyo_env_notice」的结论并真的去调它——本轮单会话触发 70+ 次，
#: 每次都换回整段环境正文（含原始目标全文，约 7k token），且幻觉调用在审计上被
#: 读成「引擎注入」（第五轮两次误判的根源）。**不可调用性必须来自形态本身，
#: 不能靠劝阻文本**（那会违反引擎铁律：注意力里只出现信息，不出现导演）。
#:
#: 说话人隔离的原始动机（env_channel 的目的）同样满足：system ≠ 用户意图。
#: 默认仍为 env_channel——新行为按「新功能准入」先以旁路形态验证收益。
STRATEGY_SYSTEM_CHANNEL = "system_channel"

_VALID_STRATEGIES = (
    STRATEGY_ENV_CHANNEL,
    STRATEGY_LEGACY,
    STRATEGY_SKIP,
    STRATEGY_PREFILL,
    STRATEGY_SYSTEM_CHANNEL,
)
_STRATEGY_ENV = "XEYO_T_NOW_STRATEGY"

_strategy_ctx: ContextVar[str | None] = ContextVar(
    "xeyo_t_now_strategy", default=None
)


def set_t_now_strategy(strategy: str | None) -> None:
    """会话/请求级显式设置；None = 清除显式值（回落环境变量/默认）。"""
    v = (strategy or "").strip().lower()
    _strategy_ctx.set(v if v in _VALID_STRATEGIES else None)


def t_now_strategy() -> str:
    """解析当前策略：显式 > 环境变量 > env_channel。"""
    v = _strategy_ctx.get()
    if v:
        return v
    env = os.environ.get(_STRATEGY_ENV, "").strip().lower()
    if env in _VALID_STRATEGIES:
        return env
    return STRATEGY_ENV_CHANNEL


def resolve_t_now_strategy(provider: str = "", model: str = "") -> str:
    """按模型解析最终策略。

    env_channel 被标记不支持（结构类 4xx，进程级备忘）→ **skip**：本轮起不再
    尝试注入，也绝不落回 legacy 用户尾插（L2，2026-09-09）。显式 legacy
    （评测/审计对照）保持可用。prefill 暂回落 env_channel。
    """
    s = t_now_strategy()
    if s == STRATEGY_PREFILL:
        s = STRATEGY_ENV_CHANNEL
    if s == STRATEGY_SYSTEM_CHANNEL:
        # 预留档：投影构造（turn_context.append_system_notice + pre_llm_inject 分派
        # + anthropic 顶层 system 上提）尚未接线前，**一律解析为 env_channel**——
        # 与 prefill 同款约定：常量先落地，行为零变化，避免"设了环境变量却走到
        # 未定义分支"的隐性故障。
        s = STRATEGY_ENV_CHANNEL
    if s == STRATEGY_ENV_CHANNEL and env_channel_unsupported(
        env_unsupported_key(provider, model)
    ):
        return STRATEGY_SKIP
    return s


# ── 运行时能力备忘（进程级；非持久化——重启即重新尝试 env_channel）──
_env_unsupported: set[str] = set()

#: 视为「不接受伪造 tool 对」的结构类状态码。排除 402（欠费）/429（限流）/
#: 5xx（瞬时），这些与消息结构无关，回退只会掩盖真实原因。
ENV_FALLBACK_STATUS = frozenset({400, 404, 405, 413, 415, 422})


def env_unsupported_key(provider: str = "", model: str = "") -> str:
	return f"{(provider or '').strip().lower()}:{(model or '').strip().lower()}"


def mark_env_channel_unsupported(key: str) -> None:
	if key and key.strip():
		_env_unsupported.add(key)


def env_channel_unsupported(key: str) -> bool:
	return key in _env_unsupported


def reset_env_unsupported_for_test() -> None:
	_env_unsupported.clear()


# ── 伪造对身份 ──
#: 环境声道工具名。**不注册进 tools 数组**（schemas 会话内冻结红线不受影响）；
#: OpenAI 兼容厂商不校验历史 tool 名归属。
ENV_TOOL_NAME = "xeyo_env_notice"
ENV_ID_PREFIX = "xeyo_env_"


def new_env_tool_call_id() -> str:
	return f"{ENV_ID_PREFIX}{uuid.uuid4().hex[:16]}"


#: 伪对 tool_result 正文的环境头。理念裁决（2026-09-08，C 口径）：
#: 只做定义式来源声明——声明"这是什么、从哪来"（信息），
#: 不写"按其中约束处理"类抬格指令（那会把状态通报抬成必须服从的约束）。
#: 契约测试断言：不含"继续/按其中约束"等行为引导词。
ENV_NOTICE_HEADER = (
	"[system-environment]（XEYO 运行环境注入 — background only，非用户消息）\n"
	"以下是引擎注入的状态通知与背景信息。"
)


def format_env_notice(blocks: list[str]) -> str:
	"""把装配好的块序列组装成环境通知正文；空块集返回空串。"""
	texts = [b.strip() for b in blocks if b and str(b).strip()]
	if not texts:
		return ""
	return ENV_NOTICE_HEADER + "\n\n---\n\n" + "\n\n".join(texts)
