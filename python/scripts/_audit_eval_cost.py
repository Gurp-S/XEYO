"""评测花费精确测算（审计随附）。

定价（截图）：deepseek-v4-flash(-vision-exp) 每百万 tokens
  输入(缓存命中)  空闲 0.05 元 / 高峰 0.10 元
  输入(未命中)    空闲 1.50 元 / 高峰 3.00 元
  输出            空闲 4.50 元 / 高峰 9.00 元

token 假设全部参数化；标注 [实测] 的来自本仓库已有数据，[估] 的为行业典型值，
跑一次真实样本后可用实测值回填（脚本输出 header 提示哪些参数需要校准）。
"""

from __future__ import annotations

P = {  # 每百万 tokens（元）
    "hit_offpeak": 0.05, "hit_peak": 0.10,
    "miss_offpeak": 1.50, "miss_peak": 3.00,
    "out_offpeak": 4.50, "out_peak": 9.00,
}


def cost(input_tokens: int, output_tokens: int, hit_ratio: float, peak: bool) -> float:
    """input_tokens 中 hit_ratio 比例按命中价计，其余按未命中价；输出按输出价。"""
    hit = P["hit_peak" if peak else "hit_offpeak"]
    miss = P["miss_peak" if peak else "miss_offpeak"]
    out = P["out_peak" if peak else "out_offpeak"]
    m = 1_000_000.0
    return input_tokens / m * (hit_ratio * hit + (1 - hit_ratio) * miss) + output_tokens / m * out


def fmt(y: float) -> str:
    return f"{y:.2f} 元" if y >= 1 else f"{y * 100:.0f} 分"


# ---------------------------------------------------------------- token 假设
# [估] HumanEval 164 题：模板+docstring ≈800 tok/题（上限 1200），补全 ≈400 tok
HE = dict(n=164, prompt=800, completion=400)
# [估] MBPP sanitized 427 题：3-shot 前缀+题目 ≈500 tok，补全 ≈300 tok
MBPP = dict(n=427, prompt=500, completion=300)
# [估] BFCL v4 单轮类（AST/live/irrelevance/relevance）≈1800 题：工具文档大头 ≈2000 tok，输出 ≈120 tok
BFCL_1T = dict(n=1800, prompt=2000, completion=120)
# [估] BFCL v4 multi-turn ≈800 场景 × 5 轮：每场景累计输入 35,000 tok（无缓存口径），输出 700 tok
BFCL_MT = dict(n=800, prompt=35_000, completion=700)
# [估] τ-bench 全量 165 题（agent+用户模拟器双计）：每任务累计输入 120,000 tok，输出 6,000 tok
TAU_FULL = dict(n=165, prompt=120_000, completion=6_000)
TAU_50 = dict(n=50, prompt=120_000, completion=6_000)
# [实测] XEYO live 证据复跑：hitrate ultra 4 配置（project 4.47M + c2 0.712M ≈ 单配置 5.2M×4）
# + 表A-real 24 题×3 次×2 配置 ≈0.3M → ≈21M 输入；输出 ≈80k；命中率按 93.9%
LIVE = dict(n=1, prompt=21_000_000, completion=80_000, hit=0.939)

BENCHES = [
    ("HumanEval 全量", HE["n"] * HE["prompt"], HE["n"] * HE["completion"], 0.0),
    ("MBPP 全量", MBPP["n"] * MBPP["prompt"], MBPP["n"] * MBPP["completion"], 0.0),
    ("BFCL 单轮类(≈1800题)", BFCL_1T["n"] * BFCL_1T["prompt"], BFCL_1T["n"] * BFCL_1T["completion"], 0.6),
    ("BFCL multi-turn(800场)", BFCL_MT["n"] * BFCL_MT["prompt"], BFCL_MT["n"] * BFCL_MT["completion"], 0.6),
    ("τ-bench 全量(165题)", TAU_FULL["n"] * TAU_FULL["prompt"], TAU_FULL["n"] * TAU_FULL["completion"], 0.6),
    ("τ-bench 子集(50题)", TAU_50["n"] * TAU_50["prompt"], TAU_50["n"] * TAU_50["completion"], 0.6),
    ("XEYO live 证据复跑", LIVE["prompt"], LIVE["completion"], LIVE["hit"]),
]

CACHE_SCENARIOS = [
    ("基准口径(HE/MBPP0%,BFCL/τ60%,live94%)", None),  # 各基准自身的命中假设
    ("统一60%自动前缀缓存", 0.60),
    ("统一93.9%(全走XEYO引擎)", 0.939),
]


def main() -> None:
    print("定价：命中 0.05/0.10，未命中 1.5/3.0，输出 4.5/9.0（每百万，空闲/高峰）")
    print("token 假设见脚本参数（[实测]=live 复跑用真实账本口径；其余为行业典型值，"
          "首跑后用 usage 回填校准）\n")

    hdr = f"{'评测':<26}{'输入tok':>12}{'输出tok':>10} | " + "".join(
        f"{s[0][:14]:>16} | " for s in CACHE_SCENARIOS
    )
    for peak, tag in ((False, "空闲时段"), (True, "高峰时段")):
        print(f"===== {tag} =====")
        print(hdr)
        totals = [0.0] * len(CACHE_SCENARIOS)
        for name, it, ot, own_hit in BENCHES:
            row = f"{name:<26}{it:>12,}{ot:>10,} | "
            for i, (sname, forced) in enumerate(CACHE_SCENARIOS):
                hr = own_hit if forced is None else max(forced, own_hit if own_hit else 0.0)
                c = cost(it, ot, hr, peak)
                totals[i] += c
                row += f"{fmt(c):>16} | "
            print(row)
        print(f"{'全跑合计':<26}{'':>12}{'':>10} | " + "".join(f"{fmt(t):>16} | " for t in totals))
        print()

    # 三档套餐（推荐口径：60% 缓存）
    idx60 = 1
    sets = {
        "最低配(HE+MBPP+BFCL单轮+BFCL_MT)": [0, 1, 2, 3],
        "推荐配(+τ50+live复跑)": [0, 1, 2, 3, 5, 6],
        "全量配(+τ全量)": [0, 1, 2, 3, 4, 5, 6],
    }
    for peak, tag in ((False, "空闲"), (True, "高峰")):
        print(f"--- 套餐合计（{tag}，60%缓存口径）---")
        for sname, members in sets.items():
            t = sum(
                cost(BENCHES[i][1], BENCHES[i][2],
                     max(0.60, BENCHES[i][3] if CACHE_SCENARIOS[idx60][1] is None else 0.60), peak)
                for i in members
            )
            print(f"  {sname}: {fmt(t)}")
        print()


if __name__ == "__main__":
    main()
