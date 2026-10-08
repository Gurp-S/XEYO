"""Compare saved provider receipts to a separately inspected reference encoder.

No API key, network calls or production mutation. The external encoder and
tokenizer are explicitly selected and hashed; matches do not prove identity
with the vendor's live API template.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def run(tokenizer_path, encoder_path, wire_paths):
    from tokenizers import Tokenizer
    tokenizer_path, encoder_path = Path(tokenizer_path), Path(encoder_path)
    spec = importlib.util.spec_from_file_location("reference_encoding", encoder_path)
    encoder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encoder)
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    records = []
    for path in map(Path, wire_paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        captures = payload if isinstance(payload, list) else payload["requests"]
        for index, capture in enumerate(captures):
            wire = capture.get("wire", capture)
            body = wire["request"]
            messages = deepcopy(body["messages"])
            record = {"source": str(path.resolve()), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "request_index": index, "model": body["model"],
                      "provider_prompt_tokens": wire["response"]["usage"]["prompt_tokens"]}
            if any(not isinstance(message.get("content", ""), (str, type(None))) for message in messages):
                records.append({**record, "status": "unsupported_nontext_input"})
                continue
            if body.get("tools"):
                if messages[0]["role"] != "system":
                    messages.insert(0, {"role": "system", "content": ""})
                messages[0]["tools"] = body["tools"]
            mode = "thinking" if body.get("thinking", {}).get("type") == "enabled" else "chat"
            text = encoder.encode_messages(messages, thinking_mode=mode, reasoning_effort=body.get("reasoning_effort"))
            count = len(tokenizer.encode(text, add_special_tokens=False).ids)
            records.append({**record, "status": "counted", "reference_count": count,
                "difference": count - record["provider_prompt_tokens"],
                "relative_error": abs(count-record["provider_prompt_tokens"])/max(1,record["provider_prompt_tokens"])})
    counted = [row for row in records if row["status"] == "counted"]
    return {"scope": "offline saved-request comparison; reference count is not a live provider exact count",
        "tokenizer_sha256": hashlib.sha256(tokenizer_path.read_bytes()).hexdigest(),
        "encoder_sha256": hashlib.sha256(encoder_path.read_bytes()).hexdigest(),
        "counted": len(counted), "unsupported": len(records)-len(counted),
        "max_abs_difference": max((abs(row["difference"]) for row in counted), default=None),
        "max_relative_error": max((row["relative_error"] for row in counted), default=None), "requests": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--encoder", required=True)
    parser.add_argument("--dependency-dir")
    parser.add_argument("--output", required=True)
    parser.add_argument("wires", nargs="+")
    args = parser.parse_args()
    if args.dependency_dir:
        sys.path.insert(0, str(Path(args.dependency_dir).resolve()))
    result = run(args.tokenizer, args.encoder, args.wires)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "requests"}))
