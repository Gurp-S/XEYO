"""Capture the turn actually observed on this stream before sending control."""
def observed_turn_id(frame: dict) -> str:
    xy = frame.get("xy") or frame.get("xeyo") or {}
    value = frame.get("xeyo_turn_id") or (xy.get("turn_id") if isinstance(xy, dict) else "")
    return value if isinstance(value, str) else ""
