"""Process-owned journal lock; a crashed process releases it through the OS."""
import os
import time
from contextlib import contextmanager


@contextmanager
def action_file_lock(path, *, timeout=5.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path.with_suffix(".lock")), os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        # Byte-range locks may extend past EOF. Writing an initialization byte
        # would race another process already holding that byte on Windows.
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("action journal lock unavailable")
                time.sleep(.01)
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
