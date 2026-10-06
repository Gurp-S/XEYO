"""XEYO Harbor 适配器：把 XEYO 引擎接入 Harbor 评测框架的 custom agent。

用法（harbor run）:
  -a "xeyo_harbor_agent:XeyoHarborAgent"

本文件是**唯一权威实现**，住在 tracked 路径里（原先在 TerminalBench/ —— 该目录被
.gitignore 整目录排除，于是"评测档到底开了哪些开关"这件事没有任何版本记录）。
harbor 从它的 cwd（TerminalBench/）按 `module:Class` 解析，因此那边留一个
`xeyo_harbor_agent.py` **入口垫片**：只 import 本模块并再导出类，不含逻辑。

职责边界（54 号禀赋架构的基准落点）：
- setup(): 从 trial 会话名解析任务容器名，验证容器可见性；实际路由在 run() 的协程上下文内绑定；
- run(): 进程内构建 XEYO 引擎（XEYO_BENCH_MINIMAL=1，评测档工具面见 tools/catalog.py），
  submit 指令 → 消费事件流 → 回填 AgentContext（tokens/cost）→ 落盘轨迹；
- 墙钟死线（禀赋①）：agent timeout 的 80%/90% 经 BudgetTracker 既有 notice 通道注入；
- 防做题红线：本文件不解析任何题目语义，instruction 原样透传给引擎。

环境变量（由 harbor job 配置 --ae 或外层设置）:
  DEEPSEEK_API_KEY      模型 key（必需）
  XEYO_BENCH_MINIMAL    必须为 1（评测档工具面）
  XEYO_FAKE=1           fake 模型管道自检（零费用）
  XEYO_MAX_TURNS        单题最大对话轮数（默认 160；引擎 build_default_engine
                        自带默认 50，多步任务会被掐死在 error_max_turns）
  XEYO_THINKING         思考态 enabled/disabled（默认 enabled）
  XEYO_REASONING_EFFORT 档位 low/high/max（默认 high；仅 thinking=enabled 时发出）
  XEYO_MULTI_AGENT      子 agent 引导开关（默认 1=开；0 关闭 → 不挂 multi_agent_hint）
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# XEYO 引擎源码目录（适配器与 harbor 同进程，需提前入 path）。
# 本文件现在住在 python/evals/ 下 ⇒ python/ 就是它的上一级，不再写死某台机器的绝对路径
# （旧值 r"D:\lea\XenYon code\python" 是机器绑定的：换克隆路径就静默失效）。
XEYO_PY = os.environ.get("XEYO_PY_DIR", "").strip() or str(Path(__file__).resolve().parents[1])
if XEYO_PY not in sys.path:
    sys.path.insert(0, XEYO_PY)

from typing import Any, override

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName


def _env_int(name: str, default: int) -> int:
    """读环境变量整数；缺省 / 非法值一律回落默认（构建期不因配置中断）。"""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


#: 评测档生效配置（每次跑分写进 AgentContext.metadata，供事后复算）。
#: 教训：9/14 那批跑分没记生效配置，导致事后只能靠轨迹反推当时哪些开关是开的。
BENCH_ENV_DEFAULTS: dict[str, str] = {
    "XEYO_BENCH_MINIMAL": "1",
    "XEYO_PERMISSION_MODE": "never",
    # 45s 自动转后台 vs 命令族超时（timeout_map：make/pip/apt 300s、cargo 420s）
    # 自相矛盾——提交前先被 45s 晋升截断。9/14 实测 job 管理类调用 198 次
    # （job_output 160 + job_list 22 + job_kill 16），占全部工具调用 14%，
    # 每次轮询都是一整轮 LLM 往返。评测档抬到 300s，让 timeout_map 真正生效。
    "XEYO_BASH_PROMOTE_MS": "300000",
    # 子代理引导块：1378 个 assistant 轮里 Agent 工具调用 0 次 ⇒ 该块在评测里
    # 零使用、纯注入。默认关（工具本身仍在）。
    "XEYO_MULTI_AGENT": "0",
    # 最小工作面：只给 Bash/Write/Edit/Glob/Grep/Agent（+ job 三件套，后台配套）。
    # 依据：同批实测 20 个工具里 13 个零调用。置空可回到原生面做对照。
    "XEYO_TOOL_SURFACE": "minimal",
    # 副作用动作在 tool_use 与 tool_result 之间持久化；断流/恢复时不重复执行。
    "XEYO_ACTION_JOURNAL": "1",
    # WSC 生产档（C2 触发、WSC 执行压缩投影）。⚠️ 2026-09-22 之前**根本不在这里**，
    # 而 `memory/wsc_projection.live_enabled()` 只认进程 env ⇒ 全部历史 TB 跑分
    # （含 26 绿那批）都是 **WSC 关闭**状态下拿的。缺这一行时，"WSC 在 TB 上有没有用"
    # 这个问题花多少钱都测不出来。外层可 `XEYO_WSC=0` 覆盖做对照臂。
    "XEYO_WSC": "1",
    # 折叠节奏闸（2026-09-30 起注册表默认=开）：显式钉住。默认值不许当跑分配置的隐式
    # 输入——默认一翻，历史成绩其实换了配置而 metadata 里查不出来。外层置 0 可做对照臂。
    "XEYO_WSC_FOLD_COOLDOWN_VETO": "1",
}

#: 折叠水位提示：WSC 开了也不代表它会参与。触发点是「peak prompt 越过 0.8×窗口」，
#: 而窗口来自登记表（deepseek-flash 系 = 1M ⇒ 水位 800k，TB 单题历史最大 peak 只有 224k
#: ⇒ 一题都不会折叠）。要量机制必须**外层显式**钉 `XEYO_CONTEXT_LIMIT`（机制档，
#: 例如 65536），且该批成绩不可与产品档互引。这里刻意不把窗口写进默认值：
#: 那等于把今天刚修好的"按型号登记真实窗口"再钉回一个错的常数。
_WINDOW_NOTE = (
    "XEYO_CONTEXT_LIMIT 未钉 ⇒ 窗口取登记表；WSC 大概率整轮不参与（peak < 0.8×窗口）。"
    "要测机制请显式 export XEYO_CONTEXT_LIMIT=<小窗口> 并在结论里写明是机制档。"
)


def _apply_bench_env() -> dict[str, str]:
    """写入评测档环境变量；已被外层显式设置的键不覆盖（保留 A/B 覆盖能力）。

    返回本次**实际生效**的配置，供 metadata 留档。
    """
    effective: dict[str, str] = {}
    for key, value in BENCH_ENV_DEFAULTS.items():
        current = (os.environ.get(key) or "").strip()
        if current:
            effective[key] = current  # 外层显式设置优先 → 可做 A/B
        else:
            os.environ[key] = value
            effective[key] = value
    # 诊断档旋钮：默认不动，仅记录（改动须走 A/B，见 docs 归因文档）
    for key in ("XEYO_T_NOW_STRATEGY", "XEYO_CONTEXT_LIMIT", "XEYO_MAX_TURNS",
                "XEYO_THINKING", "XEYO_REASONING_EFFORT", "XEYO_BASH_PROMOTE_MS"):
        current = (os.environ.get(key) or "").strip()
        if current:
            effective[key] = current
    # 留档必须当场说清「WSC 开了但窗口没钉」这种空跑形状 —— 否则跑完又要靠轨迹反推
    # （9/14 那批的教训）。写进 metadata 比打日志有用：日志会随容器一起没。
    if (os.environ.get("XEYO_WSC") or "").strip().lower() in ("1", "true", "on", "yes") \
            and not (os.environ.get("XEYO_CONTEXT_LIMIT") or "").strip():
        effective["__warning_wsc_may_not_trigger"] = _WINDOW_NOTE
    return effective


def _container_name_from_session(session_id: str | None) -> str | None:
    """session_id 形如 `<task>__<hash>__agent`；对应主容器 `<task>__<hash>__env-main-1`。"""
    if not session_id:
        return None
    trial = session_id
    for suffix in ("__agent", "__user"):
        if trial.endswith(suffix):
            trial = trial[: -len(suffix)]
    if "__" not in trial:
        return None
    return f"{trial}__env-main-1"


def _resolve_container(preferred: str | None) -> str | None:
    """优先用推导名；用 docker ps 校验存在性，失败则模糊匹配运行中的 env-main 容器。"""
    import subprocess

    def _ps() -> list[str]:
        try:
            out = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=20,
            ).stdout
            return [l.strip() for l in out.splitlines() if l.strip()]
        except Exception:  # noqa: BLE001
            return []

    names = _ps()
    if preferred and preferred in names:
        return preferred
    if preferred:
        # 容器名大小写不敏感（compose 会小写化），做一次大小写无关匹配
        low = {n.lower(): n for n in names}
        hit = low.get(preferred.lower())
        if hit:
            return hit
    # 兜底：唯一的 env-main 容器（n_concurrent>1 时可能多个，取第一个匹配 trial 前缀）
    envs = [n for n in names if n.endswith("__env-main-1")]
    if preferred:
        prefix = preferred.split("__env-main-1")[0].lower()
        matched = [n for n in envs if n.lower().startswith(prefix)]
        if matched:
            return matched[0]
    if len(envs) == 1:
        return envs[0]
    return None


class XeyoHarborAgent(BaseAgent):
    SUPPORTS_WINDOWS: bool = True

    @staticmethod
    def name() -> str:
        return "xeyo"

    @override
    def version(self) -> str:
        return "1.0.0"

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        # 评测档案：必须在引擎/工具构建前生效
        _apply_bench_env()
        session_id = self.session_id or ""
        container = _container_name_from_session(session_id)
        cid = _resolve_container(container)
        if cid:
            # 不把 trial 容器写进进程级环境变量：Harbor 并发 trial 共用进程，
            # 后写者会污染先写者。run() 会把同一 cid 作为显式 runtime fact 和
            # ContextVar 路由传入引擎；这里仅清理旧的 shell 前缀兼容项。
            os.environ.pop("XEYO_BASH_EXEC_PREFIX", None)
            self.logger.info("XEYO bash routed to container %s", cid)
        else:
            self.logger.warning(
                "XEYO container not found (session=%s); bash will run host-side", session_id
            )

    @override
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        from contextlib import aclosing

        # 评测档生效配置（含容器路由下"工作区外写"的审批放开：headless 没人能批，
        # 硬边界——密钥/策略文件/受保护元数据/危险路径——仍由 policy 更早分支拦截）。
        bench_env = _apply_bench_env()

        # 并发 trial 防串线（p4 冒烟实测）：os.environ 是进程级的，harbor 多
        # trial 共进程时互相覆盖 → 全部 bash 串进最后 setup 的容器（query-optimize
        # 的 agent 落进 raman-fitting 容器被误判"输入文件不存在"）。改为每 trial
        # 在自身协程上下文设置 ContextVar 覆盖（bash/job 工具优先读，env 仅回退）。
        cid_self = ""
        try:
            from tools.container_routing import set_container_override

            cid_self = _resolve_container(
                _container_name_from_session(self.session_id)
            )
            if cid_self:
                set_container_override(cid_self)
                self.logger.info("XEYO contextvar routed to %s", cid_self)
            else:
                # setup() 可能来自另一个并发 trial；当前 trial 找不到容器时，
                # 必须清掉继承的 ContextVar，不能沿用上一题的容器。
                set_container_override("")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("contextvar routing failed: %s", exc)

        agent_timeout = self._agent_timeout_sec()
        scratch = Path(self.logs_dir) / "workspace"
        scratch.mkdir(parents=True, exist_ok=True)

        fake = os.environ.get("XEYO_FAKE") == "1"
        kwargs: dict[str, Any] = {
            "cwd": str(scratch),
            "session_id": (self.session_id or f"xeyo_{os.getpid()}"),
            "runtime": "docker" if cid_self else "local",
            "container_id": cid_self or "",
            "runtime_profile": "terminal-bench-2.1",
            "runtime_verify": True,
        }
        if fake:
            kwargs["model_backend"] = "fake"
        else:
            kwargs.update(
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                # provider 决定 openai_compat 是否把思考态发出去：只有 "deepseek"
                # 分支发 thinking/reasoning_effort（model/openai_compat.py:205-210），
                # 写 "openai" 时档位根本不出网 → 不可控。带 api_key 时 backend 仍走
                # OpenAICompatClient（engine/query_engine.py:1293 分支条件）。
                provider="deepseek",
                model=(self.model_name or "deepseek-v4-flash").split("/")[-1],
                base_url="https://api.deepseek.com/v1",
                thinking=os.environ.get("XEYO_THINKING", "enabled"),
                reasoning_effort=os.environ.get("XEYO_REASONING_EFFORT", "high"),
                max_turns=_env_int("XEYO_MAX_TURNS", 160),
            )

        from engine.query_engine import build_default_engine

        engine = build_default_engine(**kwargs)

        # 禀赋①：墙钟死线 → BudgetTracker 既有 notice 通道（80%/90% 提醒）
        try:
            budget = engine._session.budget  # noqa: SLF001 — 适配器属引擎外挂，接受私有访问
            # R1'：给墙钟留一段收尾 margin——外部 harbor 超时是"硬杀"，引擎内的
            # 优雅收尾（grace → forced_wrap_up 配额窗）需要在这之前跑完。默认
            # margin 0（= 现状：只播报不硬停）；显式武装（XEYO_WALL_HARD_STOP=1）
            # 并设 margin 后，引擎在外部掐断前先落盘再结束。
            margin_raw = os.environ.get("XEYO_WALL_STOP_MARGIN", "").strip()
            try:
                margin = max(0.0, float(margin_raw)) if margin_raw else 0.0
            except ValueError:
                margin = 0.0
            deadline_ts = time.time() + max(0.0, agent_timeout - margin)
            budget.set_wall_deadline(deadline_ts, started_ts=time.time())
            budget.arm_wall_stop(None)  # 跟随 XEYO_WALL_HARD_STOP，默认不武装
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("wall deadline not set: %s", exc)

        # 命中/未命中/输出 累计器（包装 add_usage，读取 split_usage 三元组）
        acc = {"hit": 0, "miss": 0, "out": 0}
        try:
            from usage import pricing as _pricing

            real_add = budget.add_usage

            def _acc_add(usage: dict[str, Any] | None, ts: float | None = None) -> None:
                try:
                    h, m, o = _pricing.split_usage(usage)
                    acc["hit"] += h
                    acc["miss"] += m
                    acc["out"] += o
                except Exception:  # noqa: BLE001
                    pass
                real_add(usage, ts)

            budget.add_usage = _acc_add  # type: ignore[method-assign]
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("usage accumulator unavailable: %s", exc)

        final_text = ""
        events_log: list[dict[str, Any]] = []
        started = time.time()
        _exception_type: str | None = None
        # ⑥ 子 agent（Multi-Agent chip）：引擎侧读 options["multi_agent"]，
        # True 时在 T_now 挂 multi_agent_hint 块（tools/agent_tool/prompt.py），
        # 让模型知道可以派子 agent；工具面本身一直有 Agent（catalog 评测档只裁 4 个）。
        _ma = (os.environ.get("XEYO_MULTI_AGENT", "1") or "1").strip().lower()
        _multi_agent = _ma not in ("0", "false", "no", "off")
        try:
            async with aclosing(engine.submit(instruction, {"multi_agent": _multi_agent})) as stream:
                async for ev in stream:
                    etype = getattr(ev, "type", "") or getattr(ev, "kind", "")
                    if etype in ("assistant_delta", "text_delta"):
                        final_text += getattr(ev, "text", "")
                    events_log.append({
                        "type": type(ev).__name__,
                        "subtype": str(getattr(ev, "subtype", "") or ""),
                    })
                    if type(ev).__name__ == "ResultEvent":
                        if getattr(ev, "result", "") and not final_text:
                            final_text = ev.result
        except Exception as exc:  # noqa: BLE001 — 异常也走结算（轨迹/usage/记忆）
            _exception_type = f"{type(exc).__name__}: {str(exc)[:160]}"
            raise
        finally:
            elapsed = time.time() - started
            b = engine._session.budget  # noqa: SLF001
            context.n_input_tokens = acc["hit"] + acc["miss"]
            context.n_cache_tokens = acc["hit"]
            context.n_output_tokens = acc["out"]
            context.cost_usd = round(b.used_usd, 6)
            # 禀赋③：失败 → 惯例记忆（复用 memdir/memindex）。适配器侧只能感知
            # agent 执行期异常（如 AgentTimeout）；判分期失败由 P3 分析层归类。
            try:
                from memory.failure_note import failure_class_of, note_failure_convention

                fc = failure_class_of(_exception_type, None)
                if fc:
                    note_failure_convention(
                        cwd=str(scratch), task=self.session_id or "task",
                        failure_class=fc, detail=str(final_text)[:200],
                    )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("failure note skipped: %s", exc)
            context.metadata = {
                "engine": "xeyo",
                # 生效配置留档：跑分事故复盘时不必再从轨迹反推当时开了哪些开关
                "bench_env": bench_env,
                "runtime_profile": str(kwargs.get("runtime_profile") or ""),
                "runtime_verify": bool(kwargs.get("runtime_verify", False)),
                "used_cny": round(b.used_cny, 4),
                "used_tokens": b.used_tokens,
                "elapsed_sec": round(elapsed, 1),
                "final_text_chars": len(final_text),
                "events": events_log[-40:],
                "final_text_head": final_text[:600],
            }
            try:
                runtime_snapshot = engine.runtime_snapshot()
                context.metadata["runtime_verification"] = runtime_snapshot.get(
                    "verification", {"checked": False}
                )
                context.metadata["runtime_authorities"] = runtime_snapshot.get(
                    "authorities", {}
                )
            except Exception:
                pass
            # 轨迹持久化：复用 XEYO 现成的磁盘 transcript（~/.xeyo/sessions/<sid>.jsonl）
            try:
                traj_dir = Path(self.logs_dir) / "agent"
                traj_dir.mkdir(parents=True, exist_ok=True)
                sid = kwargs.get("session_id", "")
                src = Path(os.path.expanduser(f"~/.xeyo/sessions/{sid}.jsonl"))
                payload = {
                    "instruction": instruction,
                    "final_text": final_text,
                    "usage": {
                        "input": acc["hit"] + acc["miss"],
                        "cache": acc["hit"],
                        "output": acc["out"],
                        "usd": round(b.used_usd, 6),
                        "cny": round(b.used_cny, 4),
                    },
                    "elapsed_sec": round(elapsed, 1),
                }
                if src.exists():
                    payload["transcript"] = [
                        json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()
                    ]
                (traj_dir / "trajectory.json").write_text(
                    json.dumps(payload, ensure_ascii=False, default=str, indent=1),
                    encoding="utf-8",
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("trajectory dump failed: %s", exc)

    def _agent_timeout_sec(self) -> float:
        """从环境变量读 agent 超时（秒）；默认 30 分钟。"""
        raw = os.environ.get("XEYO_AGENT_TIMEOUT_SEC", "").strip()
        try:
            return max(60.0, float(raw)) if raw else 1800.0
        except ValueError:
            return 1800.0
