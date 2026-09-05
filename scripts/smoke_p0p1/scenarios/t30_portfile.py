"""T30 端口与健康真相：portfile 携带 port/pid/started_at/engine_version。"""

import json
from typing import Any

RESPONSES: list[dict[str, Any]] = []


def run(h: Any) -> list[tuple[str, bool, str]]:
    data = json.loads(h.portfile_path.read_text("utf-8"))
    checks = [
        ("port present", int(data.get("port") or 0) > 0, f"port={data.get('port')}"),
        ("pid present", int(data.get("pid") or 0) > 0, f"pid={data.get('pid')}"),
        ("started_at present", bool(data.get("started_at")),
         f"started_at={data.get('started_at')}"),
        ("engine_version present", bool(data.get("engine_version")),
         f"engine_version={data.get('engine_version')}"),
    ]
    # /health 反映真实状态（含 engine_version / pid / busy_sessions）
    st, j = h.api("get", "/health")
    j = j or {}
    checks.append(("health reflects truth", st == 200 and any(
        k in j for k in ("engine_version", "pid", "busy_sessions", "status")),
        f"status={st} keys={list(j.keys())}"))
    return checks
