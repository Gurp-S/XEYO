"""T_now 注入声道策略（设计 32 号修订：方案 A 环境声道 → 声道 B 治本）。

四值策略：
- ``system_channel``（**2026-09-15 起默认**）：全部易变块作为一条**原生
  system 消息**追加在投影尾部（``turn_context.append_system_notice``）。
  这是伪对缺陷的治本档：``env_channel`` 的伪对
  ``assistant(tool_use: xeyo_env_notice) → tool_result`` 与「模型自己的工具
  调用」完全同形 ⇒ 模型在投影里看到自己调过该工具，判定自己拥有它并真的去调。
  实测：第六轮单会话 70+ 次，第七轮单会话 80+ 次（含多次整条响应体只有该调用），
  且**被 host 侧应答者当成真实工具轮应答**（回灌 ``# Continue（工具结果后）``）
  ⇒ 自催化闭环，意图抑制无效。
  system 是"引擎注入的状态"的原生声道：不是 user（说话人隔离成立），
  也不是 assistant（不伪装成模型自身行为）⇒ 不可调用性来自形态本身。
  协议分工：OpenAI 系保留 role=system；Anthropic 由 ``_split_system``
  上提顶层 ``system`` 字段。
- ``env_channel``：原默认（伪造 tool 对）。**保留为对照/回退档**：声道 B 被
  厂商以结构类 4xx 拒绝（厂商不接受 messages 里的 system 角色）时，本进程内
  对该 provider:model 退回本档（保功能；已知代价是会重新引入上述 affordance）。
- ``legacy``：更早的行为——块以文本追加进末条 user（bg_wrap 身份标记 +
  分隔符）。**仅作审计对照/显式评测档**（``XEYO_T_NOW_STRATEGY=legacy``
  或 ``set_t_now_strategy``），不充当任何自动回退档——引擎文本进用户角色
  正是 L2（2026-09-09）要消灭的说话人混淆源。
- ``skip``：内部档——本轮不注入任何 T_now 块。env_channel 被标记不支持时的
  终态：宁缺毋滥，不把引擎文本伪装成用户消息。执行层硬约束（预算/回合/wrap
  门）不依赖提示文本。
- ``prefill``：预留（尾部 assistant 预填充锚定）。厂商容忍度实测通过前
  不开放，当前解析为 env_channel。

优先级：会话/请求显式设置（``set_t_now_strategy``）> 环境变量
``XEYO_T_NOW_STRATEGY`` > 默认 system_channel。

回退阶梯（均为进程级备忘，重启即重试）：
``system_channel`` --结构类 4xx--> ``env_channel`` --结构类 4xx--> ``skip``
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
#: 默认已切到 system_channel；env_channel 保留为回退/对照档。
STRATEGY_SYSTEM_CHANNEL = "system_channel"

#: 声道 C（包封片段档）：易变块以**一条 user 消息**投递，正文用 ``<system-reminder>``
#: 包封 + 定义式来源声明。存在的唯一理由：``system_channel`` 在部分厂商被拒
#: （messages 里的 system 角色 ⇒ 结构类 4xx）时，旧阶梯降级到 ``env_channel``
#: （伪造 tool 对），一次降级同时欠下四条债——假 id 触发厂商 ``reasoning_content``
#: 校验、无主 tool 结果、模型模仿 ``xeyo_env_notice`` 的 affordance、以及清扫逻辑。
#: user 角色所有厂商都收，且**不含任何 tool_use 形状** ⇒ 不可调用性仍来自形态。
#: 代价（必须知道）：注入文本落在 user 角色，说话人隔离弱于 system，靠包封承载
#: 语义；因此它排在 system 之后、伪对之前，且生产阶梯不再产出伪对。
STRATEGY_NOTICE_FRAGMENT = "notice_fragment"

#: 包封标签与来源声明的**唯一**定义处在 ``prompt.notice_sections``（词法身份三件套
#: wrap/is/strip 同处）；本模块只管档位，不持有文本形态。

_VALID_STRATEGIES = (
    STRATEGY_ENV_CHANNEL,
    STRATEGY_LEGACY,
    STRATEGY_SKIP,
    STRATEGY_PREFILL,
    STRATEGY_SYSTEM_CHANNEL,
    STRATEGY_NOTICE_FRAGMENT,
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
    """解析当前策略：显式 > 环境变量 > 默认 notice_fragment（声道 C）。

    2026-09-22 默认档从 system_channel 换成 notice_fragment，与 Codex / Claude Code
    对齐：两家都把引擎注入的状态放在 **user 侧 + 共训练包封标签**
    （``<system-reminder>``）里，没有一家往 messages 中段塞 system 角色——那恰好是
    各家网关兼容性最不确定的一环，摆在默认位等于指望厂商配合。system_channel
    保留为显式对照档（厂商拒它时阶梯仍落到默认档）。
    """
    v = _strategy_ctx.get()
    if v:
        return v
    env = os.environ.get(_STRATEGY_ENV, "").strip().lower()
    if env in _VALID_STRATEGIES:
        return env
    return STRATEGY_NOTICE_FRAGMENT


def resolve_t_now_strategy(provider: str = "", model: str = "") -> str:
    """按模型解析最终策略（回退阶梯见模块 docstring）。

    ``system_channel`` 被标记不支持（厂商不接受 messages 里的 system 角色，
    结构类 4xx）→ 降级到 ``notice_fragment``（声道 C：user 消息 + 包封）。
    **不再降级到 ``env_channel``**：伪对与「模型自己的工具调用」同形，一次降级
    同时引入假 id 的 ``reasoning_content`` 校验、无主 tool_result、以及模型模仿
    ``xeyo_env_notice`` 的 affordance（实测单会话 60-70+ 次）。``env_channel``
    仅保留为**显式**评测/对照档。``notice_fragment`` 再被标记 → ``skip``
    （L2：宁缺毋滥，绝不落回 legacy 用户尾插）。prefill 回落 notice_fragment。
    """
    s = t_now_strategy()
    if s == STRATEGY_PREFILL:
        s = STRATEGY_NOTICE_FRAGMENT
    key = env_unsupported_key(provider, model)
    if s == STRATEGY_SYSTEM_CHANNEL and system_channel_unsupported(key):
        s = STRATEGY_NOTICE_FRAGMENT
    if s == STRATEGY_NOTICE_FRAGMENT and notice_fragment_unsupported(key):
        return STRATEGY_SKIP
    if s == STRATEGY_ENV_CHANNEL and env_channel_unsupported(key):
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


# ── 声道 B 备忘：厂商不接受 messages 里的 system 角色（结构类 4xx）──
_system_unsupported: set[str] = set()


def mark_system_channel_unsupported(key: str) -> None:
	if key and key.strip():
		_system_unsupported.add(key)


def system_channel_unsupported(key: str) -> bool:
	return key in _system_unsupported


def reset_system_unsupported_for_test() -> None:
	_system_unsupported.clear()


# ── 声道 C 备忘：厂商连 user 包封片段也拒（理论上不该发生，留降级出口）──
_fragment_unsupported: set[str] = set()


def mark_notice_fragment_unsupported(key: str) -> None:
	if key and key.strip():
		_fragment_unsupported.add(key)


def notice_fragment_unsupported(key: str) -> bool:
	return key in _fragment_unsupported


def reset_fragment_unsupported_for_test() -> None:
	_fragment_unsupported.clear()


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
