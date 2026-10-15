"""Opt-in digest admission for bytes read from owned image asset paths."""
import hashlib
import os
from pathlib import Path
import re


def verify_read(raw, requested_path, *, cwd):
    from memory.wsc_media_archive import ENV
    if os.environ.get(ENV, '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        return
    from media_store import _media_root, MediaError
    requested = Path(requested_path).expanduser()
    if not requested.is_absolute():
        requested = Path(cwd) / requested
    # Keep the requested basename: resolving a redirected file first would
    # discard the digest identity the catalog actually advertised.
    if requested.parent.resolve() != _media_root().resolve():
        return
    if not re.fullmatch(r'[0-9a-f]{64}\.(?:png|jpg|gif|webp)', requested.name):
        return
    if hashlib.sha256(raw).hexdigest() != requested.stem:
        raise MediaError('stale_media_archive: content digest mismatch')
