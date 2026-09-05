"""DeepSeek 评测客户端：同步非流式、重试退避、usage 与成本记账。

仅供起步阶段基准（BFCL-lite / HumanEval-lite / MBPP-lite）使用。
计价口径取自《起步阶段》表格1隐含单价：输入 0.1 元/M tokens，输出 4.5 元/M tokens，
缓存命中按 0.1 倍计。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = os.environ.get("XEYO_EVAL_MODEL", "deepseek-v4-flash-vision-exp")
BASE_URL = (
    os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    or "https://api.deepseek.com"
)
STARTUP_DIR = REPO_ROOT / "artifacts" / "benchmarks" / "startup"
DATA_DIR = STARTUP_DIR / "data"

# 计价单价（元/M tokens）默认取自《起步阶段》表格1，可用环境变量覆盖，避免硬编码漂移。
# 注意：completion_tokens 已含 reasoning_tokens（DeepSeek 对输出 token 统一计价），
# 因此估算成本时不得再单独以「非 reasoning 输出」计算，否则会像表格1预估值那样
# 系统性低估开思考的代码基准成本。
PRICE_IN_PER_M_CNY = float(os.environ.get("XEYO_EVAL_PRICE_IN_PER_M", "0.1"))
PRICE_OUT_PER_M_CNY = float(os.environ.get("XEYO_EVAL_PRICE_OUT_PER_M", "4.5"))
CACHE_HIT_FACTOR = float(os.environ.get("XEYO_EVAL_CACHE_HIT_FACTOR", "0.1"))


def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


class EvalError(RuntimeError):
    pass


@dataclass
class UsageAccount:
    name: str
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    requests: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    elapsed_s: float = 0.0

    def add(self, usage: dict | None, elapsed: float) -> None:
        with self.lock:
            self.requests += 1
            self.elapsed_s += elapsed
            if usage:
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                cd = usage.get("completion_tokens_details") or {}
                self.reasoning_tokens += int(cd.get("reasoning_tokens") or 0)
                pd = usage.get("prompt_tokens_details") or {}
                self.cached_tokens += int(pd.get("cached_tokens") or 0)

    def fail(self) -> None:
        with self.lock:
            self.failures += 1

    @property
    def cost_cny(self) -> float:
        miss = max(self.prompt_tokens - self.cached_tokens, 0)
        return (
            miss / 1e6 * PRICE_IN_PER_M_CNY
            + self.cached_tokens / 1e6 * PRICE_IN_PER_M_CNY * CACHE_HIT_FACTOR
            + self.completion_tokens / 1e6 * PRICE_OUT_PER_M_CNY
        )

    def summary(self) -> dict:
        return {
            "requests": self.requests,
            "failures": self.failures,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
            "elapsed_s": round(self.elapsed_s, 1),
            "cost_cny": round(self.cost_cny, 4),
        }


_accounts: dict[str, UsageAccount] = {}
_accounts_lock = threading.Lock()


def account(name: str) -> UsageAccount:
    with _accounts_lock:
        acc = _accounts.get(name)
        if acc is None:
            acc = _accounts[name] = UsageAccount(name=name)
        return acc


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    thinking: str = "disabled",
    tools: list[dict] | None = None,
    max_tokens: int = 4096,
    temperature: float | None = None,
    acct: UsageAccount | None = None,
    timeout: float = 300.0,
    retries: int = 4,
) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise EvalError("DEEPSEEK_API_KEY is not set (.env 或环境变量)")
    # 用产品客户端构造请求体，保证消息/工具规范化（_normalize_messages_for_openai +
    # _to_openai_tool + thinking/temperature）与 agent 一致，避免评测打的是一套、
    # 生产跑的却是另一套请求（缩小「测非所跑」偏差）。
    from model.deepseek import DeepSeekModelClient

    body: dict = DeepSeekModelClient(
        api_key=key,
        base_url=BASE_URL,
        model=model or MODEL_ID,
        thinking=thinking,
    )._build_body(messages, tools or [], stream=False)
    body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    last_err: Exception | None = None
    data: dict | None = None
    elapsed = 0.0
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(2**attempt, 30))
        try:
            t0 = time.monotonic()
            req = urllib.request.Request(
                f"{BASE_URL}/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            elapsed = time.monotonic() - t0
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            last_err = EvalError(f"HTTP {e.code}: {detail[:400]}")
            if e.code not in (429, 500, 502, 503, 504):
                if acct:
                    acct.fail()
                raise last_err from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = EvalError(f"network: {e}")
    if data is None:
        if acct:
            acct.fail()
        raise last_err or EvalError("request failed")

    choice = data["choices"][0]
    msg = choice.get("message") or {}
    usage = data.get("usage")
    if acct:
        acct.add(usage, elapsed)

    tool_calls: list[dict] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments")
        if isinstance(raw_args, str):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"__unparsed__": raw_args}
        else:
            args = raw_args if isinstance(raw_args, dict) else {}
        tool_calls.append({"name": fn.get("name"), "arguments": args})

    cdet = (usage or {}).get("completion_tokens_details") or {}
    return {
        "content": msg.get("content"),
        "tool_calls": tool_calls,
        "finish_reason": choice.get("finish_reason"),
        "reasoning_chars": len(msg.get("reasoning_content") or ""),
        "truncated": choice.get("finish_reason") == "length",
    }


def ensure_stdout_utf8() -> None:
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
