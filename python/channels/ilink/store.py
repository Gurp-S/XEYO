"""iLink bot_token 持久化。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def credentials_dir() -> Path:
	return Path(__file__).resolve().parents[2] / ".xeyo_ilink"


def credentials_path() -> Path:
	return credentials_dir() / "credentials.json"


def load_credentials(path: Path | None = None) -> dict[str, Any]:
	p = path or credentials_path()
	if not p.is_file():
		return {}
	try:
		raw = json.loads(p.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}
	return raw if isinstance(raw, dict) else {}


def save_credentials(data: dict[str, Any], path: Path | None = None) -> None:
	p = path or credentials_path()
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_credentials(path: Path | None = None) -> None:
	p = path or credentials_path()
	try:
		p.unlink(missing_ok=True)
	except OSError:
		pass
