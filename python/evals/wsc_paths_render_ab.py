"""开关前后 `[PATHS]` 段的**直接渲染对比**（人眼可核，不用任何自造判据）。

为什么不用统计式判据：本任务里 `existed_on_disk` 与「点名集合差集」两次都因
口径不对（未归一化 / 未算 is_noise_path）给出假阳性。渲染原文是唯一不会被
自己骗到的证据 —— 开关打开后 `[PATHS]` 里**实际少了哪几行**，直接看。

用法: py -3.11 python/evals/wsc_paths_render_ab.py <session.jsonl> [region_end]
"""
from __future__ import annotations

import difflib
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "python"))

from synaptic.project import default_params, project  # noqa: E402

SWITCH = "XEYO_WSC_PATHS_ARG_ONLY"


def rows_to_messages(path: Path) -> list[dict]:
	out: list[dict] = []
	for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			ev = json.loads(line)
		except Exception:
			continue
		msg = ev.get("message") if isinstance(ev, dict) else None
		if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
			out.append(msg)
		elif isinstance(ev, dict) and ev.get("role") in ("user", "assistant"):
			out.append(ev)
	return out


def head_text(proj) -> str:
	r = proj.result
	d = asdict(r) if is_dataclass(r) else getattr(r, "__dict__", {"repr": repr(r)})
	return json.dumps(d, ensure_ascii=False, default=str).replace("\\n", "\n")


def paths_block(text: str) -> str:
	lines = text.splitlines()
	out: list[str] = []
	inside = False
	for ln in lines:
		s = ln.strip()
		if s.startswith("[PATHS]"):
			inside = True
			out.append(ln)
			continue
		if inside:
			if s.startswith("[") and not s.startswith("[PATHS]"):
				break
			out.append(ln)
	return "\n".join(out)


def render(messages: list[dict], region_end: int, *, on: bool) -> str:
	old = os.environ.get(SWITCH)
	os.environ[SWITCH] = "1" if on else "0"
	try:
		proj = project(messages, region_end=region_end, params=default_params())
		return paths_block(head_text(proj))
	finally:
		if old is None:
			os.environ.pop(SWITCH, None)
		else:
			os.environ[SWITCH] = old


def main() -> int:
	if len(sys.argv) < 2:
		print(f"usage: {Path(__file__).name} <session.jsonl> [region_end]")
		return 2
	src = Path(sys.argv[1])
	messages = rows_to_messages(src)
	end = int(sys.argv[2]) if len(sys.argv) > 2 else len(messages)

	off = render(messages, end, on=False)
	on = render(messages, end, on=True)

	print(f"# source: {src.name}  messages={len(messages)}  region_end={end}")
	print(f"# OFF lines={len(off.splitlines())} chars={len(off)}")
	print(off)
	print(f"\n# ON  lines={len(on.splitlines())} chars={len(on)}")
	print(on)
	print("\n# DIFF (OFF -> ON)")
	for line in difflib.unified_diff(off.splitlines(), on.splitlines(),
	                                 "off", "on", lineterm="", n=0):
		print(line)

	def paths_of(block: str) -> set[str]:
		"""渲染行格式是 ``[PATHS] <path>``（前缀与路径同行），故按前缀切。"""
		found: set[str] = set()
		for ln in block.splitlines():
			s = ln.strip()
			if s.startswith("[PATHS]"):
				rest = s[len("[PATHS]"):].strip()
				if rest:
					found.add(rest)
		return found

	dropped = sorted(paths_of(off) - paths_of(on))
	kept = paths_of(on)
	print(f"\n# SUMMARY off={len(paths_of(off))} on={len(kept)} dropped={len(dropped)}")
	print("# dropped:", dropped)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
