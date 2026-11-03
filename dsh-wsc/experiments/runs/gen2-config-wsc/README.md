# settings-kit

`loadSettings(raw)` normalises a settings object for the runtime.

Two file formats are accepted. Version 1 uses `db`:

    { "db": { "host": "localhost", "port": 5432 } }

Version 2 uses `database`, and may carry `ssl`:

    { "database": { "host": "db.internal", "port": 6543, "ssl": true } }

Both normalise to the internal shape:

    { "database": { "host": "localhost", "port": 5432, "ssl": false } }

`ssl` defaults to `false`. Version 1 cannot express `ssl`, so a version 1 file that carries `ssl` is
rejected with a `TypeError` rather than being silently upgraded.

A file carrying both `db` and `database` is ambiguous and is rejected with a `TypeError`, as are
unknown top-level keys. Shape problems throw `TypeError`; a port outside 1..65535 throws `RangeError`.
