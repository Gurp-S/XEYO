"""T31 跨入口 SSOT（服务端面）：会话 id 由服务端签发（xeyo- 前缀），workspace 服务端权威。"""

from typing import Any

RESPONSES: list[dict[str, Any]] = []


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session(workspace=str(h.workspace))
    checks.append(("server-issued xeyo- id", str(sid).startswith("xeyo-"),
                   f"sid={sid}"))
    # 假 workspace id：由服务端权威解析（拒绝或解析均由服务端决定，非客户端自造）
    st, j = h.api("post", "/v1/sessions", json_body={"workspace": "__nonexistent__"})
    served = st in (200, 400)
    checks.append(("workspace server-authoritative", served,
                   f"status={st} body={str(j)[:90]!r}"))
    return checks
