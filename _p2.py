import os, sys
sys.path.insert(0, "python")
sys.stdout.reconfigure(encoding="utf-8")
os.environ["XEYO_BENCH_MINIMAL"] = "1"
from tools.catalog import build_default_registry
reg = build_default_registry(cwd=".")
names = sorted(str(s.get("name")) for s in reg.schemas() if isinstance(s, dict) and s.get("name"))
print("bench tool face:", len(names))
print(names)
print()
os.environ.pop("XEYO_BENCH_MINIMAL", None)
reg2 = build_default_registry(cwd=".")
n2 = sorted(str(s.get("name")) for s in reg2.schemas() if isinstance(s, dict) and s.get("name"))
print("native tool face:", len(n2))
print("native - bench =", sorted(set(n2) - set(names)))
