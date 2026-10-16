"""Coalesce retention scans outside the tool-result response path."""
import contextvars
import logging
import threading
import time

_lock = threading.Lock()
_last = {}
_running = {}
INTERVAL_SECONDS = 300.0


def schedule(root, cleanup, *, force=False):
    root = root.resolve()
    key = str(root)
    with _lock:
        now = time.monotonic()
        if key in _running:
            return _running[key]
        if not force and now - _last.get(key, float("-inf")) < INTERVAL_SECONDS:
            return None
        # Expired roots need no persistent bookkeeping.
        for old in list(_last):
            if now - _last[old] >= INTERVAL_SECONDS:
                del _last[old]
        _last[key] = now
        context = contextvars.copy_context()
        def run():
            try:
                context.run(cleanup, root)
            except Exception:
                logging.getLogger(__name__).warning("spill retention scan failed", exc_info=True)
            finally:
                with _lock:
                    _running.pop(key, None)
        worker = threading.Thread(target=run, name="xeyo-spill-gc", daemon=True)
        _running[key] = worker
        try:
            worker.start()
        except BaseException:
            _running.pop(key, None)
            _last.pop(key, None)
            raise
        return worker
