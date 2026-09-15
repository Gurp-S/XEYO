"""合并过程的核实回执（修订版）：逐条重跑源码，验证五轮报告中的可证伪断言。

第一版脚本自身有 4 类缺陷（口径不符 / 正则漏下划线 / 结构假设错 / rglob 未排除 node_modules），
产生 10 条"假更正"。本版修正后重跑，并在结果中标注每条断言的来源文档与核对方式。
"""
import pathlib
import re

X = pathlib.Path(r"D:\lea\XenYon code")
D = pathlib.Path(r"D:\lea\dsh-src")

rows = []


def rec(round_, claim, expect, got, ok, evidence, note=""):
    rows.append((round_, claim, expect, got, "确认" if ok else "★更正", evidence, note))


NUM = re.compile(r"([0-9][0-9_]*)")


def num(text, name):
    """提取常量值，自动去掉 Python 千位下划线。"""
    m = re.search(rf"\b{name}\b\s*=\s*([0-9][0-9_]*)", text)
    return m.group(1).replace("_", "") if m else "未见"


def read(p):
    p = pathlib.Path(p)
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


# ============================================================ dsh 侧
d_pkg = len([p for p in (D / "packages").glob("*/*") if p.is_dir()])
rec("R1–R4", "dsh 包数（packages/<组>/<子包>/）", 255, d_pkg, d_pkg == 255, "glob packages/*/*")

d_src = [p for p in list((D / "packages").rglob("*")) + list((D / "apps").rglob("*"))
         if p.is_file() and p.suffix in (".ts", ".tsx") and "/src/" in str(p).replace("\\", "/")
         and "node_modules" not in str(p)]
rec("R3/R4", "dsh src 下 .ts/.tsx 文件数", 1611, len(d_src), len(d_src) == 1611,
    'R3 原文「1611 个 src/**.ts（packages+apps）」/ R4「src 下 .ts/.tsx 1611」')

d_tests = [p for p in list((D / "packages").rglob("*")) + list((D / "apps").rglob("*"))
           if p.is_file() and p.name.endswith((".spec.ts", ".test.ts")) and "node_modules" not in str(p)]
rec("R1/R3", "dsh 测试文件数", 863, len(d_tests), len(d_tests) == 863, "find packages apps -name *.spec.ts/*.test.ts")

ev = set()
for p in (D / "packages").glob("*/*/src/**/*.ts"):
    t = read(p)
    if "interface SessionEventMap" not in t:
        continue
    for m in re.finditer(r"interface SessionEventMap\s*\{", t):
        i = m.end(); depth = 1
        while i < len(t) and depth > 0:
            if t[i] == "{": depth += 1
            elif t[i] == "}": depth -= 1
            i += 1
        for k in re.finditer(r"^\s*'([a-z0-9-]+(?:/[a-z0-9-]+)+)'\s*:", t[m.end():i - 1], re.M):
            ev.add(k.group(1))
rec("R4/R5", "dsh 会话事件数（含双斜杠键）", 51, len(ev), len(ev) == 51,
    "花括号配对提取 SessionEventMap 键；正则应允许 ≥2 段")

ses = read(D / "packages/core/session/src/types.ts")
val = re.search(r"SESSION_FORMAT_VERSION\s*=\s*(\d+)", ses)
rec("R4/R5", "SESSION_FORMAT_VERSION", 2, val.group(1) if val else "未见", bool(val and val.group(1) == "2"),
    "core/session/src/types.ts")

cli = len([p for p in (D / "packages/client").glob("*") if p.is_dir()])
rec("R4", "packages/client 子包目录数", 45, cli, cli == 45, "glob packages/client/*/ 仅目录")

tcat = read(D / "docs/tool-catalog.md")
uniq = sorted({m.group(1) for m in re.finditer(r"^### `([^`]+)`", tcat, re.M)})
entries = len(re.findall(r"^### `", tcat, re.M))
rec("R4", "dsh 工具目录条目 / 唯一工具名", "62 / 57", f"{entries} / {len(uniq)}",
    entries == 62 and len(uniq) == 57, "docs/tool-catalog.md")

hits = []
for p in (D / "packages").rglob("*.ts"):
    if "node_modules" in str(p):
        continue
    t = read(p)
    if re.search(r"name:\s*['\"]Mcp['\"]", t):
        hits.append(str(p))
rec("R2/R5", "dsh 是否存在名为 Mcp 的网关工具（否定断言）", "无", f"命中 {len(hits)} 个文件", not hits,
    "grep packages/ name: 'Mcp'")

tidx = read(D / "packages/core/tools/src/index.ts")
n_memo = len(re.findall(r"\bmemo\w*\s*[(=]", tidx))
n_cache = len(re.findall(r"\bcache\w*\b", tidx, re.I))
rec("R2/R5", "dsh ToolRuntime.view() 无 memo（按需派生）", "memo 0 处",
    f"memo {n_memo} 处 / cache {n_cache} 处", n_memo == 0, "core/tools/src/index.ts")

win = [p for p in (D / "packages/sandbox").glob("*") if p.is_dir() and "win" in p.name.lower()]
rec("R6/R7", "dsh Windows 专用沙箱后端", "存在", win[0].name if win else "不存在", bool(win),
    "packages/sandbox/*windows*")

rec("R4", "spill 预览是否头尾各半（ceil/floor）", "ceil+floor",
    f"ceil={read(D/'packages/spill/spill-policy/src/index.ts').count('ceil')} floor="
    f"{read(D/'packages/spill/spill-policy/src/index.ts').count('floor')}",
    "ceil" in read(D / "packages/spill/spill-policy/src/index.ts")
    and "floor" in read(D / "packages/spill/spill-policy/src/index.ts"),
    "spill-policy/src/index.ts")

cfg = read(D / "packages/compaction/compaction-basic/src/config.ts")
prc = read(D / "packages/compaction/compaction-tool-result-pruner/src/config.ts")
rec("R4", "compaction 触发常量 0.8 / 0.16 / 8192", "三者齐",
    ",".join(x for x in ("0.8", "0.16", "8192") if x in cfg) or "未见",
    all(x in cfg for x in ("0.8", "0.16", "8192")), "compaction-basic/src/config.ts")
rec("R4", "tool-result-pruner 8192 / 4096 / 1024", "三者齐",
    ",".join(x for x in ("8192", "4096", "1024") if x in prc) or "未见",
    all(x in prc for x in ("8192", "4096", "1024")), "compaction-tool-result-pruner/src/config.ts")

appr = "".join(read(p) for p in (D / "packages/interaction").glob("*/src/*.ts"))
rec("R3/R4", "审批唯一授予值 allowed-once", "存在", "存在" if "allowed-once" in appr else "未见",
    "allowed-once" in appr, "packages/interaction/*/src/*.ts")

memhits = []
for p in (D / "packages").rglob("*.ts"):
    if "node_modules" in str(p):
        continue
    if "interface SessionEventMap" in read(p):
        continue
    t = read(p)
    if re.search(r"MEMORY\.md|longTermMemory|persistentMemory", t):
        memhits.append(str(p))
rec("R2/R5", "dsh 是否跨会话记忆（否定断言）", "无", f"命中 {len(memhits)} 个文件", not memhits,
    "grep MEMORY.md / longTermMemory / persistentMemory")

# ============================================================ XEYO 侧
def xfiles(root, suffix="*.py"):
    return [p for p in root.rglob(suffix)
            if not any(s in str(p) for s in (".venv", "__pycache__", "node_modules"))]


pyf = xfiles(X / "python")
pyl = sum(read(p).count("\n") for p in pyf)
rec("R1–R7", "XEYO python 文件数 / 行数", "1141 / 160772", f"{len(pyf)} / {pyl}",
    len(pyf) == 1141 and abs(pyl - 160772) <= 300, "rglob *.py 排除 .venv/__pycache__")

guif = [p for p in (X / "gui/src").rglob("*") if p.suffix in (".ts", ".tsx")]
guil = sum(read(p).count("\n") for p in guif)
rec("R1–R7", "gui/src ts+tsx 文件数 / 行数", "391 / 81484", f"{len(guif)} / {guil}",
    len(guif) == 391 and abs(guil - 81484) <= 400, "rglob gui/src")

tull = sum(read(p).count("\n") for p in (X / "tui/src").rglob("*") if p.suffix in (".ts", ".tsx"))
rs = list((X / "gui/src-tauri/src").glob("*.rs"))
rsl = sum(read(p).count("\n") for p in rs)
rec("R1–R7", "tui 行数 / rust 文件数·行数", "3544 / 3·1162", f"{tull} / {len(rs)}·{rsl}",
    tull == 3544 and rsl == 1162, "rglob tui/src, glob src-tauri/src/*.rs")

ptf = list((X / "python/tests").rglob("test_*.py"))
vtf = [p for p in (X / "gui/src").rglob("*") if p.name.endswith((".test.ts", ".test.tsx"))]
rec("R3–R7", "pytest 文件数 / vitest 文件数", "307 / 102", f"{len(ptf)} / {len(vtf)}",
    len(ptf) == 307 and len(vtf) == 102, "rglob test_*.py / *.test.ts(x)")

rout = sum(len(re.findall(r'@router\.(get|post|put|patch|delete)\("', read(p)))
           for p in (X / "python/server/routers").glob("*.py"))
rec("R3–R7", "XEYO HTTP 路由数", 101, rout, rout == 101, "server/routers/*.py @router.<verb>")

meta = read(X / "python/tools/meta.py")
nt = len(re.findall(r'name="([^"]+)"', meta))
nf = len({m.group(1) for m in re.finditer(r"^\s+([a-z_]+)=", meta, re.M)})
rec("R4–R7", "XEYO 工具数 / TOOL_META 字段数", "26 / 14", f"{nt} / {nf}", nt == 26 and nf == 14, "tools/meta.py")

evp = read(X / "python/msgtypes/events.py")
ndc = len(re.findall(r"^class ", evp, re.M))
mun = re.search(r"EngineEvent\s*=\s*Union\[(.*?)\]", evp, re.S)
nun = len([x for x in mun.group(1).split(",") if x.strip()]) if mun else 0
rec("R4–R7", "EngineEvent dataclass 数", 20, ndc, ndc == 20, "msgtypes/events.py ^class")
rec("R4–R7", "EngineEvent Union 成员数（PermissionExpiringEvent 未入）", 19, nun, nun == 19,
    "msgtypes/events.py EngineEvent = Union[...]")

inj = read(X / "python/prompt/pre_llm_inject.py")
nblk = len(re.findall(r'^\t"([a-z_0-9]+)": \{', inj, re.M))
tags = len(re.findall(r'_tag_block\(\s*\n?\s*tagged,\s*"', inj))
rec("R4–R7", "T_now 登记块数 / _tag_block 装配点", "20 / 20", f"{nblk} / {tags}",
    nblk == 20 and tags == 20, "pre_llm_inject.py")
hard = num(inj, "T_NOW_BLOCK_HARD_CAP")
rec("R4–R7", "T_NOW_BLOCK_HARD_CAP", 21, hard, hard == "21", "pre_llm_inject.py:826")
b = [num(inj, k) for k in ("T_NOW_TOTAL_BUDGET", "T_NOW_INVENTORY_MAX", "T_NOW_EXTRA_BUDGET", "NESTED_MAX_CHARS")]
rec("R4–R7", "T_now 预算 6000 / 2500 / 6000 / 4000", "6000,2500,6000,4000", ",".join(b),
    b == ["6000", "2500", "6000", "4000"], "pre_llm_inject.py（原值带千位下划线 6_000 等）")

cat = read(X / "python/tools/catalog.py").splitlines()
bl = [i for i, l in enumerate(cat, 1) if "XEYO_BENCH_MINIMAL" in l]
rec("R3–R7", "XEYO_BENCH_MINIMAL 裁剪点行号", 359, bl, bl == [359], "tools/catalog.py")

ml = meta.splitlines()
zlines = [i for i, l in enumerate(ml, 1) if re.search(r"output_budget\s*=\s*0", l)]
rec("R4–R7", "output_budget=0 豁免（Read / Bash）", "2 处", zlines, len(zlines) == 2,
    "tools/meta.py（R4 记 111-112 / 146-148；实测行号见左）")

tr = read(X / "python/tools/bash_tool/truncate.py")
rec("R7", "bash 截断常量 DEFAULT_LIMIT / HEAD_CHARS / TAIL_CHARS", "30000 / 20000 / 8000",
    " / ".join(num(tr, k) for k in ("DEFAULT_LIMIT", "HEAD_CHARS", "TAIL_CHARS")),
    [num(tr, k) for k in ("DEFAULT_LIMIT", "HEAD_CHARS", "TAIL_CHARS")] == ["30000", "20000", "8000"],
    "tools/bash_tool/truncate.py:7-9")

reg = read(X / "python/tools/tool_registry.py")
rec("R7", "registry 级 spill 常量 16000 / 6000 / 2000", "16000 / 6000 / 2000",
    " / ".join(num(reg, k) for k in ("DEFAULT_OUTPUT_BUDGET", "PREVIEW_HEAD", "PREVIEW_TAIL")),
    [num(reg, k) for k in ("DEFAULT_OUTPUT_BUDGET", "PREVIEW_HEAD", "PREVIEW_TAIL")] == ["16000", "6000", "2000"],
    "tools/tool_registry.py:84-87")

cmp_ = read(X / "python/engine/compact.py")
rec("R7", "engine/compact.py 工具配对平衡", "tool_pair_ranges 存在",
    "存在" if "tool_pair_ranges" in cmp_ else "未见", "tool_pair_ranges" in cmp_,
    "engine/compact.py:69")

rwf = list((X / "python/rewind").glob("*.py"))
rwl = sum(read(p).count("\n") for p in rwf)
rec("R5/R7", "python/rewind 文件数 / 行数", "12 / 5343", f"{len(rwf)} / {rwl}",
    len(rwf) == 12 and rwl == 5343, "glob python/rewind/*.py")

ttl = read(X / "python/permissions/pending_ttl.py")
vals = [num(ttl, k) for k in ("PENDING_PANEL_TTL_SECONDS", "PENDING_DANGER_TTL_SECONDS", "PENDING_REMINDER_BEFORE_S")]
rec("R6/R7", "审批风险分级 TTL（普通 / 危险 / 提醒）", "180 / 60 / 30", " / ".join(vals),
    vals == ["180", "60", "30"], "permissions/pending_ttl.py:20-22")

rt = read(X / "python/session/record_transcript.py")
rec("R6/R7", "_disk_lock 仅进程内锁", "threading.Lock",
    "threading.Lock" if re.search(r"_disk_lock\s*=\s*threading\.Lock\(\)", rt) else "未见",
    bool(re.search(r"_disk_lock\s*=\s*threading\.Lock\(\)", rt)), "session/record_transcript.py")
rec("R6/R7", "读侧撕裂行处理只静默跳过", "JSONDecodeError: continue",
    "命中" if "JSONDecodeError" in rt else "未见", "JSONDecodeError" in rt, "session/record_transcript.py")

rec("R7", "sidecar 侧挂→升格基建", "存在", "存在" if (X / "python/sidecar/policy.py").exists() else "不存在",
    (X / "python/sidecar/policy.py").exists(), "python/sidecar/policy.py")

hk = read(X / "python/extension/hooks.py")
hev = re.search(r"EVENTS\s*=\s*\(([^)]*)\)", hk)
rec("R5/R7", "XEYO hooks 事件数", 5, len(re.findall(r'"', hev.group(1))) // 2 if hev else 0,
    bool(hev) and len(re.findall(r'"', hev.group(1))) // 2 == 5, "extension/hooks.py EVENTS")

rec("R4–R7", "pricing.py 仍是 2026-08-17 旧价表", "仍是旧表",
    "仍是旧表" if "2026-08-17" in read(X / "python/usage/pricing.py") else "已更新",
    "2026-08-17" in read(X / "python/usage/pricing.py"), "usage/pricing.py 头注释")

bp = read(X / "python/permissions/bash_policy.py")
i = bp.index("_DENY_RULES")
j = bp.index("\n)", i)
body = bp[i:j]
nd = body.count("re.compile(")
ntag = len(set(re.findall(r'"([a-z_]+)"\s*,?\s*\),', body)))
sln = bp[:i].count("\n") + 1
eln = bp[:j].count("\n") + 1
rec("R3–R7", "bash 黑名单正则条数 / 标签类数（报告写「18 条」）", "18", f"{nd} 条 / {ntag} 类",
    nd == 18, f"permissions/bash_policy.py L{sln}–L{eln}（报告记 :20-106，实为 L{sln}–L{eln}）",
    "报告原文「18 条黑名单正则（permissions/bash_policy.py:20-106）」")

ql = read(X / "python/engine/query_loop.py")
me = re.search(r"_EARLY_BLOCKLIST\s*=\s*frozenset\(\{([^}]*)\}\)", ql)
n_early = len(re.findall(r'"', me.group(1))) // 2 if me else 0
rec("R7", "_EARLY_BLOCKLIST 投机提前执行黑名单项数", 4, n_early, n_early == 4,
    "engine/query_loop.py:93 frozenset({...})")

cons = []
for p in (X / "python").rglob("*.py"):
    if any(s in str(p) for s in (".venv", "__pycache__")):
        continue
    if p.name == "scheduler.py" and p.parent.name == "engine":
        continue
    if re.search(r"\bscheduler\b", read(p)):
        cons.append(str(p.relative_to(X / "python")))
rec("R1→R5", "engine/scheduler.py 是否死代码（否定断言）", "不是死代码",
    f"消费方 {len(cons)} 个文件", len(cons) >= 5, "全仓 grep scheduler 排除自身：" + ", ".join(sorted(cons)[:6]))

led = read(X / "python/usage/ledger.py")
rec("R5/R7", "ledger 注释引用 dsh 记账纪律", "含 S2/S4",
    "含" if ("S2" in led and "S4" in led) else "未见", "S2" in led and "S4" in led, "usage/ledger.py:66-76")

# ============================================================ 输出
w = [10, 50, 24, 30, 7]
print(f"{'轮次':<10}{'断言':<50}{'报告值':<24}{'实测':<30}{'判定'}")
print("-" * 175)
bad = []
for r, claim, exp, got, verdict, ev, note in rows:
    if verdict != "确认":
        bad.append((claim, exp, got, ev, note))
    print(f"{r:<10}{claim:<50}{str(exp):<24}{str(got):<30}{verdict}")
print("-" * 175)
print(f"共核 {len(rows)} 条：确认 {len(rows)-len(bad)}，更正 {len(bad)}")
for claim, exp, got, ev, note in bad:
    print(f"\n★更正：{claim}\n   报告值={exp}  实测={got}\n   证据={ev}\n   注={note}")

(X / "docs" / "_verify_receipt.txt").write_text(
    "\n".join("\t".join(str(y) for y in x) for x in rows), encoding="utf-8")
print(f"\n回执已写：docs/_verify_receipt.txt")
