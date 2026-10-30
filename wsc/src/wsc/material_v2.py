"""Lazy public material (V2): page a projection without building it whole.

``MaterialView`` keeps the validated rows and understanding records by
reference and only builds the public dict when a caller asks for it.
``event_slice`` projects one window of rows, so a consumer that needs a single
page never serializes the whole history.  ``byte_size`` stays exact because the
byte budget is a contract, not an estimate.
"""
from .contracts import encode, require
from .projection import public_material

_KEYS = ("id", "seq", "kind", "role", "call_id", "text", "observed_at")


class MaterialView:
    def __init__(self, prefix, records, *, session_id, cut):
        self.prefix = list(prefix)
        self.records = list(records)
        self.session_id = session_id
        self.cut = cut
        self._public = None

    @property
    def size(self) -> int:
        return len(self.prefix)

    def public(self) -> dict:
        if self._public is None:
            self._public = self._project()
        return self._public

    def _project(self) -> dict:
        return {"session_id": self.session_id, "source_boundary": self.cut,
                **public_material(self.prefix, self.records)}

    def byte_size(self) -> int:
        """Exact serialized size of the full public projection."""
        return len(encode(self.public()).encode("utf-8"))

    def text_bytes(self) -> int:
        """Lower bound on the public size, computed without projecting.

        Every visible character costs at least one byte in UTF-8 and the
        projection only adds structure around the text, so a sum that already
        exceeds the budget proves the full view would too. Callers use this to
        reject an oversized view before paying for its projection.
        """
        return sum(len(row.get("text") or "") for row in self.prefix if row["kind"] != "opaque")

    def event_slice(self, offset: int, limit: int) -> dict:
        require(isinstance(offset, int) and isinstance(limit, int) and offset >= 0 and limit >= 0,
                "material_slice_invalid")
        visible = [row for row in self.prefix if row["kind"] != "opaque"]
        rows = visible[offset:offset + limit]
        source_ids = {row["id"] for row in rows}
        return {"session_id": self.session_id, "source_boundary": self.cut,
                "events": [{key: row[key] for key in _KEYS} for row in rows],
                "understandings": [record for record in self.records
                                   if set(record["sources"]) <= source_ids]}
