"""Side-path switch for lossless model inputs; no production-layer imports."""
import os

DEFAULT_ENABLED = True  # 14-defect offline A/B gate: tests/test_llm_input_contract.py.
FLAG = "XEYO_LLM_INPUT_CONTRACT"


def enabled() -> bool:
    raw = os.environ.get(FLAG, "").strip().lower()
    if not raw:
        return DEFAULT_ENABLED
    return raw not in {"0", "false", "off", "no"} if DEFAULT_ENABLED else raw in {"1", "true", "on", "yes"}


def has_user_content(text: str, media: object) -> bool:
    return bool(text or (enabled() and media))


def notice_identity(message: object) -> bool:
    """Origin is side metadata, never a guess from user-controlled prose."""
    if isinstance(message, dict):
        return bool(str(message.get("note_key") or "").strip())
    return bool(str(getattr(message, "note_key", "") or "").strip())
