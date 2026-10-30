"""Opt-in Win32 binding reuse; file calls, flags and validation stay identical."""
from functools import lru_cache
from .resource_io import ResourceIO


@lru_cache(maxsize=1)
def file_api():
    return ResourceIO._windows_api()


class BoundWindowsIO(ResourceIO):
    _windows_api=staticmethod(file_api)
