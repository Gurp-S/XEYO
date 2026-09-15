# -*- coding: utf-8 -*-
import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, r"D:\lea\XenYon code\TerminalBench\zero")
sys.stdout.reconfigure(encoding="utf-8")
import p6_run as R
R.load_env()
key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
print("key len:", len(key))

TOOLS = [{"type": "function", "function": {
    "name": "Bash", "description": "Run a shell command",
    "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]

def probe(name, body):
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            j = json.loads(r.read().decode("utf-8"))
        ch = (j.get("choices") or [{}])[0].get("message") or {}
        rc = ch.get("reasoning_content") or ""
        u = j.get("usage") or {}
        print(f"[{name}] 200 | reasoning_chars={len(rc)} | tool_calls={len(ch.get('tool_calls') or [])} | usage={u.get('completion_tokens')}")
    except urllib.error.HTTPError as e:
        print(f"[{name}] HTTP {e.code}: {e.read().decode('utf-8','replace')[:240]}")
    except Exception as e:
        print(f"[{name}] ERR {type(e).__name__}: {e}")

msgs = [{"role": "user", "content": "Run `echo hi` with the Bash tool."}]
for effort in ("low", "high", "max"):
    probe(f"enabled/{effort}", {"model": "deepseek-flash", "messages": msgs, "tools": TOOLS,
                                "thinking": {"type": "enabled"}, "reasoning_effort": effort, "stream": False})
probe("baseline(no field)", {"model": "deepseek-flash", "messages": msgs, "tools": TOOLS, "stream": False})
probe("disabled", {"model": "deepseek-flash", "messages": msgs, "tools": TOOLS,
                   "thinking": {"type": "disabled"}, "stream": False})
