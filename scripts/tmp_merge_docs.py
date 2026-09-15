"""
把 7 份对比/决策文档合并为一份《五轮合集》。

两条硬保证：
1. 零内容丢失 —— 每个源节的 (start,end) 行区间必须被完整搬运，且全文件行区间
   恰好铺满 1..N、无空洞、无重叠（脚本自带断言）。
2. 标题层级自动降级（+3 级，上限 h6），代码块内不降级。
"""
import pathlib
import re

ROOT = pathlib.Path(r"D:\lea\XenYon code")

DOCS = {
    1: "docs/XEYO-vs-DeepSeekHarness-全量对比.md",
    2: "docs/XEYO-vs-DeepSeekHarness-设计级对比-第二轮.md",
    3: "docs/XEYO-vs-DeepSeekHarness-实现级对比-第三轮.md",
    4: "docs/XEYO-vs-DeepSeekHarness-逐字段级对比-第四轮.md",
    5: "docs/XEYO-vs-DeepSeekHarness-机制设计说明-第五轮.md",
    6: "docs/XEYO-开源优化路线-五轮总结.md",
    7: "docs/XEYO-高杠杆优化点-收益评估.md",
}
SHORT = {
    1: "R1 功能面·全量对比",
    2: "R2 设计面·设计级对比",
    3: "R3 实现面·实现级对比",
    4: "R4 枚举面·逐字段级对比",
    5: "R5 机制面·机制设计说明",
    6: "决策 A·优化路线五轮总结",
    7: "决策 B·高杠杆收益评估",
}


def parse(path):
    """解析节的 (level, title, start, end)，跳过代码块内的伪标题。"""
    lines = pathlib.Path(ROOT / path).read_text(encoding="utf-8").splitlines()
    heads = []
    in_code = False
    for i, l in enumerate(lines, 1):
        if l.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,2})\s+(.*)$", l)
        if m:
            heads.append((len(m.group(1)), m.group(2).strip(), i))
    secs = []
    for idx, (lv, t, ln) in enumerate(heads):
        end = heads[idx + 1][2] - 1 if idx + 1 < len(heads) else len(lines)
        secs.append({"lv": lv, "title": t, "start": ln, "end": end})
    return lines, secs, len(lines)


DATA = {k: parse(v) for k, v in DOCS.items()}


def demote_line(l):
    m = re.match(r"^(#{1,6})\s+(.*)$", l)
    if not m:
        return l
    n = min(6, len(m.group(1)) + 3)
    return "#" * n + " " + m.group(2)


def emit_block(out, doc, idxs, spans_log):
    """搬运若干节（可跨多个连续节），标题降级 3 级，加来源标注。"""
    lines, secs, _ = DATA[doc]
    spans = sorted((secs[ix]["start"], secs[ix]["end"], secs[ix]["title"]) for ix in idxs)
    merged = []
    for a, b, t in spans:
        if merged and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b), merged[-1][2])
        else:
            merged.append((a, b, t))
    for (a, b, t) in merged:
        spans_log.setdefault(doc, []).append((a, b))
        label = t if len(merged) == 1 else f"{t} 等 {len(merged)} 节合并"
        out.append(f"> 来源：**{SHORT[doc]}** · 原节「{label}」（源 L{a}–{b}）")
        out.append("")
        in_code = False
        for l in lines[a - 1:b]:
            if l.lstrip().startswith("```"):
                in_code = not in_code
                out.append(l)
                continue
            out.append(l if in_code else demote_line(l))
        out.append("")


# ---------------------------------------------------------------- PLAN
PLAN = []  # (卷, 章标题, [(doc, [节索引]), ...])

PLAN.append(("@INTRO", "导言", []))

# ===== 卷一：总纲 · 取证口径与更正沿革
PLAN += [
    ("VOL1", "1.1 第一轮 · 说明与取证口径", [(1, [0, 1])]),
    ("VOL1", "1.2 第二轮 · 两处更正（推翻第一轮的错误结论）", [(2, [0, 1])]),
    ("VOL1", "1.3 第三轮 · 取证基线与取证方式", [(3, [0])]),
    ("VOL1", "1.4 第四轮 · 方法、取证边界与三处更正", [(4, [0, 1])]),
    ("VOL1", "1.5 第五轮 · 定位与取值修正", [(5, [0, 1])]),
]

# ===== 卷二：逐域完整对照（每个域按 R1→R2→R3→R4 递进）
DOMAINS = [
    ("域 01 · 定位与顶层架构范式", [(1, [2, 3]), (2, [2])]),
    ("域 02 · 运行入口与产品形态", [(1, [4])]),
    ("域 03 · Agent 主循环", [(1, [5]), (2, [3]), (3, [1])]),
    ("域 04 · 会话数据模型与持久化", [(1, [6]), (2, [4]), (3, [2]), (4, [2])]),
    ("域 05 · 上下文投影与 KV 前缀缓存保护", [(1, [7]), (2, [5]), (3, [3])]),
    ("域 06 · 压缩与预算（含截断常量）", [(2, [6]), (3, [4]), (4, [10])]),
    ("域 07 · System Prompt 组装", [(1, [8]), (2, [7]), (3, [5])]),
    ("域 08 · 逐轮注入管线（T_now）★XEYO 独有", [(2, [8]), (3, [6]), (4, [7, 8])]),
    ("域 09 · 工具系统（抽象 · 注册 · 生命周期）★重点样例", [(1, [9]), (2, [9]), (3, [7]), (4, [3])]),
    ("域 10 · 工具执行管线", [(1, [10]), (2, [10]), (3, [8]), (4, [4])]),
    ("域 11 · 权限与审批（含逐分支与字段）", [(1, [11]), (2, [11]), (3, [9]), (4, [5, 6])]),
    ("域 12 · 沙箱与执行隔离", [(1, [12]), (2, [12]), (3, [10]), (4, [9])]),
    ("域 13 · 文件系统能力与写入策略", [(1, [13]), (2, [13]), (3, [11])]),
    ("域 14 · Shell / 终端 / 子进程", [(2, [14]), (3, [12])]),
    ("域 15 · 模型层与 provider / 流式协议", [(1, [19]), (2, [15]), (3, [13]), (4, [11])]),
    ("域 16 · 代码运行时与 LSP", [(2, [16])]),
    ("域 17 · 成本与用量", [(1, [20]), (2, [17]), (3, [14])]),
    ("域 18 · 记忆子系统", [(1, [21]), (2, [18]), (3, [15])]),
    ("域 19 · 子代理与多代理", [(1, [14]), (2, [19]), (3, [16]), (4, [13])]),
    ("域 20 · 调度 / 后台任务 / 工作流 / Webhook", [(1, [15]), (2, [20]), (3, [17]), (4, [14])]),
    ("域 21 · Skill 系统", [(1, [16]), (2, [21]), (3, [18])]),
    ("域 22 · MCP 与扩展层", [(1, [17]), (2, [22]), (3, [19])]),
    ("域 23 · Hooks（含 wire 协议逐字段）", [(1, [18]), (2, [23]), (3, [20]), (4, [12])]),
    ("域 24 · 扩展组合机制", [(2, [24]), (3, [21])]),
    ("域 25 · 服务端与协议（101 路由 + 23 帧）", [(1, [23]), (2, [25]), (3, [22]), (4, [15])]),
    ("域 26 · 前端架构", [(1, [22]), (2, [26]), (3, [23]), (4, [16])]),
    ("域 27 · 桌面壳与进程管理", [(2, [27]), (3, [24])]),
    ("域 28 · 对外集成（CLI / SDK / ACP）", [(1, [24]), (2, [28]), (3, [25])]),
    ("域 29 · 配置 / 凭据 / 身份 / 遥测", [(1, [25]), (2, [29]), (3, [26])]),
    ("域 30 · 测试与质量门 / 工程门禁", [(1, [26]), (2, [30]), (3, [27]), (4, [17])]),
    ("域 31 · 构建 / 打包 / 分发", [(1, [27]), (2, [31]), (3, [28])]),
    ("域 32 · 文档与协作规范", [(1, [28]), (2, [32])]),
    ("域 33 · 行为对照用例：同一任务在两端各发生什么", [(4, [19])]),
]
for title, srcs in DOMAINS:
    PLAN.append(("VOL2", title, srcs))

# ===== 卷三：机制设计说明（R5 全文，含 A/B/C 三部分）
PLAN.append(("VOL3", "3.1 机制总目录", [(5, [2])]))
PLAN.append(("VOL3", "3.2 机制设计说明 · 全文（A-1…A-11 / B-1…B-13 / C-1…C-5）", [(5, list(range(3, 35)))]))

# ===== 卷四：差异总表与累计结论
PLAN += [
    ("VOL4", "4.1 第一轮 · 差异总表与结论", [(1, [29, 30])]),
    ("VOL4", "4.2 第二轮 · 设计层差异总表与结论", [(2, [33, 34])]),
    ("VOL4", "4.3 第三轮 · 实现级差异总表与结论", [(3, [29, 30])]),
    ("VOL4", "4.4 第四轮 · 字段级差异总矩阵与结论", [(4, [18, 21])]),
]

# ===== 卷五：优化决策
PLAN += [
    ("VOL5", "5.1 优化路线：最适合用来优化 XEYO 的点（决策 A 全文）", [(6, list(range(0, 32)))]),
    ("VOL5", "5.2 高杠杆优化点收益评估（决策 B 全文）", [(7, list(range(0, 11)))]),
]

# ===== 附录
PLAN.append(("APPX", "附 A · 第四轮覆盖自检", [(4, [20])]))

# ---------------------------------------------------------------- 覆盖率校验
src_ranges = {}
assigned = {}
for doc, (_, secs, _) in DATA.items():
    for ix, s in enumerate(secs):
        src_ranges[(doc, ix)] = (s["start"], s["end"])

covered = set()
for _, _, srcs in PLAN:
    for doc, idxs in srcs:
        for ix in idxs:
            covered.add((doc, ix))

missing = [(d, ix, DATA[d][1][ix]["title"]) for (d, ix) in src_ranges if (d, ix) not in covered]
seen = set()
dupes = []
for _, _, srcs in PLAN:
    for doc, idxs in srcs:
        for ix in idxs:
            if (doc, ix) in seen:
                dupes.append((doc, ix))
            seen.add((doc, ix))

print("=== 覆盖率校验（按节） ===")
print(f"源节总数: {len(src_ranges)}   已分配: {len(covered)}   未分配: {len(missing)}   重复: {len(dupes)}")
for d, ix, t in missing:
    print(f"  [!] 未分配 R{d} idx={ix}  {t[:80]}")
assert not missing and not dupes, "存在未分配或重复分配的节 —— 合并中止"

print("OK：全部源节均已分配，零遗漏、零重复。")

# ---------------------------------------------------------------- 生成
VOL_TITLE = {
    "VOL1": "# 卷一 · 总纲：取证口径与更正沿革",
    "VOL2": "# 卷二 · 逐域完整对照（33 个域 × 四轮递进）",
    "VOL3": "# 卷三 · 机制设计说明（第五轮全文）",
    "VOL4": "# 卷四 · 差异总表与累计结论",
    "VOL5": "# 卷五 · 优化决策（路线 + 收益评估）",
    "APPX": "# 附录",
}
VOL_NOTE = {
    "VOL1": "五轮各自的取证方法、边界、以及每一轮推翻上一轮的具体条目。**读后面任何结论前先读这卷**——多轮结论存在迭代更正，以最新一轮为准。",
    "VOL2": "同一能力域下把五轮证据按 R1 功能 → R2 设计 → R3 实现 → R4 字段 的次序排开，可直接看出认识如何逐层变具体。",
    "VOL3": "第五轮全文。这一轮不再按能力域切，而是按「机制」切：同一道题两端各有解法，逐机制讲设计意图、不变量、算法步骤与失败路径。",
    "VOL4": "各轮的差异总表与结论段，集中排布便于纵向对比口径变化。",
    "VOL5": "两份决策文档全文：先给候选池与排序，再给收益/适配双维打分。",
    "APPX": "覆盖自检与源文档索引。",
}

spans_log = {}
out = []
out.append("# XEYO × DeepSeek Harness —— 五轮源码级考古 · 完整合集")
out.append("")
out.append("> **源文档 7 份 / 8,932 行 / 约 640 KB**，合并为单一文档。")
out.append("> 合并原则：**源文档每一节均被完整搬运，零删减、零改写**——仅标题层级按新结构降级 3 级、并在每块前标注出处（文档 + 原节 + 源行号）。")
out.append("> 校验：脚本对每个源文件的 `(start,end)` 行区间做**全覆盖断言**（恰好铺满 1..N，无空洞、无重叠），断言失败即中止生成。")
out.append("")
out.append("**卷结构**")
out.append("")
out.append("| 卷 | 内容 | 规模来源 |")
out.append("|---|---|---|")
out.append("| 卷一 | 总纲：取证口径与更正沿革 | R1–R4 的取证节 |")
out.append("| 卷二 | 逐域完整对照（33 域 × 4 轮） | R1–R4 主体 |")
out.append("| 卷三 | 机制设计说明 | R5 全文 |")
out.append("| 卷四 | 差异总表与累计结论 | R1–R4 总表/结论 |")
out.append("| 卷五 | 优化决策 | 决策 A + 决策 B 全文 |")
out.append("| 附录 | 覆盖自检 + 源文档索引 | — |")
out.append("")
out.append("---")
out.append("")
out.append("<!--INTRO_PLACEHOLDER-->")
out.append("")
out.append("---")
out.append("")

cur_vol = None
for kind, title, srcs in PLAN:
    if kind == "@INTRO":
        continue
    if kind != cur_vol:
        cur_vol = kind
        out.append("")
        out.append(VOL_TITLE[kind])
        out.append("")
        out.append(f"> {VOL_NOTE[kind]}")
        out.append("")
    out.append(f"## {title}")
    out.append("")
    for doc, idxs in srcs:
        emit_block(out, doc, idxs, spans_log)

# ===== 附录：源文档索引（程序生成，保证与源一致）
out.append("")
out.append("# 附录")
out.append("")
out.append("## 附 B · 源文档分节索引（自动生成）")
out.append("")
out.append("> 用途：反向定位。任意一条结论都能从这里查到它来自哪份文档的哪一节、原始行号是多少。")
out.append("")
for doc in sorted(DATA):
    lines, secs, total = DATA[doc]
    out.append(f"### R{doc} · {SHORT[doc]}")
    out.append("")
    out.append(f"路径 `{DOCS[doc]}` · 共 {total} 行 · {len(secs)} 节")
    out.append("")
    out.append("| # | 节标题 | 源行号 | 行数 |")
    out.append("|---|---|---|---|")
    for ix, s in enumerate(secs):
        t = s["title"].replace("|", "\\|")
        out.append(f"| {ix} | {t} | L{s['start']}–{s['end']} | {s['end']-s['start']+1} |")
    out.append("")

text = "\n".join(out)
target = ROOT / "docs" / "XEYO-vs-DeepSeekHarness-五轮合集.md"
target.write_text(text, encoding="utf-8")
print(f"\n生成完成：{target}")
print(f"行数 = {len(text.splitlines())}   字节 = {len(text.encode('utf-8'))}")

# ---------------------------------------------------------------- 行区间全覆盖断言
print("\n=== 行区间全覆盖断言 ===")
ok = True
for doc, (_, secs, total) in DATA.items():
    got = sorted(spans_log.get(doc, []))
    if not got:
        print(f"  [!] R{doc} 无任何搬运记录"); ok = False; continue
    merged = []
    for a, b in got:
        if merged and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    covered_lines = sum(b - a + 1 for a, b in merged)
    gap = []
    cur = 1
    for a, b in merged:
        if a > cur:
            gap.append((cur, a - 1))
        cur = max(cur, b + 1)
    if cur <= total:
        gap.append((cur, total))
    status = "OK" if (covered_lines == total and not gap) else "FAIL"
    if status == "FAIL":
        ok = False
    print(f"  R{doc}: 覆盖 {covered_lines}/{total} 行  区间块 {len(merged)} 个  空洞 {gap if gap else '无'}  -> {status}")
assert ok, "存在行区间空洞 —— 有内容未被搬运"
print("全部源文件行区间 100% 覆盖，零空洞、零重叠。")

print(f"\n源文档行数合计 = {sum(d[2] for d in DATA.values())}")
print(f"残留占位标记 = {len([l for l in text.splitlines() if 'APPEND-MARKER' in l])}")
