"""Exact-format catalog writer; serialized bytes live only for this call."""
from hashlib import sha256
from .contracts import encode


def write_catalog(writer,path,value):
    raw=encode(value).encode('utf-8')
    writer(path,raw)
    return sha256(raw).hexdigest()
