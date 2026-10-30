"""Opt-in JSON command transport with live stdout and stderr byte budgets."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import math

from .contracts import WSCError, encode, require
from .selection_transport import selection_from_json, string_list
from .generation_boundary import decode_response
from .command_process_tree import ProcessOwner,resume_attached_root


_READ_CHUNK_BYTES = 64 * 1024
_POLL_SECONDS = 0.01

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _peek_named_pipe = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
    _peek_named_pipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD),
                                 ctypes.POINTER(wintypes.DWORD),
                                 ctypes.POINTER(wintypes.DWORD)]
    _peek_named_pipe.restype = wintypes.BOOL


class _PipeReader:
    """Read a bounded chunk without blocking the other stream's drain."""
    def __init__(self, stream):
        self.stream = stream
        self.selector = None
        if os.name == "nt":
            self.handle = msvcrt.get_osfhandle(stream.fileno())
        else:
            import selectors
            self.selector = selectors.DefaultSelector()
            self.selector.register(stream, selectors.EVENT_READ)

    def read(self, timeout, max_bytes):
        max_bytes = max(1, min(max_bytes, _READ_CHUNK_BYTES))
        if os.name == "nt":
            deadline = time.monotonic() + max(timeout, 0)
            while True:
                available = wintypes.DWORD()
                ok = _peek_named_pipe(self.handle, None, 0, None,
                                      ctypes.byref(available), None)
                if not ok:
                    error = ctypes.get_last_error()
                    if error in (109, 232, 233):  # broken or closing pipe
                        return b"", True
                    raise OSError(error, ctypes.FormatError(error))
                if available.value:
                    data = os.read(self.stream.fileno(), min(available.value, max_bytes))
                    return data, not data
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, False
                time.sleep(min(_POLL_SECONDS, remaining))

        if not self.selector.select(max(timeout, 0)):
            return None, False
        data = os.read(self.stream.fileno(), max_bytes)
        return data, not data

    def close(self):
        if self.selector is not None:
            self.selector.close()


def _kill_and_reap(process):
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            if process.poll() is None:
                raise
    process.wait()


def _probe_size(limit, total):
    """Read no more than the remaining budget plus one byte proving overflow."""
    remaining = limit - total
    if remaining >= _READ_CHUNK_BYTES:
        return _READ_CHUNK_BYTES
    return max(1, int(remaining) + 1)


def _run_bounded(argv, *, cwd, stdin, stdout_path, stderr_path, timeout,
                 max_output_bytes, max_stderr_bytes, on_cleanup):
    require(os.name=='nt','generation_tree_containment_unavailable')
    owner=ProcessOwner()
    with stdout_path.open("wb") as output, stderr_path.open("wb") as errors:
        try:
            process = subprocess.Popen(argv, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False,creationflags=4)
        except BaseException:
            owner.close();raise
        stdout_reader = stderr_reader = None
        try:
            owner.attach(process)
            resume_attached_root(process,owner)
            stdout_reader = _PipeReader(process.stdout)
            stderr_reader = _PipeReader(process.stderr)
            deadline = time.monotonic() + timeout
            stdout_total = stderr_total = 0
            stdout_eof = stderr_eof = False

            while not (stdout_eof and stderr_eof):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_and_reap(process)
                    raise WSCError("generation_command_timeout")

                progressed = False
                if not stdout_eof:
                    chunk, eof = stdout_reader.read(0, _probe_size(max_output_bytes, stdout_total))
                    if chunk:
                        if stdout_total + len(chunk) > max_output_bytes:
                            _kill_and_reap(process)
                            raise WSCError("generation_output_budget_exhausted")
                        output.write(chunk)
                        stdout_total += len(chunk)
                        progressed = True
                    if eof:
                        stdout_eof = True
                        progressed = True

                if not stderr_eof:
                    chunk, eof = stderr_reader.read(0, _probe_size(max_stderr_bytes, stderr_total))
                    if chunk:
                        if stderr_total + len(chunk) > max_stderr_bytes:
                            _kill_and_reap(process)
                            raise WSCError("generation_stderr_budget_exhausted")
                        errors.write(chunk)
                        stderr_total += len(chunk)
                        progressed = True
                    if eof:
                        stderr_eof = True
                        progressed = True

                if not progressed:
                    time.sleep(min(_POLL_SECONDS, remaining))

            if process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _kill_and_reap(process)
                    raise WSCError("generation_command_timeout")
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    _kill_and_reap(process)
                    raise WSCError("generation_command_timeout") from None
            return process.wait()
        finally:
            try:
                try:on_cleanup(owner.close())
                finally:_kill_and_reap(process)
            finally:
                if stdout_reader is not None:stdout_reader.close()
                if stderr_reader is not None:stderr_reader.close()
                process.stdout.close();process.stderr.close()


class BoundedJsonCommandGenerator:
    """Run argv and stop the direct child when either output byte cap is exceeded.

    stdin is public material JSON; stdout is ``{selection, usage}``. Both output
    streams are byte-limited and stored in temporary files. stderr is never
    included in public errors. Windows descendants are contained in a private
    Job before the root is resumed; other platforms fail admission explicitly.
    """
    def __init__(self, argv, *, cwd=None, timeout=120, max_output_bytes=1048576,
                 max_stderr_bytes=65536):
        self.argv = string_list(argv)
        require(bool(self.argv) and type(timeout) in (int,float) and math.isfinite(timeout) and timeout > 0
                and type(max_output_bytes) is int and max_output_bytes > 0,
                "generation_command_invalid")
        require(isinstance(max_stderr_bytes, int) and not isinstance(max_stderr_bytes, bool)
                and max_stderr_bytes > 0, "generation_command_invalid")
        self.cwd, self.timeout, self.max_output_bytes = cwd, timeout, max_output_bytes
        self.max_stderr_bytes = max_stderr_bytes
        self.cleanup=None

    def __call__(self, material):
        with tempfile.TemporaryDirectory(prefix="wsc-generation-") as temp:
            root = Path(temp)
            source, output, error = root / "input.json", root / "output.json", root / "error.txt"
            source.write_text(encode(material), encoding="utf-8")
            with source.open("rb") as stdin:
                try:returncode = _run_bounded(self.argv, cwd=self.cwd, stdin=stdin,
                                          stdout_path=output, stderr_path=error,
                                          timeout=self.timeout,
                                          max_output_bytes=self.max_output_bytes,
                                          max_stderr_bytes=self.max_stderr_bytes,
                                          on_cleanup=lambda receipt:setattr(self,'cleanup',receipt))
                except OSError:raise WSCError('generation_command_unavailable') from None
                except RuntimeError:raise WSCError('generation_process_containment_failed') from None
            require(returncode == 0, "generation_command_failed")
            value = json.loads(output.read_text(encoding="utf-8"))
            return decode_response(value, selection_from_json)
