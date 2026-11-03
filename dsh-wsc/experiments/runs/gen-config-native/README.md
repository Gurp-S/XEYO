# settings-kit

`loadSettings(raw)` normalises a settings object for the runtime.

Two file formats are accepted.

Version 1 (legacy) uses `db`:

    { "db": { "host": "localhost", "port": 5432 } }

Version 2 (the runtime's internal shape) uses `database`:

    { "database": { "host": "db.internal", "port": 6543, "ssl": true } }

Both versions normalise to:

    { "database": { "host": "localhost", "port": 5432, "ssl": false } }

Version 1 cannot express `ssl`, so a version 1 file that contains `ssl` is rejected rather than
silently upgraded. Version 2 defaults `ssl` to `false` when it is omitted.

A file that contains both `db` and `database`, or any unknown top-level key, is rejected as
ambiguous. Shape errors throw `TypeError`; a port outside `1..65535` throws `RangeError`.
