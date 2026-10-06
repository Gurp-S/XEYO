"""Provider end facts; no automatic continuation or request replay."""
from engine.model_events import ModelProtocolError


def validate_stream_end(state):
    reason = state.get("finish_reason")
    if reason in {"length", "content_filter", "max_tokens", "refusal"}:
        raise ModelProtocolError(f"model stream ended with finish_reason={reason}")
    # Either marker is sufficient for compatible gateways. An entirely empty
    # stream keeps the runtime's existing bounded empty-response retry policy.
    if state.get("has_output") and not (state.get("done") or reason):
        raise ModelProtocolError("model stream ended without a completion marker")
