"""Wait for one transcript's submitted generation, without blocking asyncio."""
import time


def flush_path(path, timeout=5.0):
    from importlib import import_module
    writer = import_module("session.record_transcript")

    key = str(path)
    writer._ensure_writer()
    deadline = time.monotonic() + timeout
    with writer._cv:
        through = writer._submitted_seq
        def selected(item):
            return item[1] == key and item[0] <= through
        retry = [item for item in writer._failed if selected(item)]
        if retry:
            writer._failed[:] = [item for item in writer._failed if not selected(item)]
            writer._pending[:0] = retry
            writer._cv.notify_all()
        while any(selected(item) for item in writer._pending + writer._inflight):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            writer._cv.wait(remaining)
        return not any(selected(item) for item in writer._failed)
