"""Optional JSON command transport; no embedded model, prompt, retry or scheduler."""
from pathlib import Path
import json
import tempfile
import os

from .contracts import encode, require
from .generation_boundary import decode_response, run_command


from .selection_transport import string_list,selection_from_json


class JsonCommandGenerator:
    """stdin: public material JSON; stdout: {selection, usage}.

    argv is an explicitly supplied local program, run without a shell. Its model
    credentials, prompt and usage reporting remain the caller's responsibility.
    stdout/stderr are temporary files, never unbounded in-memory pipes or model
    error messages. All failures are recorded by WSC.generate as real attempts.
    """
    def __init__(self, argv, *, cwd=None, timeout=120, max_output_bytes=1048576,max_stderr_bytes=65536,legacy=None):
        self.argv = string_list(argv)
        require(bool(self.argv) and timeout > 0 and max_output_bytes > 0, "generation_command_invalid")
        self.cwd, self.timeout, self.max_output_bytes = cwd, timeout, max_output_bytes
        require(legacy is None or type(legacy) is bool,'generation_command_invalid')
        self.legacy=os.name!='nt' if legacy is None else legacy
        self.max_stderr_bytes=max_stderr_bytes;self.cleanup=None

    def __call__(self, material):
        if not self.legacy:
            from .bounded_generation import BoundedJsonCommandGenerator
            bounded=BoundedJsonCommandGenerator(self.argv,cwd=self.cwd,timeout=self.timeout,
                max_output_bytes=self.max_output_bytes,max_stderr_bytes=self.max_stderr_bytes)
            try:return bounded(material)
            finally:self.cleanup=bounded.cleanup
        with tempfile.TemporaryDirectory(prefix="wsc-generation-") as temp:
            root = Path(temp)
            source, output, error = root / "input.json", root / "output.json", root / "error.txt"
            source.write_text(encode(material), encoding="utf-8")
            with source.open("rb") as stdin, output.open("wb") as stdout, error.open("wb") as stderr:
                outcome = run_command(self.argv, cwd=self.cwd, stdin=stdin, stdout=stdout,
                                         stderr=stderr, shell=False, timeout=self.timeout, check=False)
            require(outcome.returncode == 0, "generation_command_failed")
            require(output.stat().st_size <= self.max_output_bytes, "generation_output_budget_exhausted")
            value = json.loads(output.read_text(encoding="utf-8"))
            return decode_response(value, selection_from_json)
