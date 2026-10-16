"""Lossless slash arguments and truthful, singly bounded skill payloads."""
import re


def leading_token(text: str) -> tuple[str, str] | None:
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = re.match(r"^/([^\s/]+)(?:\s+(.*))?$", line.strip())
        if match is None:
            return None
        rest = match[2] or ""
        return match[1], "\n".join([rest, *lines[index + 1:]]).strip()
    return None


def render_skill(entry, body: str, limit: int) -> str:
    total = len(body)
    clipped = total > limit
    shown = body[:limit] if clipped else body
    status = (f"SKILL.md 节选：显示 {len(shown)}/{total} 字符；完整文件：{entry.path / 'SKILL.md'}。"
              if clipped else "SKILL.md 全文（含调用参数展开；调用 Skill 工具返回的也是该内容）。")
    return (
        "# Skill invocation（用户直呼技能 — background only）\n"
        f"用户在本轮消息里以 /{entry.name} 直接调用了技能「{entry.name}」。\n"
        f"{status}\n\n<skill_content>\n{shown}\n</skill_content>"
    )
