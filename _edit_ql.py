import sys
p = "engine/query_loop.py"
s = open(p, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
print("newline:", repr(nl))
lines = s.split(nl) if nl in s else s.split("\n")

def find(pred, start=0, end=None):
    end = len(lines) if end is None else end
    for i in range(start, end):
        if pred(lines[i]):
            return i
    return -1

# ---- edits 1..3: single-line call sites ----
reps = []
i = find(lambda l: "guard_action = repeat_guard.observe(tu.name, tu.input)" in l)
assert i >= 0, "guard_action site not found"
reps.append((i, [
"            guard_action = safe_observe(",
"                repeat_guard.observe, tu.name, tu.input,",
'                label="RepeatCallGuard.observe",',
"            )",
]))

i = find(lambda l: l.strip() == "loop_ledger.observe_assistant(assistant_text)")
assert i >= 0, "observe_assistant site not found"
reps.append((i, [
"        safe_observe(",
"            loop_ledger.observe_assistant, assistant_text,",
'            label="LoopLedger.observe_assistant",',
"        )",
]))

i = find(lambda l: "distinct_zero = zero_hit_tracker.record(tu.name, tu.input)" in l)
assert i >= 0, "zero_hit_tracker site not found"
reps.append((i, [
"                distinct_zero = safe_observe(",
"                    zero_hit_tracker.record, tu.name, tu.input,",
'                    label="ZeroHitTracker.record", default=0,',
"                )",
]))

# ---- edit 4: observe_tool block ----
anchor = find(lambda l: "loop_ledger.observe_tool(" in l)
assert anchor >= 0, "observe_tool not found"
# find the try: immediately above, then skip the comment block above it
diag_try = -1
for k in range(anchor, 0, -1):
    if lines[k].strip() == "try:":
        diag_try = k
        break
assert diag_try >= 0
c = diag_try - 1
while c > 0 and lines[c].lstrip().startswith("#"):
    c -= 1
comment_start = c + 1
# find the fold try: after the anchor
fold_try = -1
for k in range(anchor, len(lines) - 1):
    if lines[k].strip() == "try:" and 'if not getattr(result, "images", None):' in lines[k + 1]:
        fold_try = k
        break
assert fold_try >= 0, "fold try not found"
reps.append((comment_start, fold_try, [
"            # 诊断采集与防护动作**分属两条独立路径**：账本是诊断（失败只剩少",
"            # 一行数据），折叠是防护（失败即空转失去止血阀）。任何“共用一个",
"            # try”的写法都会让诊断侧异常连带打死折叠——2026-09-14 事故",
"            # （params_digest 传了原始 dict → TypeError → [fold] 全域失效）。",
"            # 观测统一经 safe_observe 隔离；折叠单独 try / fail-open 保留原文。",
"            # 行为账本：s1/s2 信号采集（纯计数，无副作用；豁免集在 LoopLedger",
"            # 内部处理）。fold 判定与其独立、互不影响。params_digest 只存摘要",
"            # （锚点报“参数变体种数”用）。",
"            safe_observe(",
"                loop_ledger.observe_tool,",
"                tu.name,",
"                out_content,",
'                label="LoopLedger.observe_tool",',
'                params_digest=params_digest(getattr(tu, "input", None)),',
"            )",
"            try:",
]))

# apply from bottom to top
opens = [r[0] for r in reps]
if len(set(opens)) != len(opens):
    print("overlapping edits"); sys.exit(1)
for r in sorted(reps, key=lambda x: x[0], reverse=True):
    start = r[0]
    end = r[1] if len(r) == 3 else r[0]
    new = r[2] if len(r) == 3 else r[1]
    lines[start:end + 1] = new

# ---- edit 0: import ----
imp = find(lambda l: l.strip() == "from engine.loop_ledger import LoopLedger, params_digest")
assert imp >= 0, "import anchor not found"
lines.insert(imp + 1, "from engine.observe_safety import safe_observe")

open(p, "w", encoding="utf-8", newline="").write(nl.join(lines))
print("edits applied; total lines:", len(lines))
