"""An explicit integration seam owned by the host runtime."""
from ..contracts import require


class CallbackHost:
    """commit performs capacity, permission, binding and idle checks atomically
    with installation; it persists the receipt and is idempotent by operation ID.
    lookup reads that durable receipt after a lost response. No receipt is invented
    here. An adapter without these host guarantees cannot use installation.
    """
    def __init__(self, *, commit, lookup):
        require(callable(commit) and callable(lookup), "host_callbacks_missing")
        self._commit, self._lookup = commit, lookup

    def install(self, package):
        return self._commit(package)

    def lookup(self, operation_id):
        return self._lookup(operation_id)
