import os, sys
sys.path.insert(0, "python")
sys.stdout.reconfigure(encoding="utf-8")
os.environ["XEYO_BENCH_MINIMAL"] = "1"
from tools.catalog import build_default_registry
reg = build_default_registry(cwd=".")
for name in ("offload_read", "Bash", "Read"):
    t = reg.get(name)
    print(name, "->", "REGISTERED" if t else "missing",
          "| in schemas:", any((s or {}).get("name") == name for s in reg.schemas() if isinstance(s, dict)))
from tools.meta import TOOL_META, meta_for
m = meta_for("offload_read")
print("meta:", m)
print("enabled tools in meta:", sum(1 for k, v in TOOL_META.items() if getattr(v, "enabled", False)))
