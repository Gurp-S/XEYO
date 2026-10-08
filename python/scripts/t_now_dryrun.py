"""提示面 dry-run：用**当前代码**在一个独立进程里跑一次注入装配，打印会进注意力的块。

动机（agent 自报的摩擦）：改 T_now 块 / Read 工具 / notice 载波之后，运行中的后端
仍加载旧模块——模型自己看不到效果，只能等重启。这个脚本把"改-验"闭环从进程生命周期
里解耦：给定会话或一份 projected 载荷，直接跑 ``run_pre_llm_inject`` 并打印
"块名 + 正文 + 来源声明出现次数"。

用法（离线、零 API 成本）::

    py -3.11 -m scripts.t_now_dryrun --session sess_xxx
    py -3.11 -m scripts.t_now_dryrun --json projected.json
    py -3.11 -m scripts.t_now_dryrun --text "随便一句话"

``--session`` 的载荷由 transcript 尽力转换（Message → dict）；要逐字节核对请用
``--json`` 传你实际要发的载荷。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.notice_channel import NOTICE_SOURCE_LINE  # noqa: E402
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject  # noqa: E402


def _payload_from_session(session_id: str) -> list[dict]:
    from session.hydrate import load_session_messages

    out: list[dict] = []
    for message in load_session_messages(session_id) or []:
        to_dict = getattr(message, "to_dict", None)
        if callable(to_dict):
            out.append(to_dict())
            continue
        out.append(
            {
                "role": str(getattr(message, "role", "user")),
                "content": getattr(message, "content", ""),
            }
        )
    return out


def _payload_from_json(path: str) -> list[dict]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("messages"), list):
        raw = raw["messages"]
    return [row for row in raw if isinstance(row, dict)]


def _text_payload(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def _row_texts(row: dict) -> list[str]:
    content = row.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T_now 提示面 dry-run")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session", help="会话 id（从 transcript 尽力还原载荷）")
    group.add_argument("--json", help="projected 载荷 JSON（messages 数组或 {messages:[…]}）")
    group.add_argument("--text", help="只喂一句话（最小冒烟）")
    parser.add_argument("--cwd", default="", help="工作区根（缺省取 XEYO_CWD/当前目录）")
    parser.add_argument(
        "--window",
        type=int,
        default=0,
        help="用户登记的上下文窗口（权威分母）；给 0 = 模型未登记时不报占比",
    )
    parser.add_argument(
        "--used",
        type=int,
        default=0,
        help="模拟上一枪的厂商输入 token（等价 usage.prompt_tokens）；给 0 = 走 est 兜底",
    )
    args = parser.parse_args(argv)

    if args.session:
        projected = _payload_from_session(args.session)
    elif args.json:
        projected = _payload_from_json(args.json)
    else:
        projected = _text_payload(args.text or "")

    cwd = args.cwd or ""
    ctx = InjectContext(
        cwd=cwd,
        session_id=args.session or "",
        window_tokens=args.window,
        last_usage={"prompt_tokens": args.used} if args.used > 0 else None,
    )
    out = run_pre_llm_inject([dict(row) for row in projected], ctx)

    texts: list[str] = []
    new_texts: list[str] = []
    for index, row in enumerate(out):
        for text in _row_texts(row):
            texts.append(text)
            if index >= len(projected):
                new_texts.append(text)
    blob = "\n".join(texts)
    new_blob = "\n".join(new_texts)

    print(
        f"projected messages: {len(projected)} → emitted rows: {len(out)}"
        f"（本次新增 {len(out) - len(projected)} 条）"
    )
    print(
        "本次新增里的来源声明出现次数: "
        f"{new_blob.count(NOTICE_SOURCE_LINE)}（多块各带一次 = 旧行为；1 = 已收口）"
    )
    print(f"（全量含历史：{blob.count(NOTICE_SOURCE_LINE)} 次——历史消息里本来就带着旧通报）")
    print("-" * 72)
    for text in new_texts:
        stripped = text.strip()
        # 本次新增的片段**逐条**打印：不能再按"含来源声明"筛——② 收口后只有第一条
        # 带声明，靠它筛会把其余块（正是要看的那条）全部藏掉。
        if not stripped.startswith("<system-reminder"):
            continue
        match = re.search(r'key="([^"]*)"', stripped)
        key = match.group(1) if match else "(no key)"
        body = stripped.split(NOTICE_SOURCE_LINE, 1)[-1].strip()
        print(f"[{key}]\n{body}\n")
    print("-" * 72)
    print(f"总字符: {len(blob)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
