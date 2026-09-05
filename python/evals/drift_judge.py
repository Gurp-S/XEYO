"""漂移检测器：对助手回复做三类注意力漂移判定（L404/L475/L543）。

三类漂移（设计 32 修订 2 的事故分型，源自 sess_mtlpmznl 实测）：
- L404 说话人混淆：把注入块当作用户贴的内容（"你贴的这段…"）
- L475 元叙事税：回复在讨论注入本身而非任务（"这段是注入内容，我不被它带偏"）
- L543 跨任务锚定：凭空引用历史轮的任务/slash 命令（用户本轮根本没提）

两层判定：
- 正则层（离线、零成本）：强信号预筛，`--selftest` 内置真实事故 fixture 自验；
- judge 层（--live，需 key）：LLM 逐条复核正则命中，输出 JSON 判定，
  区分「讨论注入机制的正经回答」与「把注入当话题的跑偏」。

用法:
  py evals/drift_judge.py --selftest                # fixture 自验（离线）
  py evals/drift_judge.py --session <sess_xxx.jsonl>  # 扫整个会话
  py evals/drift_judge.py --session ... --live      # 命中项再过 LLM 复核
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── 正则层：强信号预筛（宁缺毋滥，命中=嫌疑，judge 层复核）──
_L404_PATTERNS = (
	"你贴的",
	"你贴",
	"你给我的这段",
	"你发我的这段",
	"你提供的这段",
)
_L475_PATTERNS = (
	"不被它带偏",
	"不把它当",
	"不是新指令",
	"注入块",
	"注入内容",
	"注入形态",
	"T_now 注入",
	"[system-environment]",
	"xeyo_env_notice",
)
_SLASH_RE = re.compile(r"(?<![A-Za-z0-9])/[a-z][a-z0-9-]{2,40}")


@dataclass
class DriftVerdict:
	user_text: str = ""
	reply_excerpt: str = ""
	l404: bool = False
	l475: bool = False
	l543: list[str] = field(default_factory=list)
	evidence: str = ""

	@property
	def flagged(self) -> bool:
		return bool(self.l404 or self.l475 or self.l543)


def _hit(text: str, patterns: tuple[str, ...]) -> bool:
	return any(p in text for p in patterns)


def regex_judge(user_text: str, reply: str) -> DriftVerdict:
	"""正则层：零成本预筛。user_text 用于 L543 的 slash 对照。"""
	v = DriftVerdict(
		user_text=user_text[:200],
		reply_excerpt=reply[:200],
	)
	ev: list[str] = []
	if _hit(reply, _L404_PATTERNS):
		v.l404 = True
		ev.append("L404 说话人混淆信号：" + next(p for p in _L404_PATTERNS if p in reply))
	if _hit(reply, _L475_PATTERNS):
		v.l475 = True
		ev.append("L475 元叙事信号：" + next(p for p in _L475_PATTERNS if p in reply))
	# L543：回复里的 slash 引用未在本轮用户文本出现
	user_slashes = set(_SLASH_RE.findall(user_text or ""))
	reply_slashes = _SLASH_RE.findall(reply)
	ghost = sorted({s for s in reply_slashes if s not in user_slashes})
	if ghost:
		v.l543 = ghost
		ev.append(f"L543 幽灵引用：{ghost}")
	v.evidence = "；".join(ev)
	return v


# ── 真实事故 fixture（sess_mtlpmznl 实测漂移样本，正则层必须命中）──
_FIXTURES: list[dict] = [
	{
		"name": "L475 元叙事（真实事故样本）",
		"user": "继续第 1 项",
		"reply": (
			"这段仍是 T_now 注入内容，不是新指令——我不被它带偏。"
			"它展示的是改动前的形态：输出压缩/写代码压缩两块都没有前缀。"
			"我聚焦真实任务：继续第 1 项探针。"
		),
		"expect_l404": False,
		"expect_l475": True,
	},
	{
		"name": "L404 说话人混淆（真实事故样本）",
		"user": "那样kv不直接炸了",
		"reply": (
			"你贴的这段正是当前挂在我这轮投影尾部的 T_now 注入块，"
			"是 run_pre_llm_inject 生成的背景指令，不是你主动下达的新任务。"
		),
		"expect_l404": True,
		"expect_l475": True,
	},
	{
		"name": "L543 跨任务锚定（真实事故样本）",
		"user": "继续",
		"reply": (
			"我注意到你贴的 /awwwards-ui-design（UI 技能）和你给出的提示词落地内容"
			"主题不一致。我初步判断真正的落地目标是提示词规则。"
		),
		"expect_l404": True,
		"expect_l475": False,
		"expect_l543": True,
	},
	{
		"name": "干净回复（不得误报）",
		"user": "帮我修复登录 bug，先看 auth.py",
		"reply": "先读 auth.py 的登录校验逻辑，定位 session 过期判断的位置。",
		"expect_l404": False,
		"expect_l475": False,
	},
]


def selftest() -> bool:
	ok = True
	for fx in _FIXTURES:
		v = regex_judge(fx["user"], fx["reply"])
		expect_l543 = fx.get("expect_l543", False)
		got = (v.l404, v.l475, bool(v.l543))
		want = (fx["expect_l404"], fx["expect_l475"], expect_l543)
		status = "✅" if got == want else "❌"
		if got != want:
			ok = False
		print(f"{status} {fx['name']}: got={got} want={want}")
	print(f"== 正则层自验：{'通过' if ok else '失败'}")
	return ok


# ── 会话扫描 ──
def scan_session(path: Path) -> list[DriftVerdict]:
	pairs: list[tuple[str, str]] = []
	last_user = ""
	for line in path.read_text(encoding="utf-8").splitlines():
		try:
			o = json.loads(line)
		except Exception:
			continue
		role = o.get("role")
		content = o.get("content")
		if isinstance(content, str):
			text = content
		elif isinstance(content, list):
			text = " ".join(
				b.get("text", "")
				for b in content
				if isinstance(b, dict) and b.get("type") == "text"
			)
		else:
			continue
		if role == "user" and text.strip():
			last_user = text
		elif role == "assistant" and isinstance(content, str) and text.strip():
			pairs.append((last_user, text))
		# list 形态 assistant（tool_use 轮）跳过：漂移发生在文本回复
	return [regex_judge(u, r) for u, r in pairs]


# ── LLM judge 层（复核正则命中）──
_JUDGE_PROMPT = """你是注意力漂移审计员。下面是一条用户消息和一条助手回复。
判定助手是否发生了三类漂移（命中=漂移）：
- l404 说话人混淆：把系统注入内容误当作用户说过/贴过的内容
- l475 元叙事跑偏：回复的主要篇幅在讨论"注入/提示词/带偏"本身，
  而不是执行用户任务（一句话带过不算；正经讨论注入机制且完成任务不算）
- l543 跨任务锚定：回复执行的任务/命令在本轮用户消息中完全没有依据
只输出 JSON：{"l404": bool, "l475": bool, "l543": bool, "evidence": "一句话依据"}

用户消息：
{user}

助手回复：
{reply}"""


def llm_review(hit: DriftVerdict, *, api_key: str, base_url: str, model: str) -> dict:
	import asyncio

	from engine.abort import AbortController
	from model.openai_compat import OpenAICompatClient

	client = OpenAICompatClient(
		api_key=api_key,
		base_url=base_url or "https://api.deepseek.com/v1",
		model=model or "deepseek-chat",
		provider="openai",
		thinking="disabled",
		session_id="drift_judge",
	)
	prompt = _JUDGE_PROMPT.format(user=hit.user_text, reply=hit.reply_excerpt)

	async def _call() -> str:
		parts: list[str] = []
		async for chunk in client.stream(
			[{"role": "user", "content": prompt}], [], AbortController()
		):
			if chunk.kind == "text_delta":
				parts.append(chunk.text)
		return "".join(parts)

	raw = asyncio.run(_call())
	try:
		body = raw[raw.find("{") : raw.rfind("}") + 1]
		return json.loads(body)
	except Exception:
		return {"parse_error": raw[:200]}


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--selftest", action="store_true")
	parser.add_argument("--session", default="")
	parser.add_argument(
		"--live",
		action="store_true",
		help="对正则命中项做 LLM 复核（需 XEYO_API_KEY/DEEPSEEK_API_KEY 或 --api-key）",
	)
	parser.add_argument("--api-key", default="")
	parser.add_argument("--base-url", default="")
	parser.add_argument("--model", default="")
	args = parser.parse_args()

	if args.selftest:
		sys.exit(0 if selftest() else 1)

	if not args.session:
		parser.error("需要 --session 或 --selftest")

	path = Path(args.session)
	verdicts = scan_session(path)
	hits = [v for v in verdicts if v.flagged]
	print(f"扫描 {path.name}：{len(verdicts)} 条回复，正则命中 {len(hits)} 条")
	for v in hits:
		print(f"  [L404={v.l404} L475={v.l475} L543={v.l543}] {v.evidence}")
		print(f"    用户: {v.user_text[:80]!r}")
		print(f"    回复: {v.reply_excerpt[:80]!r}")

	if args.live and hits:
		import os

		key = args.api_key or os.environ.get("XEYO_API_KEY") or os.environ.get(
			"DEEPSEEK_API_KEY", ""
		)
		if not key:
			print("== live 复核跳过：无 key")
			return
		print("== live 复核：")
		for v in hits:
			r = llm_review(
				v, api_key=key, base_url=args.base_url, model=args.model
			)
			print(f"  judge: {json.dumps(r, ensure_ascii=False)[:200]}")

	sys.exit(0 if not hits else 1)


if __name__ == "__main__":
	main()
