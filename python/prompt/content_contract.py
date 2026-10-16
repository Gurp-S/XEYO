"""Separate provenance framing from narrowly identified credential redaction."""
import re

# Literal assignments only: expressions such as tokenizer.encode(text) are source.
# Capture separators/quotes so redaction does not corrupt surrounding syntax.
_LITERAL = re.compile(
    r'''(?i)(\b(?:api[_-]?key|secret|token|password)\b["']?\s*[=:]\s*)(["'])([^\r\n]*?)(\2)'''
)
_ENV_LITERAL = re.compile(
    r"(?m)^(\s*(?:export\s+)?(?:[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD))\s*=\s*)([A-Za-z0-9_+/.=-]{8,})(\s*)$"
)


def sanitize_data(content: str, secret_patterns: tuple) -> str:
    text = content or ""
    # Provider key formats and PEM blocks remain redacted independently of syntax.
    for pattern, replacement in secret_patterns[:3]:
        text = pattern.sub(replacement, text)
    text = _LITERAL.sub(
        lambda m: m[1] + m[2] + ("[REDACTED]" if len(m[3]) >= 8 else m[3]) + m[4], text
    )
    return _ENV_LITERAL.sub(lambda m: m[1] + "[REDACTED]" + m[3], text)


def direct_user_text(text: str) -> str:
    """Authenticated inbound channel content has the same authority as GUI input."""
    return text or ""
