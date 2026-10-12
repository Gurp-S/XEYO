"""Live process identity, not a claim that disk HEAD identifies loaded code."""
from datetime import datetime, timezone
import os
import uuid

_INSTANCE = uuid.uuid4().hex
_INITIALIZED = datetime.now(timezone.utc).isoformat()


def snapshot():
    from server.portfile import engine_version
    return {"instance_id": _INSTANCE, "pid": os.getpid(),
            "identity_initialized_at": _INITIALIZED, "engine_version": engine_version(),
            "loaded_source_identity": "unknown",
            "scope": "live process; identity initialization is not process start"}
