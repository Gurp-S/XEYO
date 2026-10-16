"""Public embedded-engine entry point; product dependencies load only on demand.

Legacy package imports remain supported during the namespace migration.
"""
from common.version import __version__

__all__ = ["QueryEngine", "QueryEngineConfig", "build_default_engine", "RuntimeServices", "ToolHostServices", "__version__"]


def __getattr__(name: str):
    if name == "ToolHostServices":
        from tools.host_services import ToolHostServices
        return ToolHostServices
    if name == "RuntimeServices":
        from engine.runtime_services import RuntimeServices
        return RuntimeServices
    if name in {"QueryEngine", "QueryEngineConfig", "build_default_engine"}:
        from engine import query_engine
        return getattr(query_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
