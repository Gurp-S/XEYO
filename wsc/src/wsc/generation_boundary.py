"""Command failure and response boundaries for the optional JSON transport."""
from dataclasses import fields
import subprocess

from .contracts import Generated, Usage, WSCError, require


def run_command(argv, **kwargs):
    try:
        return subprocess.run(argv, **kwargs)
    except subprocess.TimeoutExpired:
        # The subprocess API has killed and reaped this process. Its argv and
        # captured data are not part of the public error or an accounting receipt.
        raise WSCError("generation_command_timeout") from None


def decode_response(value, parse_selection):
    require(isinstance(value, dict) and set(value) <= {"selection", "usage"}
            and "selection" in value, "generation_response_invalid")
    raw_usage = value.get("usage", {})
    require(isinstance(raw_usage, dict) and set(raw_usage) <= {f.name for f in fields(Usage)},
            "generation_usage_invalid")
    usage = Usage(**raw_usage)
    try:
        selected = parse_selection(value["selection"])
    except (ValueError, TypeError) as exc:
        # Paid work and selection validity are independent facts. WSC.generate
        # records this receipt on the failed attempt; it does not retry.
        exc.usage = usage
        raise
    return Generated(selected, usage)
