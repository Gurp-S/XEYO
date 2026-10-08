"""Per-request admission and accounting at the verified Flash peak CNY price.

No retries. Unknown billed outcomes reserve their entire admitted upper bound.
The byte bound is deliberately much larger than normal text token counts.
"""
import json


class Budget:
    def __init__(self, per_call=0.5, total=0.4):
        self.per_call, self.total = per_call, total
        self.spent_upper = 0.0
        self.entries = []

    def admit(self, body, max_output):
        byte_count = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
        upper = ((byte_count + 8192) * 2 + max_output * 8) / 1_000_000
        if upper > self.per_call or self.spent_upper + upper > self.total:
            raise ValueError("evaluation_budget_exceeded")
        entry = {"request_bytes": byte_count, "output_limit": max_output,
                 "admitted_cny_upper": upper, "usage_observed": False}
        self.entries.append(entry)
        self.spent_upper += upper
        return entry

    def settle(self, entry, usage):
        if not usage or "prompt_tokens" not in usage or "completion_tokens" not in usage:
            return
        prompt = int(usage["prompt_tokens"])
        completion = int(usage["completion_tokens"])
        cached = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        cost = (max(0, prompt-cached) * 2 + cached * 0.04 + completion * 8) / 1_000_000
        self.spent_upper += cost - entry["admitted_cny_upper"]
        entry.update(usage_observed=True, prompt_tokens=prompt, completion_tokens=completion,
                     cache_hit_tokens=cached, peak_price_cny=cost, off_peak_price_cny=cost/2)
        if cost > entry["admitted_cny_upper"] or cost > self.per_call:
            raise ValueError("evaluation_cost_bound_violation")
