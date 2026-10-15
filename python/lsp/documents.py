"""Serialize document snapshots and publish only successfully sent versions."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable


class DocumentSync:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._documents: dict[str, tuple[int, str]] = {}

    def ensure_open(
        self, uri: str, target: Path, language: str,
        notify: Callable[[str, dict[str, Any]], None],
    ) -> None:
        with self._lock:
            text = target.read_text(encoding="utf-8", errors="replace")
            previous = self._documents.get(uri)
            if previous is not None and previous[1] == text:
                return
            version = previous[0] + 1 if previous else 1
            if previous is None:
                notify("textDocument/didOpen", {"textDocument": {
                    "uri": uri, "languageId": language, "version": version, "text": text,
                }})
            else:
                notify("textDocument/didChange", {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": text}],
                })
            self._documents[uri] = (version, text)
