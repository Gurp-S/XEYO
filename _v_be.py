import sys, inspect
sys.path.insert(0, "python")
sys.stdout.reconfigure(encoding="utf-8")
from engine.query_engine import build_default_engine as f
src = inspect.getsource(f)
i = src.find("OpenAICompatible")
if i < 0:
    i = src.find("openai_compat")
print(src[max(0, i - 1500):i + 2000])
