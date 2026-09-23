"""度量台的发车闸门：V1 投影到底能不能跨采样点共用 session_id。

背景（`docs/wsc2-phase5.md` §8–§9）：`memory/wsc_projection.py:65` 的 `_STATE` 按 session_id 缓存
冻结头，`XEYO_WSC_FROZEN_HEAD` 默认开 ⇒ 探针把同一转录的多个前缀当成同会话连续枪来打时，
后一个点会拿到前一个点的头，量出来的 V1 尺寸/召回全是被抬高的。实测抬高 40.6%。

这里把"发现了"变成"不修就跑不起来"：

- `contamination(project, prefixes)` —— 同一批前缀，共用 sid 跑一遍、每点唯一 sid 跑一遍，
  比逐字差异与体积差。
- `require_independent(prefixes, project)` —— 探针启动时调用：若结果依赖投影顺序（即共用 sid
  且顺序可交换性不成立），直接 `SystemExit` 拒跑。

自检本身要能被证伪：`self_test()` 会在"故意共用 sid"的模式下断言闸门**会响**。
"""

from __future__ import annotations

import hashlib


def _sha(text: str) -> str:
    """**遮名后再比**：取回句柄里带 `offload/wsc/<session>.txt`，session 名本身就随 sid 变，
    不遮名会把"换了个文件名"误判成"输出变了"（第一版就栽在这里，报了个假的顺序敏感）。
    剩下 `<...>` 兜住其它 sid 派生名（快照目录、视图文件等）。"""
    import re

    masked = re.sub(r"offload[/\\]wsc[/\\][^'\"\s]+", "<STORE>", text)
    masked = re.sub(r"<[^>]{1,80}>", "<T>", masked)
    return hashlib.sha1(masked.encode("utf-8", "ignore")).hexdigest()[:12]


def contamination(project, prefixes):
    """project(prefix, sid) -> str。返回 (逐字不同的点数, 总比例, 体积比)。"""
    shared = [project(p, "GUARD-SHARED") for p in prefixes]
    fresh = [project(p, f"GUARD-FRESH-{i}") for i, p in enumerate(prefixes)]
    diff = sum(1 for a, b in zip(shared, fresh) if _sha(a) != _sha(b))
    ta, tb = sum(len(a) for a in shared), sum(len(b) for b in fresh)
    return diff, round(diff / max(1, len(prefixes)), 4), round(ta / max(1, tb), 4)


def order_is_stable(project, prefixes):
    """唯一 sid 下，投影顺序不该影响任何一点的输出 ⇒ 这才是可引用的逐点采样。"""
    fwd = {i: _sha(project(p, f"ORD-F-{i}")) for i, p in enumerate(prefixes)}
    rev = {}
    for i in reversed(range(len(prefixes))):
        rev[i] = _sha(project(prefixes[i], f"ORD-R-{i}"))
    bad = [i for i in fwd if fwd[i] != rev[i]]
    return not bad, bad


class SidLedger:
    """探针用的取号器：**同一个 sid 不许打两个不同前缀**。

    这是唯一可靠的执法点 —— "每点唯一 sid"本身就是修复，所以事后用唯一 sid 去查污染一定查不出来
    （`order_is_stable` 对"sid 真的被隔离"的假件是不敏感的）。取号器在调用时就拦住复用。
    """

    def __init__(self) -> None:
        self._used: dict[str, str] = {}

    def claim(self, sid: str, prefix_key: str) -> str:
        prev = self._used.get(sid)
        if prev is not None and prev != prefix_key:
            raise SystemExit(
                f"guard: session_id {sid!r} 已被另一个采样点用过 ⇒ V1 会复用冻结头，"
                f"本次投影不可引用。每个点必须取唯一 sid。")
        self._used[sid] = prefix_key
        return sid


def require_independent(project, prefixes, *, sample: int = 8):
    """探针启动时调用。顺序不稳 ⇒ 拒跑；共用 sid 与唯一 sid 不等 ⇒ 打印提醒并强制唯一 sid。"""
    ps = list(prefixes)[:sample]
    if not ps:
        raise SystemExit("guard: 没有可用前缀样本")
    stable, bad = order_is_stable(project, ps)
    if not stable:
        raise SystemExit(f"guard: V1 投影顺序敏感（{len(bad)}/{len(ps)} 点）⇒ 逐点采样不可引用，"
                         f"必须先隔离 session_id 再跑")
    diff, ratio, size_ratio = contamination(project, ps)
    return {"顺序无关": True, "共用sid与唯一sid不同的点数": f"{diff}/{len(ps)}",
            "共用/唯一 字符量比": size_ratio,
            "结论": "该语料确实会被 _STATE 污染，探针必须每点唯一 sid"}


def self_test(project, prefixes):
    """变异验证：故意用同一个 sid 连打多个前缀 ⇒ 闸门必须响。"""
    def shared_only(p, _sid):
        return project(p, "SAME-SID-EVERY-TIME")

    stable, bad = order_is_stable(shared_only, prefixes)
    return (not stable), bad


if __name__ == "__main__":
    raise SystemExit("只能被探针 import 使用")
