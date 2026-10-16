"""Per-attempt provider state; HTTP connection pools remain transport-owned."""
import copy


def fork_runtime(runtime):
    if runtime is None:
        return None
    fork = copy.copy(runtime)
    client = getattr(runtime, "model_client", None)
    if client is not None:
        factory = getattr(client, "fork_for_agent", None)
        child = factory() if callable(factory) else copy.copy(client)
        if child is client:
            raise RuntimeError("model_client_isolation_unavailable")
        if not callable(factory):
            # Built-in clients keep request results on their instance and share
            # only the external transport pool. Mutable configuration is private.
            for key, value in getattr(client, "__dict__", {}).items():
                if isinstance(value, (dict, list, set, bytearray)):
                    setattr(child, key, copy.deepcopy(value))
        for key, value in (("last_usage", None), ("last_context_tokens", None),
                           ("_usage_recorded_this_stream", False), ("_meta_request_id", "")):
            if hasattr(child, key):
                setattr(child, key, value)
        fork.model_client = child
    return fork
