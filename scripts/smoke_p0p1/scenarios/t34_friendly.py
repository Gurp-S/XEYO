"""T34 错误人话化：无效 session id 的 API 调用返回友好文案，绝不带 Traceback。"""

from typing import Any

RESPONSES: list[dict[str, Any]] = []


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    st, j = h.api("get", "/v1/sessions/anon-bad-session/messages")
    raw = str(j or "")
    checks.append(("bad session handled", st in (404, 200, 400),
                   f"status={st} body={raw[:120]!r}"))
    checks.append(("no traceback leaked", "Traceback" not in raw
                   and "File \"" not in raw
                   and "Exception" not in raw,
                   f"body={raw[:160]!r}"))
    return checks
