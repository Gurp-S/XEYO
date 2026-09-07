"""BFCL-lite：函数调用评测（simple_python / parallel 等价类），本地确定性判分。

表格1对应 BFCL `--test-category simple_python,parallel`；官方 bfcl-eval 依赖 Unix
沙箱且不支持 Python 3.14，此处按同一评测语义自建 100 例（simple 50 + parallel 50），
工具 schema 风格与 Berkeley BFCL 一致（单步调用 + 并行多调用），判分要求
函数名与参数完全匹配（数值按值比较、字符串去首尾空白、顺序无关）。

思考模式：按表格2「简单单步调用 → 关闭」，本基准 thinking=disabled。
"""

from __future__ import annotations

import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import (  # noqa: E402
    MODEL_ID,
    STARTUP_DIR,
    account,
    chat,
    ensure_stdout_utf8,
)

RESULTS_DIR = STARTUP_DIR / "bfcl"
import os

SMOKE = bool(os.environ.get("XEYO_EVAL_SMOKE"))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "获取指定城市当前天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名"},
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "温度单位",
                    },
                },
                "required": ["location", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "获取指定股票代码的最新价格",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string", "description": "股票代码"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "发送一封电子邮件",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "收件人邮箱"},
                    "subject": {"type": "string", "description": "邮件主题"},
                    "body": {"type": "string", "description": "邮件正文"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_song_title",
            "description": "根据一句歌词查找歌曲名称",
            "parameters": {
                "type": "object",
                "properties": {"lyrics": {"type": "string", "description": "歌词片段"}},
                "required": ["lyrics"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_tip",
            "description": "按小费比例计算小费金额",
            "parameters": {
                "type": "object",
                "properties": {
                    "bill_total": {"type": "number", "description": "账单总额"},
                    "tip_percentage": {"type": "number", "description": "小费百分比"},
                },
                "required": ["bill_total", "tip_percentage"],
            },
        },
    },
]

CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆"]
TICKERS = ["AAPL", "MSFT", "GOOG", "AMZN", "TSLA", "META", "NVDA", "NFLX", "AMD", "INTC"]

SYSTEM_PROMPT = (
    "你是工具调用助手。根据用户请求选择并调用合适的函数；参数只能来自用户明确给出的信息。"
    "需要多个信息时并行发起全部函数调用。除函数调用外不要输出任何内容。"
)

# 无关检测专用提示词：允许文字回答，测量的是「该不该调用函数」而非「只能输出调用」的强约束。
IRRELEVANCE_SYSTEM_PROMPT = (
    "你是通用助手。根据用户请求作答；只有当存在语义匹配的可用函数时才调用函数，"
    "否则直接给出文字回答。不要为了调用而调用函数。"
)


def build_simple_cases() -> list[dict]:
    cases: list[dict] = []
    for i in range(10):
        city = CITIES[i]
        for j, unit in enumerate(("celsius", "fahrenheit")):
            label = "摄氏度" if unit == "celsius" else "华氏度"
            cases.append(
                {
                    "id": f"simple-weather-{i}-{j}",
                    "query": f"现在{city}的天气怎么样？温度用{label}表示。",
                    "expected": [
                        {"name": "get_current_weather", "arguments": {"location": city, "unit": unit}}
                    ],
                }
            )
    for i in range(10):
        t = TICKERS[i]
        cases.append(
            {
                "id": f"simple-stock-{i}",
                "query": f"帮我查一下 {t} 的最新股价。",
                "expected": [{"name": "get_stock_price", "arguments": {"ticker": t}}],
            }
        )
    emails = [
        ("alice@example.com", "周会提醒", "明天上午十点例会。"),
        ("bob@example.com", "报告提交", "季度报告已发你邮箱。"),
        ("carol@example.com", "生日祝福", "生日快乐！"),
        ("david@example.com", "发票事宜", "请把上月的发票发给我。"),
        ("eve@example.com", "合作邀请", "想约时间聊聊合作细节。"),
        ("frank@example.com", "周报汇总", "本周周报请查收。"),
        ("grace@example.com", "文档链接", "设计文档链接已更新。"),
        ("heidi@example.com", "值班提醒", "今晚值班请注意来电。"),
    ]
    for i, (to, subj, body) in enumerate(emails):
        cases.append(
            {
                "id": f"simple-email-{i}",
                "query": f'给 {to} 发一封邮件，主题是"{subj}"，正文写："{body}"。',
                "expected": [
                    {"name": "send_email", "arguments": {"to": to, "subject": subj, "body": body}}
                ],
            }
        )
    lyrics = [
        "月亮代表我的心",
        "海阔天空的旋律",
        "夜空中最亮的星",
        "光阴的故事里",
        "平凡之路的方向",
    ]
    for i, ly in enumerate(lyrics):
        cases.append(
            {
                "id": f"simple-song-{i}",
                "query": f'有一句歌词是"{ly}"，这是什么歌？',
                "expected": [{"name": "find_song_title", "arguments": {"lyrics": ly}}],
            }
        )
    tips = [(120.5, 15), (86.0, 10), (240.75, 18), (59.9, 12), (310.4, 20), (77.7, 16), (150.0, 14)]
    for i, (total, pct) in enumerate(tips):
        cases.append(
            {
                "id": f"simple-tip-{i}",
                "query": f"账单一共 {total} 元，我想给 {pct}% 的小费，小费是多少钱？",
                "expected": [
                    {"name": "calculate_tip", "arguments": {"bill_total": total, "tip_percentage": pct}}
                ],
            }
        )
    return cases


def build_parallel_cases() -> list[dict]:
    cases: list[dict] = []

    def w(city: str) -> dict:
        return {"name": "get_current_weather", "arguments": {"location": city, "unit": "celsius"}}

    def s(ticker: str) -> dict:
        return {"name": "get_stock_price", "arguments": {"ticker": ticker}}

    def e(to: str, subj: str, body: str) -> dict:
        return {
            "name": "send_email",
            "arguments": {"to": to, "subject": subj, "body": body},
        }

    for i in range(10):
        a, b = CITIES[i], CITIES[(i + 3) % 10]
        cases.append(
            {
                "id": f"parallel-w2-{i}",
                "query": f"同时查一下{a}和{b}现在的气温，都用摄氏度。",
                "expected": [w(a), w(b)],
            }
        )
    for i in range(10):
        a, b = TICKERS[i], TICKERS[(i + 5) % 10]
        cases.append(
            {
                "id": f"parallel-s2-{i}",
                "query": f"看看 {a} 和 {b} 两只股票现在的价格。",
                "expected": [s(a), s(b)],
            }
        )
    for i in range(10):
        trio = [CITIES[i], CITIES[(i + 2) % 10], CITIES[(i + 6) % 10]]
        cases.append(
            {
                "id": f"parallel-w3-{i}",
                "query": f"帮我并行查询{trio[0]}、{trio[1]}、{trio[2]}三个城市的实时温度，单位摄氏度。",
                "expected": [w(c) for c in trio],
            }
        )
    for i in range(10):
        city, t = CITIES[i], TICKERS[i]
        cases.append(
            {
                "id": f"parallel-mix-{i}",
                "query": f"先看下{city}今天气温（摄氏度），再查一下 {t} 的股价，两个一起做。",
                "expected": [w(city), s(t)],
            }
        )
    email_jobs = [
        ("frank@example.com", "会议纪要", "请查收今天的会议纪要。"),
        ("grace@example.com", "合同扫描件", "合同扫描件见附件。"),
        ("heidi@example.com", "付款确认", "款项已付，请确认。"),
        ("ivan@example.com", "行程安排", "下周一行程已排好。"),
        ("judy@example.com", "产品反馈", "用户反馈整理完毕。"),
        ("ken@example.com", "面试邀请", "诚邀参加本周五的面试。"),
        ("linda@example.com", "报销单据", "报销单据已提交。"),
        ("mallory@example.com", "技术方案评审", "方案初稿请查阅。"),
        ("niaj@example.com", "数据同步通知", "数据已完成同步。"),
        ("olivia@example.com", "周末聚餐", "周六晚六点老地方见。"),
    ]
    for i, (to, subj, body) in enumerate(email_jobs):
        city, t = CITIES[i], TICKERS[(i + 1) % 10]
        cases.append(
            {
                "id": f"parallel-tri-{i}",
                "query": (
                    f"请一并处理三件事：1) 给 {to} 发邮件，主题\"{subj}\"，"
                    f"正文写：\"{body}\"；2) 查{city}天气（摄氏度）；3) 查 {t} 股价。"
                ),
                "expected": [e(to, subj, body), w(city), s(t)],
            }
        )
    return cases


def build_irrelevance_cases() -> list[dict]:
    """相关性/无关检测：查询与可用工具无关，模型应返回文字而非调用任何函数。

    这是首轮自研套件的盲区之一（此前完全未覆盖，官方 irrelevance 为 72.5%）。
    判分规则确定性：expect_no_call=True 时要求 0 次工具调用。
    """
    off = [
        "用一句话解释一下相对论。",
        "写一首关于大海的诗。",
        "推荐一本讲系统设计的书。",
        "把这句话翻译成英文：你好，世界。",
        "今天这个路段堵车吗？",
        "帮我想个理财建议。",
    ]
    return [
        {
            "id": f"irrelevant-{i}",
            "query": q,
            "expected": [],
            "expect_no_call": True,
            "system_prompt": IRRELEVANCE_SYSTEM_PROMPT,
        }
        for i, q in enumerate(off)
    ]


def _norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if isinstance(v, str):
        return v.strip()
    return v


def norm_call(call: dict) -> tuple:
    args = call.get("arguments") or {}
    return (
        call.get("name"),
        tuple(sorted((k, _norm(v)) for k, v in args.items() if k != "__unparsed__")),
    )


def judge(
    actual_calls: list[dict], expected: list[dict], *, expect_no_call: bool = False
) -> tuple[bool, str]:
    if expect_no_call:
        return (True, "ok") if not actual_calls else (False, f"unexpected_call_{len(actual_calls)}")
    if not actual_calls:
        return False, "no_tool_call"
    got = Counter(norm_call(c) for c in actual_calls)
    want = Counter(norm_call(c) for c in expected)
    if len(actual_calls) != len(expected):
        return False, f"count_{len(actual_calls)}_vs_{len(expected)}"
    if got != want:
        return False, "mismatch"
    return True, "ok"


def run_item(case: dict) -> dict:
    acc = account("bfcl")
    system_prompt = case.get("system_prompt", SYSTEM_PROMPT)
    try:
        resp = chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": case["query"]}],
            thinking="disabled",
            tools=TOOLS,
            max_tokens=2048,
            temperature=0,
            acct=acc,
        )
    except Exception as e:  # noqa: BLE001
        return {"id": case["id"], "model": MODEL_ID, "category": case["id"].split("-")[0], "pass": False, "error": str(e)[:200]}
    ok, reason = judge(resp["tool_calls"], case["expected"], expect_no_call=case.get("expect_no_call", False))
    return {
        "id": case["id"],
        "model": MODEL_ID,
        "category": case["id"].split("-")[0],
        "pass": ok,
        "reason": reason,
        "n_calls": len(resp["tool_calls"]),
        "finish_reason": resp["finish_reason"],
    }


def main() -> int:
    ensure_stdout_utf8()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items_path = RESULTS_DIR / "items.jsonl"

    simple, parallel, irr = build_simple_cases(), build_parallel_cases(), build_irrelevance_cases()
    all_cases = (simple + parallel + irr)[:8] if SMOKE else simple + parallel + irr
    print(f"[bfcl] model={MODEL_ID} cases={len(all_cases)} smoke={SMOKE}")

    done: set[str] = set()
    if items_path.exists():
        with items_path.open(encoding="utf-8") as f:
            # 只认当前 model 的历史行,避免跨模型混染与误跳过(G150)。
            done = {
                json.loads(x)["id"]
                for x in f
                if x.strip() and json.loads(x).get("model") == MODEL_ID
            }
    todo = [c for c in all_cases if c["id"] not in done]
    print(f"[bfcl] resume: done={len(done)} todo={len(todo)}")

    lock = threading.Lock()
    results: list[dict] = []
    with items_path.open("a", encoding="utf-8") as sink:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(run_item, c): c for c in todo}
            for fut in as_completed(futures):
                r = fut.result()
                with lock:
                    results.append(r)
                    sink.write(json.dumps(r, ensure_ascii=False) + "\n")
                    sink.flush()
                status = "PASS" if r["pass"] else f"FAIL({r.get('reason')})"
                print(f"[bfcl] {r['id']} {status}")

    merged = []
    with items_path.open(encoding="utf-8") as f:
        merged = [json.loads(x) for x in f if x.strip()]
    by_id = {c["id"]: c["id"].split("-")[0] for c in all_cases}
    # 仅汇总当前 model 的结果:历史其他模型行(含旧格式无 model 字段)一律排除,防混染成绩
    merged = [r for r in merged if r["id"] in by_id and r.get("model") == MODEL_ID]

    summary = {
        "model": MODEL_ID,
        "thinking": "disabled",
        "cases_total": len(all_cases),
        "usage": account("bfcl").summary(),
        "overall": _acc(merged),
        "by_category": {},
    }
    cats = sorted({r["category"] for r in merged})
    for cat in cats:
        sub = [r for r in merged if r["category"] == cat]
        summary["by_category"][cat] = _acc(sub)

    out = STARTUP_DIR / "bfcl_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["overall"], ensure_ascii=False))
    print(f"[bfcl] summary -> {out}")
    return 0


def _acc(rows: list[dict]) -> dict:
    n = len(rows)
    p = sum(1 for r in rows if r["pass"])
    return {"passed": p, "total": n, "accuracy": round(p / n, 4) if n else None}


if __name__ == "__main__":
    raise SystemExit(main())
