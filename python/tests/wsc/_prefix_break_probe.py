"""只读诊断：adopted 口径下，连续两轮投影的**首个失配点**落在哪一段。

动机（实测）：adopted 口径的 237 个紧凑态回合里，miss 体积 U 的中位数只有 1.5k，
但重尾里有 60k–190k 的回合——`L=197800 / lcp=8241`。也就是**尾部本该只追加、
前缀却在中段断掉**。不把失配点定位出来，就没法判断该改口径还是改算法。

用法：python tests/wsc/_prefix_break_probe.py <session.jsonl> [limit]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.compact import keep_tail_cut  # noqa: E402
from engine.compact import project as c0_project  # noqa: E402
from memory.simulator.params import load_params  # noqa: E402
from memory.simulator.projection import common_prefix, emit_segment, project as sim_project  # noqa: E402
from memory.simulator.scenarios import state_from_messages  # noqa: E402
from memory.token import token_len  # noqa: E402
from synaptic.project import project as wsc_project  # noqa: E402
from synaptic.replay import _SYSTEM_STANDIN, _as_api_message, load_jsonl, user_turn_starts  # noqa: E402
from synaptic.types import WscParams  # noqa: E402


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    path = Path(argv[0])
    limit = int(argv[1]) if len(argv) > 1 else 131072
    api = [_as_api_message(r) for r in load_jsonl(path)]
    starts = user_turn_starts(api)
    pset = WscParams(mode="closure").for_level("Medium+")
    sp = load_params()

    cursor = 0
    hot = ""
    state = None
    prev_x = ""
    basis = 0.0
    prev_cursor = 0
    for t, start in enumerate(starts):
        end = starts[t + 1] if t + 1 < len(starts) else len(api)
        prefix = api[:end]
        if len(prefix) < 8:
            continue
        region_end = keep_tail_cut(prefix)
        fired = False
        if basis >= 0.8 * limit and region_end > cursor:
            proj = wsc_project(prefix, region_end=region_end, params=pset, prev=state, session=path.stem)
            if proj.result.compressed:
                fired = True
                cursor = region_end
                hot = proj.text
                state = proj.state
        active = cursor > 0
        tail = c0_project(prefix[cursor:]) if active else c0_project(prefix)
        st = state_from_messages(tail, cursor=0, system=hot if active else _SYSTEM_STANDIN)
        pr = sim_project(st)
        lcp = common_prefix(pr.x, prev_x) if prev_x else ""
        if prev_x and active:
            same = pr.x.startswith(prev_x)
            cp = len(lcp)
            ctx_prev = prev_x[max(0, cp - 60) : cp + 60].replace("\n", "\\n")
            ctx_new = pr.x[max(0, cp - 60) : cp + 60].replace("\n", "\\n")
            print(
                f"t{t:>4} fired={int(fired)} cursor {prev_cursor}->{cursor} L={pr.length:>7} "
                f"prevL={token_len(prev_x):>7} lcp={token_len(lcp):>7} prefix_ok={same}"
            )
            if not same:
                print(f"       prev@lcp: ...{ctx_prev}...")
                print(f"       new @lcp: ...{ctx_new}...")
        basis = float(pr.length)
        prev_x = pr.x
        prev_cursor = cursor
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
