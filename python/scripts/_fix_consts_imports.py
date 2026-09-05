# -*- coding: utf-8 -*-
from pathlib import Path

fixes = [
	("tools/ask_user_question_tool/ask_user_question_tool.py",
	 "from tools.ask_user_question_tool.prompt import ASK_USER_TOOL_NAME\n"),
	("tools/screenshot_tool/screenshot_tool.py",
	 "from tools.screenshot_tool.prompt import SCREENSHOT_TOOL_NAME\n"),
	("tools/send_to_wechat_tool/send_to_wechat_tool.py",
	 "from tools.send_to_wechat_tool.prompt import SEND_TO_WECHAT_TOOL_NAME\n"),
]
for rel, bad in fixes:
	p = Path(__file__).resolve().parents[1] / rel
	s = p.read_text(encoding="utf-8")
	if bad in s:
		p.write_text(s.replace(bad, ""), encoding="utf-8", newline="")
		print("fixed", rel)
	else:
		print("anchor missing:", rel)
