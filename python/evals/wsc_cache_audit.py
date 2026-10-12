"""Offline cache accounting and provider-body comparison; never changes requests.

Exact message equality is a conservative structural observation, not a token
count or proof of provider caching. Request envelopes are reported separately.
No source content, credentials, or tool arguments are emitted in the audit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(previous, current):
    key = "messages" if "messages" in previous and "messages" in current else "input"
    left, right = previous.get(key), current.get(key)
    if not isinstance(left, list) or not isinstance(right, list):
        return {"comparison_available": False}
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    envelope_changes = sorted(k for k in previous.keys() | current.keys()
                              if k != key and (k not in previous or k not in current
                                              or previous[k] != current[k]))
    return {"comparison_available": True, "common_exact_messages": common,
            "previous_messages": len(left), "current_messages": len(right),
            "message_relation": "append" if common == len(left) and len(right) >= len(left)
                                else "rewrite_or_remove",
            "changed_envelope_fields": envelope_changes}


def usage_sample(raw):
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    cached = raw.get("prompt_cache_hit_tokens")
    if cached is None:
        details = raw.get("prompt_tokens_details")
        cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if type(prompt) is not int or type(cached) is not int or not 0 <= cached <= prompt:
        return None
    return {"input_tokens": prompt, "cached_tokens": cached,
            "hit_rate": cached / prompt if prompt else None}


def phase(body):
    names = [tool.get("name") or tool.get("function", {}).get("name")
             for tool in body.get("tools", [])]
    return "handoff" if "HandoffSource" in names else "continuation"


def audit(report):
    calls, previous_by_phase, totals = [], {}, {}
    previous = None
    for index, trace in enumerate(report.get("requests", [])):
        wire = trace["wire"]
        body = wire["request"]
        group = phase(body)
        sample = usage_sample(wire["response"].get("usage"))
        entry = {"index": index, "phase": group, "usage": sample}
        if previous is not None:
            entry["previous_call_structure"] = compare(previous, body)
        if group in previous_by_phase:
            entry["same_phase_structure"] = compare(previous_by_phase[group], body)
        previous, previous_by_phase[group] = body, body
        calls.append(entry)
        for name in (group, "all"):
            total = totals.setdefault(name, {"calls": 0, "usage_observed_calls": 0,
                                           "input_tokens": 0, "cached_tokens": 0})
            total["calls"] += 1
            if sample is not None:
                total["usage_observed_calls"] += 1
                total["input_tokens"] += sample["input_tokens"]
                total["cached_tokens"] += sample["cached_tokens"]
    for total in totals.values():
        total["observed_token_weighted_hit_rate"] = (
            total["cached_tokens"] / total["input_tokens"] if total["input_tokens"] else None)
    return {"scope": report.get("scope"), "arm": report.get("arm"),
            "totals": totals, "calls": calls,
            "limits": ["No provider token-prefix or TTL attribution from JSON equality.",
                       "No live-session cache guarantee from synthetic task captures.",
                       "Missing usage is unknown, not a zero-hit request."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = [{"source_report": str(path), **audit(json.loads(path.read_text(encoding="utf-8")))}
              for path in args.reports]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
