"""WSC miss 普查（**只读账本，零 API**）：把每一枪的 miss 归到四类，并给出"长对话"口径。

## 判据（第一性）

    命中率 ≡ 1 − miss/prompt，  miss_i = 新增_i + 重发_i，  新增_i = max(0, prompt_i − prompt_{i−1})

- **新增** = 本枪必须写进 KV 的新 token，**不可回收**（用户裁定的"必须 miss"）；
- **重发** = 发过却没命中，**可回收**；按当枪 action 再分：
  `C2` ⇒ 折叠重写；每会话第一枪 ⇒ 并入新增；**同 sid 下 `conv` 重置 ⇒ 按「新对话首枪」并入新增
  并单列计数**（10-04 深夜守卫：纪元边界两枪无前缀关系，不守卫会把整段 miss 误记进重发）；
  `p` 下降且非 C2 ⇒ `unexplained_drop`（历史被原地改写的形态；10-05 结案的三族见
  `_wsc_out/_register.md`「未解释下落桶结案」：glm 家族 / 首枪嗅探块消失 / 旧纪元非尾部易变块改写）；
  其余 ⇒ `other_resend`。

## ⚠️ 家族切分（2026-10-04 实测教训，必须遵守）

同一条会话里可能混着不同 (provider, model) 的请求（辅助调用 / 多模型切档）。
跨家族相邻枪的"重发"是**假重发**：实测 `glm-4.6v` 的缓存命中恒为 43 token，
在旧口径下它把"其它重发"灌到 78% of miss。⇒ **相邻枪只在同 (sid, provider, model) 内比较**，
四桶与所有派生切分都必须在家族内算。

## 口径（写死在这里，避免每次口头换）

- 只统计 `prompt_tokens > 0` 的枪；空 sid 行单独计数、不进任何比例；
- "长对话段" = `prompt ≥ --long`（默认 64000）；报该段 Σhit/Σprompt；
- **天花板** = 1 − Σ新增/Σprompt（零重写时的最好情况），必须与命中率并列报，
  防止用"分母变大"刷分。

用法::

    py -3.11 python/scripts/wsc_miss_census.py [--since 2026-09-25] [--long 64000] [--dump 12] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:  # 编码地雷：无 UTF-8 环境时 Windows 控制台是 GBK
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

DEFAULT_LONG = 64_000
AGE_EDGES = ((0, 60), (60, 300), (300, 900), (900, 3600), (3600, 10**9))
SIZE_BUCKETS = ((0, 257), (257, 1024), (1024, 4096), (4096, 12000), (12000, 16000), (16000, 10**9))


def _usage_dir() -> Path:
    import os

    override = (os.environ.get("XEYO_USAGE_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    home = (os.environ.get("XEYO_HOME") or "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".xeyo"
    return base / "usage"


def _rows(name: str, since: str | None):
    path = _usage_dir() / name
    if not path.is_file():
        return []
    out = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
            try:
                r = json.loads(raw)
            except Exception:
                continue
            if since and str(r.get("day") or "") < since:
                continue
            out.append(r)
    return out


def _bucket(edges, value: float, *, inf_label: str = "inf") -> str:
    for lo, hi in edges:
        if lo <= value < hi:
            return f"{lo}-{inf_label if hi >= 10**8 else hi}"
    return "?"


def _add(box: Counter, key: str, value: float) -> None:
    box[key] += value


def census(live: list[dict], long_at: int):
    """返回 (per_family, per_sid, extra)。相邻枪只在 (sid, provider, model) 内比较。"""
    by_fam: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in live:
        sid = str(r.get("session_id") or "")
        if sid:
            by_fam[(sid, str(r.get("provider") or "-"), str(r.get("model") or "-"))].append(r)
    for rows in by_fam.values():
        rows.sort(key=lambda x: float(x.get("ts") or 0))

    per_family: dict[tuple[str, str], Counter] = defaultdict(Counter)
    per_sid: dict[str, Counter] = defaultdict(Counter)
    per_key: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    extra = {
        "resend_age": Counter(), "resend_intact": Counter(), "resend_action": Counter(),
        "resend_action_shots": Counter(), "resend_size": Counter(), "resend_big": Counter(),
        "sess_min": {}, "long": Counter(), "big_rows": [], "epoch_boundary": 0,
    }
    for (sid, prov, model), rows in by_fam.items():
        fam = per_family[(prov, model)]
        sidc = per_sid[sid]
        keyc = per_key[(sid, prov, model)]
        prev_prompt = None
        prev_row = None
        prev_conv = None
        for r in rows:
            p = int(r.get("prompt_tokens") or 0)
            h = int(r.get("observed_hit") or 0)
            lcp = int(r.get("LCP") or 0)
            age = float(r.get("cache_age") or 0)
            action = str(r.get("action") or "")
            _cr = r.get("conversation_length")
            conv = int(_cr) if _cr is not None else None
            # 纪元边界守卫（10-04 深夜补）：同 sid 下 conv 重置（下降）⇒ 上一枪属于另一段对话，
            # 两枪之间没有前缀关系。不守卫的后果有实测形态：新纪元首枪 p 比上一枪小 ⇒ new≈0
            # ⇒ 整段 miss 被误记进"重发"桶（R8 残渣"纪元重置 4 枪 67,688"即此形态）。
            # 处置：按「本对话首枪」算——new=p（整段都是新内容），resend 自然 0，另单列计数。
            epoch_reset = prev_conv is not None and conv is not None and conv < prev_conv
            miss = max(0, p - h)
            if prev_prompt is None or epoch_reset:
                new = min(p, miss)          # 首枪 / 新纪元首枪：没有可期待的前缀
            else:
                new = min(max(0, p - prev_prompt), miss)
            resend = miss - new
            for box in (fam, sidc, keyc):
                _add(box, "shots", 1)
                _add(box, "prompt", p)
                _add(box, "hit", h)
                _add(box, "miss", miss)
                _add(box, "new", new)
            if prev_prompt is None:
                for box in (sidc, fam, keyc):
                    _add(box, "cold_start", resend)
            elif epoch_reset:
                extra["epoch_boundary"] += 1
                for box in (sidc, fam, keyc):
                    _add(box, "epoch_boundary", 1)
            elif action == "C2":
                for box in (sidc, fam, keyc):
                    _add(box, "fold_rewrite", resend)
            elif p < prev_prompt - 1 and resend > 0:
                for box in (sidc, fam, keyc):
                    _add(box, "unexplained_drop", resend)
            else:
                for box in (sidc, fam, keyc):
                    _add(box, "other_resend", resend)
                extra["resend_age"][_bucket(AGE_EDGES, age)] += resend
                # 分档线看**本枪**的引擎自算 LCP（当前跃迁），不是上一枪的：
                # 旧实现用 prev_lcp 对 previous prompt，把每行按"它的前一跃迁"分类（off-by-one）。
                intact = lcp >= 0.7 * max(1, prev_prompt)
                extra["resend_intact"]["lcp_intact" if intact else "prefix_broken"] += resend
                extra["resend_action"][action] += resend
                extra["resend_action_shots"][action] += 1
                extra["resend_size"][_bucket(SIZE_BUCKETS, resend)] += 1
                extra["resend_big"]["big" if resend > 4096 else "small"] += resend
                if resend > 4096:
                    extra["big_rows"].append((int(resend), sid, prev_row, r))
            if p >= long_at:
                for k, v in (("shots", 1), ("prompt", p), ("hit", h), ("miss", miss), ("new", new)):
                    _add(extra["long"], k, v)
            if prev_prompt is not None and action != "C2":
                extra["sess_min"].setdefault(sid, []).append(max(0, prev_prompt - h))
            prev_prompt = p
            prev_row = r
            if conv is not None:
                prev_conv = conv
    return per_family, per_sid, extra, by_fam, per_key


def main() -> int:
    ap = argparse.ArgumentParser(description="WSC miss 四桶普查（只读）")
    ap.add_argument("--since", default=None, help="只统计 day >= 该日期（YYYY-MM-DD）")
    ap.add_argument("--long", type=int, default=DEFAULT_LONG, help="长对话阈值 prompt_tokens")
    ap.add_argument("--json", default=None, help="把结果落成 JSON 便于复跑比对")
    ap.add_argument("--top", type=int, default=8, help="打印最脏的会话数")
    ap.add_argument("--dump", type=int, default=0, help="列出单枪重发最大的 N 枪（含 LCP）")
    ap.add_argument("--nofold", action="store_true",
                    help="附加「水位政策臂」：只有 prompt 会越过 W 才折（W 取 --watermark，"
                         "默认 200k/500k/800k 三档）；低水位的折叠全部推迟")
    ap.add_argument("--watermark", type=int, nargs="*", default=None, help="水位政策臂的 W 值（token）")
    ap.add_argument("--window", type=int, default=1_000_000, help="判定越窗用的上下文窗口")
    ap.add_argument("--model", default=None, help="只看 model 名含该子串的家族（如 deepseek-v4.1）")
    args = ap.parse_args()

    calib = _rows("calibration_events.jsonl", args.since)
    live = [r for r in calib if int(r.get("prompt_tokens") or 0) > 0]
    if args.model:
        live = [r for r in live if args.model in str(r.get("model") or "")]
    zero = len(calib) - len(live)
    per_family, per_sid, extra, by_fam, per_key = census(live, args.long)
    tot = Counter()
    for c in per_sid.values():
        tot.update(c)

    def rate(c: Counter) -> str:
        return f"{c['hit'] / c['prompt']:.4f}" if c["prompt"] else "-"

    print(f"# WSC miss 普查  since={args.since or 'ALL'}  long>={args.long:,}")
    print(f"账本行={len(calib)}  有效枪={len(live)}  零用量行={zero}  "
          f"会话={len(per_sid)}  家族={len(per_family)}")
    # ⚠️ 口径守卫（10-04 实测教训）：账本的 `ts` 可能乱序、同一 sid 混多个纪元
    # （实测 `conv` 在 ts 序里不单调 ⇒ 相邻两枪来自不同上下文流 ⇒ **造出假的重发**）。
    # 命中率是简单求和、不受排序影响；受影响的是**逐枪桶分解**。
    _nonmono = []
    for _sid, _rs in by_fam.items():
        _key = _sid[0]
        _convs = [int(r.get("conversation_length") or 0) for r in _rs]  # by_fam 内已按 ts 排好
        if any(_convs[i] > _convs[i + 1] for i in range(len(_convs) - 1)):
            _nonmono.append((_key, len(_rs)))
    _nonmono = list(dict.fromkeys(_nonmono))
    if _nonmono:
        _n = sum(n for _, n in _nonmono)
        print(f"  ⚠️ ts 序非单调（混纪元）的会话 {len(_nonmono)} 个 / {_n} 枪 ⇒ **逐枪桶分解对它们无效**"
              f"（命中率仍有效）。示例：" +
              " | ".join(f"{k[:22]}（{n} 枪）" for k, n in sorted(_nonmono, key=lambda x: -x[1])[:3]))
    if extra["epoch_boundary"]:
        print(f"  ⚠️ 纪元边界枪（同 sid 下 conv 重置）：{extra['epoch_boundary']} 枪已按「新对话首枪」"
              f"归入新增（new=p），不计任何重发桶——防止整段 miss 被误记为重发")
    if not tot["prompt"]:
        print("没有可用数据")
        return 0

    print()
    print("## 按 (provider, model) 家族（相邻枪只在家族内比较）")
    print(f"{'provider/model':40s} {'枪':>6s} {'Σprompt':>12s} {'命中率':>7s} {'新增占miss':>10s} "
          f"{'折叠占miss':>10s} {'其它占miss':>10s} {'天花板':>8s}")
    for k in sorted(per_family, key=lambda k: -per_family[k]["prompt"]):
        c = per_family[k]
        if not c["prompt"]:
            continue
        miss = max(1, c["miss"])
        print(f"{f'{k[0]}/{k[1]}'[:40]:40s} {c['shots']:>6d} {c['prompt']:>12,} {c['hit']/c['prompt']:>7.4f} "
              f"{c['new']/miss:>10.1%} {c['fold_rewrite']/miss:>10.1%} {c['other_resend']/miss:>10.1%} "
              f"{1-c['new']/c['prompt']:>8.4f}")

    print()
    print("## 全体（家族内相邻口径）")
    print(f"  枪={tot['shots']}  Σprompt={tot['prompt']:,}  命中率={rate(tot)}  Σmiss={tot['miss']:,}")
    print(f"  miss 构成：新增 {tot['new']:,} ({tot['new']/tot['miss']:.1%}) | "
          f"折叠重写 {tot['fold_rewrite']:,} ({tot['fold_rewrite']/tot['miss']:.1%}) | "
          f"其它重发 {tot['other_resend']:,} ({tot['other_resend']/tot['miss']:.1%}) | "
          f"未解释下落 {tot['unexplained_drop']:,} ({tot['unexplained_drop']/tot['miss']:.1%})")
    print(f"  天花板（零重写）= 1 − 新增/prompt = {1 - tot['new']/max(1, tot['prompt']):.4f}")
    rec = tot["fold_rewrite"] + tot["other_resend"] + tot["unexplained_drop"]
    print(f"  可回收 miss = {rec:,} ({rec/tot['miss']:.1%} of miss)")
    if extra["resend_age"]:
        print("  「其它重发」按空闲时长：" + " | ".join(f"{k} {v:,}" for k, v in sorted(extra["resend_age"].items())))
    if extra["resend_intact"]:
        print("  「其它重发」按引擎自算前缀：" + " | ".join(f"{k} {v:,}" for k, v in sorted(extra["resend_intact"].items())))
    if extra["resend_action"]:
        print("  「其它重发」按当枪 action："
              + " | ".join(f"{a}: {extra['resend_action'][a]:,} tok / {extra['resend_action_shots'][a]} 枪"
                           for a in sorted(extra["resend_action"], key=lambda a: -extra["resend_action"][a])))
    if extra["resend_size"]:
        print("  「其它重发」按单枪量分桶（枪数）："
              + " | ".join(f"{k}:{v}" for k, v in sorted(extra["resend_size"].items(),
                                                        key=lambda kv: int(kv[0].split("-")[0]))))
        big, small = extra["resend_big"]["big"], extra["resend_big"]["small"]
        print(f"  总量切分：单枪>4096 的偶发大块 {big:,}（{big/max(1,big+small):.1%}） | "
              f"单枪≤4096 的小量 {small:,}（{small/max(1,big+small):.1%}）")
    mins = [(sid, min(v), sorted(v)[len(v)//2], len(v)) for sid, v in extra["sess_min"].items() if len(v) >= 5]
    if mins:
        heavy = [x for x in mins if x[1] > 2048]
        print(f"  会话级最小重发 >2048 的会话 = {len(heavy)}/{len(mins)}"
              "（这些会话每一枪都在重发 ≥2k ⇒ 形态=固定段/历史每枪被改写）")
        for sid, mn, md, n in sorted(heavy, key=lambda x: -x[1])[:5]:
            print(f"    {sid[:24]:24s} 最小={mn:,} 中位={md:,} 枪={n}")

    lg = extra["long"]
    if lg["prompt"]:
        print()
        print(f"## 长对话段（prompt ≥ {args.long:,}）")
        print(f"  枪={lg['shots']}  Σprompt={lg['prompt']:,}  命中率={rate(lg)}  "
              f"新增占该段 miss {lg['new']/max(1,lg['miss']):.1%}  天花板={1-lg['new']/lg['prompt']:.4f}")

    # 桶分解的有效域：只算 ts 单调（单纪元）的会话
    _bad = {k for k, _n in _nonmono}
    mono_tot = Counter()
    for (sid, _p, _m), c in per_key.items():
        if sid not in _bad:
            mono_tot.update(c)
    if mono_tot["prompt"]:
        m = max(1, mono_tot["miss"])
        print()
        print(f"## 桶分解（**仅 ts 单调会话**：{len([k for k in per_key if k[0] not in _bad])} 会话 / {mono_tot['shots']} 枪）")
        print(f"  命中率={mono_tot['hit']/mono_tot['prompt']:.4f}  新增={mono_tot['new']/m:.1%} "
              f"折叠重写={mono_tot['fold_rewrite']/m:.1%} 其它重发={mono_tot['other_resend']/m:.1%} "
              f"未解释={mono_tot['unexplained_drop']/m:.1%}  天花板={1-mono_tot['new']/mono_tot['prompt']:.4f}")
        print("  （全量表里的桶分解含混纪元会话，**仅供参考**；命中率与天花板是求和、不受影响）")

    if args.nofold:
        # ⚠️ 「不折」不是可落地政策：把折叠量一直补回去，峰值会顶穿窗口
        # （实测 since 09-25：峰值上界 1,643,431 > 1M 窗口）⇒ 那个 99.66% 只是
        # **上界**，不是可达数。可落地的是「水位政策」：只有 prompt 会越过 W 时才折。
        # 记账（两处已标注的乐观近似）：
        #   · 推迟的折叠：其内容继续留在上下文（offset 累加），且**不发生**它的 miss；
        #   · 允许的折叠：沿用实测那一枪的 miss（忽略"这次压得更多 ⇒ 头增量更大"，
        #     方向=乐观）；折后 offset 归零，基线沿用实测折后值。
        arms = args.watermark or [200_000, 500_000, 800_000]
        print()
        print("## 水位政策臂（只有 prompt 会越过 W 才折；低水位的折叠全部推迟）")
        print(f"{'W':>9s} {'Σprompt':>14s} {'Σmiss':>12s} {'命中率':>8s} "
              f"{'折(留/推)':>11s} {'峰值':>12s} {'越窗枪':>8s}")
        print(f"{'实测':>9s} {tot['prompt']:>14,} {tot['miss']:>12,} {tot['hit']/tot['prompt']:>8.4f} "
              f"{'-':>11s} {'-':>12s} {'-':>8s}")
        for W in arms:
            arm = Counter()
            peak = 0
            over = 0
            for (_sid, _p, _m), rows in by_fam.items():
                offset = 0
                prev = None
                for r in rows:
                    p = int(r.get("prompt_tokens") or 0)
                    h = int(r.get("observed_hit") or 0)
                    fold = prev is not None and str(r.get("action")) == "C2"
                    new = p if prev is None else max(0, p - int(prev.get("prompt_tokens") or 0))
                    if fold:
                        p2 = p + offset
                        if p2 >= W:
                            # 允许：付这一枪的 miss（乐观口径），折后回到实测基线
                            arm["kept"] += 1
                            arm["prompt"] += p2
                            arm["miss"] += max(0, p2 - (int(r.get("observed_hit") or 0)))
                            offset = 0
                            peak = max(peak, p2)
                        else:
                            # 推迟：内容留存，且不发生它的 miss
                            arm["deferred"] += 1
                            arm["prompt"] += p2
                            arm["miss"] += new
                            offset += max(0, int(prev.get("prompt_tokens") or 0) - p)
                            peak = max(peak, p2)
                    else:
                        p2 = p + offset
                        arm["prompt"] += p2
                        arm["miss"] += max(0, new)
                        peak = max(peak, p2)
                    if p2 > args.window:
                        over += 1
                    prev = r
            print(f"{W:>9,} {arm['prompt']:>14,} {arm['miss']:>12,} "
                  f"{1-arm['miss']/max(1,arm['prompt']):>8.4f} "
                  f"{arm['kept']:>5d}/{arm['deferred']:<5d} {peak:>12,} {over:>8d}")

    print()
    print(f"## 每会话（按可回收 miss 降序，前 {args.top}）")
    # ⚠️ 家族列必看：厂商侧不命中的家族（如 glm-4.6v，命中恒 43 tok）会把「其它重发」
    # 灌到本表头部——没有家族列时，两族混读会把厂商现象误当成本仓缺陷（10-05 实撞一次）。
    _fam_of_sid: dict[str, str] = {}
    for (_s, _p, _m) in by_fam:
        cur = f"{_p}/{_m}"
        prev_fam = _fam_of_sid.get(_s)
        _fam_of_sid[_s] = cur if prev_fam in (None, cur) else "mixed"
    print(f"{'session':24s} {'family':24s} {'枪':>4s} {'prompt':>10s} {'命中率':>7s} {'折叠':>9s} {'其它':>9s} {'新增':>10s}")
    rank = sorted(per_sid.items(),
                  key=lambda kv: -(kv[1]["fold_rewrite"] + kv[1]["other_resend"] + kv[1]["unexplained_drop"]))
    for sid, s in rank[: args.top]:
        print(f"{sid[:24]:24s} {_fam_of_sid.get(sid, '-')[:24]:24s} {s['shots']:>4d} {s['prompt']:>10,} {rate(s):>7s} "
              f"{s['fold_rewrite']:>9,} {s['other_resend']:>9,} {s['new']:>10,}")

    if args.dump:
        rows = sorted(extra["big_rows"], key=lambda x: -x[0])
        print()
        print("## 单枪重发最大的前 %d 枪（非 C2）" % args.dump)
        print(f"{'重发':>8s} {'sid':22s} {'action':7s} {'prompt 上→本':>24s} {'LCP 上→本':>22s} {'age':>8s}")
        for sf, sid, prev, r in rows[: args.dump]:
            print(f"{sf:>8,} {sid[:22]:22s} {str(r.get('action'))[:7]:7s} "
                  f"{int(prev.get('prompt_tokens') or 0):>11,}→{int(r.get('prompt_tokens') or 0):<11,} "
                  f"{int(prev.get('LCP') or 0):>10,}→{int(r.get('LCP') or 0):<10,} "
                  f"{float(r.get('cache_age') or 0):>8.1f}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"since": args.since, "long": args.long, "all": dict(tot),
                        "families": {f"{k[0]}/{k[1]}": dict(v) for k, v in per_family.items()},
                        "sessions": {k: dict(v) for k, v in per_sid.items()}},
                       ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8", newline="\n")
        print(f"\njson -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
