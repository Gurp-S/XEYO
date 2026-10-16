"""Content-addressed evidence for evaluation branch restart checkpoints.

Mutable source.jsonl is only a staging view; a checkpoint never references it.
No production recovery changes or silent repair of mismatched evidence.
"""
import hashlib
import json
from pathlib import Path

from synaptic.contracts import publish


def seal_source(staging):
    staging=Path(staging);raw=staging.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    sealed=publish(staging.with_name('source-archive.txt'),raw)
    if hashlib.sha256(sealed.read_bytes()).hexdigest()!=sha:raise ValueError('checkpoint_source_unsealed')
    return {'path':str(sealed),'sha256':sha}


def read_source(locator):
    raw=Path(locator['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=locator['sha256']:raise ValueError('checkpoint_source_seal_mismatch')
    return [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
