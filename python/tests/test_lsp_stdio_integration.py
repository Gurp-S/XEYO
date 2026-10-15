"""Real subprocess/stdio framing; fake server, no network or installed LSP needed."""
import sys
from lsp.client import LspClient
from lsp.servers import ServerSpec


def test_stdio_roundtrip_observes_document_updates(tmp_path):
    script = tmp_path / 'server.py'
    script.write_text('''import sys, json
text = ""
while True:
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            sys.exit(0)
        if line in (b"\\r\\n", b"\\n"):
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1])
    message = json.loads(sys.stdin.buffer.read(length))
    method = message.get("method")
    if method == "exit":
        break
    if method == "textDocument/didOpen":
        text = message["params"]["textDocument"]["text"]
    if method == "textDocument/didChange":
        text = message["params"]["contentChanges"][0]["text"]
    if "id" in message:
        result = {"capabilities": {"textDocumentSync": 1}} if method == "initialize" else {"contents": text}
        body = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode()
        sys.stdout.buffer.write(b"Content-Length: %d\\r\\n\\r\\n" % len(body) + body)
        sys.stdout.buffer.flush()
''')
    p = tmp_path / 'a.py'
    p.write_text('before')
    c = LspClient(ServerSpec('python', (sys.executable, '-u', str(script))), tmp_path, timeout=2)
    try:
        c.start()
        uri = c.ensure_open(p, 'python')
        assert c.hover(uri, 0, 0) == {'contents': 'before'}
        p.write_text('after')
        c.ensure_open(p, 'python')
        assert c.hover(uri, 0, 0) == {'contents': 'after'}
    finally:
        proc = c._proc
        c.stop()
        if c._reader is not None:
            c._reader.join(2)
        assert proc is None or proc.poll() is not None
