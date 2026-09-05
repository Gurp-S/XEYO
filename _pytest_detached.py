"""Detach pytest from the console so phantom Ctrl+C events cannot kill it.

The bat runner invokes: ``py -3.11 _pytest_detached.py <pytest args...>``
This wrapper spawns ``py -3.11 -m pytest <args>`` as a DETACHED_PROCESS in its
own process group (no console attachment -> immune to CTRL_C_EVENT injected
into any console window), waits for it to finish (surviving its own possible
interrupts), then writes the completion sentinel for the polling launcher.
"""

from __future__ import annotations

import subprocess
import sys
import time

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
SENTINEL = r"..\logs\pytest-p0b-tail.done"


def _spawn(args: list[str]) -> subprocess.Popen:
    """Spawn pytest fully outside any console signal reach and kill-on-close jobs.

    - DETACHED_PROCESS + own process group → console Ctrl+C events cannot reach it;
    - CREATE_BREAKAWAY_FROM_JOB → escapes a kill-on-close Job inherited from the
      launching tree (falls back silently if the job forbids breakaway);
    - XEYO_DETACH_LOG (optional) → child stdout/stderr go to that file explicitly,
      immune to handle-inheritance quirks of the caller's redirection.
    """
    import os

    common = dict(
        cwd=os_cwd(),
        stdin=subprocess.DEVNULL,
    )
    log_path = os.environ.get("XEYO_DETACH_LOG", "").strip()
    if log_path:
        fh = open(log_path, "w", encoding="utf-8", buffering=1)
        common["stdout"] = fh
        common["stderr"] = subprocess.STDOUT
    else:
        common["stdout"] = sys.stdout
        common["stderr"] = sys.stderr
    try:
        return subprocess.Popen(
            args,
            creationflags=DETACHED_PROCESS
            | CREATE_NEW_PROCESS_GROUP
            | CREATE_BREAKAWAY_FROM_JOB,
            **common,
        )
    except OSError:
        return subprocess.Popen(
            args,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            **common,
        )


def main() -> int:
    import os

    args = [sys.executable, "-m", "pytest", *sys.argv[1:]]
    log_path = os.environ.get("XEYO_DETACH_LOG", "").strip()
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[wrapper] spawning: {args!r}\n")
    proc = _spawn(args)
    try:
        with open(SENTINEL, "w", encoding="ascii") as fh:
            fh.write(f"started pid={proc.pid}")
    except OSError:
        pass
    try:
        while proc.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        # The wrapper's console got interrupted; the detached child keeps going.
        while proc.poll() is None:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                pass
    code = proc.returncode
    try:
        with open(SENTINEL, "w", encoding="ascii") as fh:
            fh.write(f"done exit={code}")
    except OSError:
        pass
    return code if isinstance(code, int) else 0


def os_cwd() -> str:
    import os

    return os.getcwd()


if __name__ == "__main__":
    sys.exit(main())
