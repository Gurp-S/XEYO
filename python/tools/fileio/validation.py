"""Pure candidate checks; WIP persistence and validation success are separate facts."""
from pathlib import Path
import json
import sys


def extend_schema(schema):
    from engine.harness_policy import enabled
    if enabled("XEYO_HARNESS_WRITES"):
        schema["input_schema"]["properties"]["validation_policy"] = {
            "type": "string", "enum": ["draft", "strict"],
            "description": "draft persists candidate with check facts; strict requires a passed supported check."}
    return schema


def check_content(path, content):
    suffix = Path(path).suffix.lower()
    kind = {".py": "python_compile", ".json": "json_parse", ".ipynb": "json_parse"}.get(suffix)
    if not kind:
        return {"status": "unavailable", "kind": "content", "reason": "unsupported_language"}
    if len(content) > 2_000_000:
        return {"status": "skipped", "kind": kind, "reason": "size_limit"}
    result = {"status": "passed", "kind": kind, "runtime": sys.version.split()[0]}
    try:
        if kind == "python_compile":
            compile(content, str(path), "exec", dont_inherit=True)
        else:
            json.loads(content)
    except (SyntaxError, json.JSONDecodeError) as exc:
        result.update(status="failed", line=exc.lineno or 0,
                      column=getattr(exc, "offset", None) or getattr(exc, "colno", 0),
                      detail=exc.msg)
    return result
