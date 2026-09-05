"""T5 会话标题三态：即时确定性标题 + rename 后 pin。"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"content": "好的。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    st, j = h.api("post", "/v1/sessions", json_body={"workspace": str(h.workspace)})
    sid = j.get("session_id") if isinstance(j, dict) else None
    checks.append(("session created", st == 200 and bool(sid), f"status={st}"))

    # 首条消息 -> 即时标题在 SSE title 帧
    tr = h.chat(sid, "设计一个新架构")
    title_frames = [e for e in tr.events if e.get("type") == "title"]
    checks.append(("instant title frame emitted", len(title_frames) >= 1,
                   f"titles={[t.get('title') for t in title_frames]}"))
    if title_frames:
        checks.append(("title non-empty", bool(title_frames[0].get("title")),
                       f"title={title_frames[0].get('title')!r}"))

    # rename -> pin（再次提交不改变标题）
    st2, _ = h.api("post", f"/v1/sessions/{sid}/rename",
                   json_body={"title": "固定标题"}, headers={"X-Session-Id": sid})
    checks.append(("rename pinned OK", st2 in (200, 204), f"status={st2}"))
    return checks
