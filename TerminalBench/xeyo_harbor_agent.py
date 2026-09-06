"""XEYO Harbor 适配器：把 XEYO 引擎接入 Harbor 评测框架的 custom agent。

用法（harbor run）:
  -a "xeyo_harbor_agent:XeyoHarborAgent"

职责边界（54 号禀赋架构的基准落点）：
- setup(): 从 trial 会话名解析任务容器名，设置 XEYO_BASH_EXEC_PREFIX（bash 容器路由）；
- run(): 进程内构建 XEYO 引擎（XEYO_BENCH_MINIMAL=1 bash-only 最小档案），
  submit 指令 → 消费事件流 → 回填 AgentContext（tokens/cost）→ 落盘轨迹；
- 墙钟死线（禀赋①）：agent timeout 的 80%/90% 经 BudgetTracker 既有 notice 通道注入；
- 防做题红线：本文件不解析任何题目语义，instruction 原样透传给引擎。

环境变量（由 harbor job 配置 --ae 或外层设置）:
  DEEPSEEK_API_KEY   模型 key（必需）
  XEYO_BENCH_MINIMAL 必须为 1（最小档案）
  XEYO_FAKE=1        fake 模型管道自检（零费用）
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# XEYO 引擎源码目录（适配器与 harbor 同进程，需提前入 path）
XEYO_PY = r"D:\lea\XenYon code\python"
if XEYO_PY not in sys.path:
    sys.path.insert(0, XEYO_PY)

from typing import Any, override

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName


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
        # 评测最小档案：必须在引擎/工具构建前生效
        os.environ["XEYO_BENCH_MINIMAL"] = "1"
        session_id = self.session_id or ""
        container = _container_name_from_session(session_id)
        cid = _resolve_container(container)
        if cid:
            # docker SDK 直连（named pipe）：pwsh -Command 下 docker exec 的 stdout
            # 会静默丢失（批 2 实测模型全程盲打），SDK 走 API 无此问题。
            os.environ["XEYO_DOCKER_CONTAINER"] = cid
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

        os.environ["XEYO_BENCH_MINIMAL"] = "1"
        # 容器路由下，写目标在容器路径（如 /app/...），宿主 cwd 的"工作区外写"
        # 检查必然误拒——headless 评测放开审批档（never=免确认），硬边界
        # （密钥/策略文件/受保护元数据/危险路径）仍由 policy 更早分支拦截。
        os.environ["XEYO_PERMISSION_MODE"] = "never"

        # 并发 trial 防串线（p4 冒烟实测）：os.environ 是进程级的，harbor 多
        # trial 共进程时互相覆盖 → 全部 bash 串进最后 setup 的容器（query-optimize
        # 的 agent 落进 raman-fitting 容器被误判"输入文件不存在"）。改为每 trial
        # 在自身协程上下文设置 ContextVar 覆盖（bash/job 工具优先读，env 仅回退）。
        try:
            from tools.container_routing import set_container_override

            cid_self = _resolve_container(
                _container_name_from_session(self.session_id)
            )
            if cid_self:
                set_container_override(cid_self)
                self.logger.info("XEYO contextvar routed to %s", cid_self)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("contextvar routing failed: %s", exc)

        agent_timeout = self._agent_timeout_sec()
        scratch = Path(self.logs_dir) / "workspace"
        scratch.mkdir(parents=True, exist_ok=True)

        fake = os.environ.get("XEYO_FAKE") == "1"
        kwargs: dict[str, Any] = {
            "cwd": str(scratch),
            "session_id": (self.session_id or f"xeyo_{os.getpid()}"),
        }
        if fake:
            kwargs["model_backend"] = "fake"
        else:
            kwargs.update(
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                provider="openai",
                model=(self.model_name or "deepseek-v4-flash").split("/")[-1],
                base_url="https://api.deepseek.com/v1",
            )

        from engine.query_engine import build_default_engine

        engine = build_default_engine(**kwargs)

        # 禀赋①：墙钟死线 → BudgetTracker 既有 notice 通道（80%/90% 提醒）
        try:
            budget = engine._session.budget  # noqa: SLF001 — 适配器属引擎外挂，接受私有访问
            budget.set_wall_deadline(
                time.time() + agent_timeout, started_ts=time.time()
            )
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
        try:
            async with aclosing(engine.submit(instruction)) as stream:
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
                "used_cny": round(b.used_cny, 4),
                "used_tokens": b.used_tokens,
                "elapsed_sec": round(elapsed, 1),
                "final_text_chars": len(final_text),
                "events": events_log[-40:],
                "final_text_head": final_text[:600],
            }
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
