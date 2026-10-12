"""Runtime validity is independent of equality to a golden."""
import json


def failures(traces):
    errors = []
    for name, text in traces.items():
        if text.lstrip().startswith("<raised "):
            errors.append({"name": name, "reason": text.strip()})
        elif name.startswith("loop/"):
            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                errors.append({"name": name, "reason": "invalid_loop_payload"})
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list) or not isinstance(payload.get("final"), str):
                errors.append({"name": name, "reason": "invalid_loop_contract"})
            elif "Final" not in payload["events"]:
                errors.append({"name": name, "reason": "missing_final_event"})
    return errors


def apply_verdict(verdict, traces):
    from engine.harness_policy import enabled
    if enabled("XEYO_HARNESS_HEALTH"):
        errors = failures(traces)
        verdict.deterministic["healthy"] = not errors
        verdict.deterministic["health_failures"] = errors
        if errors:
            verdict.overall = "fail"
            verdict.summary_lines.insert(0, f"trace health: {len(errors)} invalid scenario(s)")
    return verdict
