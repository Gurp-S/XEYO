"""Lazy optional attachment. Off has no store, schema or model side effects."""
from .contracts import require


class Plugin:
    def __init__(self, *, mode="off", factory=None):
        require(mode in {"off", "observe", "active"}, "plugin_mode_invalid")
        require(mode == "off" or callable(factory), "plugin_factory_missing")
        self._mode, self._factory, self._core = mode, factory, None

    @property
    def mode(self):
        return self._mode

    @property
    def core(self):
        require(self.mode != "off", "component_disabled")
        if self._core is None:
            self._core = self._factory()
        return self._core

    def observe(self, context, *, events=()):
        if self.mode != "off":
            self.core.ingest(list(events))
        return context

    def install(self, operation_id, host):
        require(self.mode == "active", "component_not_active")
        return self.core.install(operation_id, host)

    def disable(self):
        if self.mode == "active" and self._core is not None:
            require(self.core.status()["mode"] == "detached", "handoff_not_confirmed")
        self._mode = "off"
