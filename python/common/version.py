"""Runtime version shared by embedded, CLI and HTTP entry points."""
__version__ = "1.11.0"


def engine_version() -> str:
    return __version__
