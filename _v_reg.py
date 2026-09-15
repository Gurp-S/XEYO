import sys, re
sys.stdout.reconfigure(encoding="utf-8")
s = open("python/prompt/pre_llm_inject.py", encoding="utf-8").read()
i = s.find("T_NOW_BLOCK_REGISTRY")
seg = s[i:i+6000]
print(seg)
