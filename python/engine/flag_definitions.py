"""One parser/default source for execution facts and harness rollout domains."""
import os

FLAGS = {
    "XEYO_EXECUTION_FACT_CONTRACTS": (True, "execution receipt and live permission facts"),
    "XEYO_TOOL_COMPLETENESS_FACTS": (True, "truncated output observation"),
    "XEYO_SCRATCH_WRITABLE": (True, "narrow scratch write permission"),
    "XEYO_ENV_FACTS_EXTRA": (True, "browser absence observation"),
    "XEYO_ENV_FACTS_SYNTAX": (False, "shell syntax observation"),
    "XEYO_TOOL_DESC_FACTS": (False, "structure capability in tool description"),
    "XEYO_READ_STRUCTURE_HINT": (True, "structure capability on window reads"),
    "XEYO_GREP_PAGINATION_FACTS": (True, "pagination total and next offset"),
    "XEYO_GREP_SYMBOL_RANGES": (True, "symbol start and end lines"),
    "XEYO_BASH_ERROR_ORIGIN": (True, "failed command origin observation"),
}


def enabled(name):
    default = FLAGS[name][0]
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    # Preserve legacy distinct semantics for default-off vs default-on predicates.
    return raw not in {"0", "false", "off", "no"} if default else raw in {"1", "true", "on", "yes"}


def snapshot(names=None):
    from engine.harness_policy import DEFAULTS, enabled as rollout
    definitions = {**FLAGS, **{name: (default, "harness rollout domain") for name, default in DEFAULTS.items()}}
    output = []
    for name in sorted(set(names) if names is not None else definitions):
        if name not in definitions:
            output.append({"name": name, "status": "unknown"})
            continue
        default, meaning = definitions[name]
        output.append({"name": name, "default": default,
                       "effective": enabled(name) if name in FLAGS else rollout(name),
                       "raw": os.environ.get(name), "meaning": meaning,
                       "value_source": "process_environment" if name in os.environ else "code_default",
                       "upstream_origin": "unknown"})
    return output
