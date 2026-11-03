# settings-kit

`loadSettings(raw)` normalises a settings object for the runtime.

Two file formats are accepted.

Version 1:

    { "db": { "host": "localhost", "port": 5432 } }

Version 2 (the shape the runtime writes back):

    { "database": { "host": "db.internal", "port": 6543, "ssl": true } }

Both normalise to the internal shape, with `ssl` defaulting to `false`:

    { "database": { "host": "localhost", "port": 5432, "ssl": false } }

Rules:

- A version 1 file may not carry `ssl`: version 1 cannot express it, so `db.ssl` is rejected
  with a `TypeError` rather than silently upgraded.
- A file carrying both `db` and `database` is ambiguous and throws a `TypeError`.
- Unknown top-level keys throw a `TypeError`.
- `host` must be a non-empty string and `port` an integer in 1..65535 (`RangeError` otherwise);
  `database.ssl`, when present, must be a boolean (`TypeError` otherwise).
