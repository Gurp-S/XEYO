"""Run with a clean wheel installation: python -I /path/to/check_engine_install.py.

No source path is added. All state and fake tool effects stay in a temporary
workspace. Model calls are local; the check makes no provider/network requests.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.abc
import importlib.metadata
import importlib.resources
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile


class ProductImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"server", "cli", "fastapi", "uvicorn", "typer", "rich"}:
            raise ModuleNotFoundError(f"Product import blocked by wheel smoke: {fullname}", name=fullname)
        return None


async def exercise(workspace: Path) -> dict:
    from xeyo import build_default_engine
    from engine.runtime_identity import snapshot
    from engine.process_ledger import _pid_alive
    from tokenizers import Tokenizer

    assert snapshot()["engine_version"] == importlib.metadata.version("xeyo")
    assert _pid_alive(os.getpid()) and not _pid_alive(-1)
    tokenizer = importlib.resources.files("model.reference_v41").joinpath("tokenizer.json")
    assert Tokenizer.from_file(str(tokenizer)).encode("wheel smoke").ids
    for module in ("coord", "lsp", "sidecar"):
        assert importlib.util.find_spec(module) is not None, module
    results = {}
    for sid, prompt in (("plain", "hello"), ("tool", "echo:wheel")):
        engine = build_default_engine(cwd=str(workspace), model_backend="fake", session_id=sid,
                                      runtime_checkpoint=True, runtime_verify=True)
        events = [e async for e in engine.submit(prompt)]
        final = next(e.text for e in events if e.type == "final")
        assert events[-1].type == "result" and not events[-1].is_error
        assert engine.runtime_snapshot()["verification"]["checked"]
        assert engine.load_runtime_checkpoint() is not None
        assert engine.runtime_recovery()["checked"]
        if sid == "plain":
            assert final == "ok: hello"
        else:
            assert any(e.type == "tool_call" and e.name == "echo" for e in events)
            assert final.endswith("\nwheel"), final
        results[sid] = {"final_ok": True, "events": [e.type for e in events]}
    # Exercise a real Git repository with transport imports actively blocked.
    from tools.git_tool import GitTool
    from tools.job_tools import JobListTool
    from tools.host_services import ToolHostServices
    from engine.abort import AbortController
    subprocess.run(["git", "init", "-q", str(workspace)], check=True, capture_output=True)
    git = await GitTool(cwd=str(workspace)).execute({"action": "status"}, AbortController())
    assert not git.is_error and "branch:" in git.content, git.content
    class Jobs:
        def snapshot_list(self, sid):
            return [{"job_id":"embedded-job", "kind":"bash", "status":"running", "label":"contract"}]
    jobs = Jobs()
    output = await JobListTool(host_services=ToolHostServices(jobs=lambda: jobs)).execute({}, AbortController())
    assert "embedded-job" in output.content and not output.is_error
    import engine, tools
    violations = []
    for file in [*Path(engine.__file__).parent.rglob("*.py"), *Path(tools.__file__).parent.rglob("*.py")]:
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8-sig"))):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(name.split(".")[0] in {"server", "cli", "fastapi", "uvicorn"} for name in names):
                violations.append(f"{file.name}:{node.lineno}")
    assert not violations, violations
    assert not any(name.split(".")[0] in {"server", "cli", "fastapi", "uvicorn", "typer", "rich"} for name in sys.modules)
    return {"ok": True, "installed_engine": str(engine.__file__),
            "version": importlib.metadata.version("xeyo"), "cases": results,
            "engine_transport_imports": violations, "tool_host_contract": True,
            "git_without_server": True, "product_modules_loaded": False}


def main() -> None:
    sys.meta_path.insert(0, ProductImportBlocker())
    with tempfile.TemporaryDirectory(prefix="xeyo-engine-wheel-") as temporary:
        workspace = Path(temporary)
        for key, name in {"XEYO_HOME": "home", "XEYO_CWD": "workspace",
                          "XEYO_SESSIONS_DIR": "sessions", "XEYO_USAGE_DIR": "usage",
                          "XEYO_SNAPSHOTS_DIR": "snapshots", "XEYO_SPILL_DIR": "spill",
                          "XEYO_JOURNAL_DIR": "journal", "XEYO_METRICS_DIR": "metrics"}.items():
            directory = workspace / name
            directory.mkdir()
            os.environ[key] = str(directory)
        from engine.env_switches import isolation_pins
        for key, value in isolation_pins():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        original_cwd = Path.cwd()
        try:
            os.chdir(workspace / "workspace")
            print(json.dumps(asyncio.run(exercise(Path.cwd())), ensure_ascii=False))
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    main()
