import sys, re
sys.stdout.reconfigure(encoding="utf-8")
s = open("docs/XEYO-高杠杆优化点-收益评估.md", encoding="utf-8").read()
i = s.find("## §8")
print(s[i:i+5200])
