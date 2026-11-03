# settings-kit

`loadSettings(raw)` normalises a settings object for the runtime.

Two file formats are accepted.

## Version 1

    { "db": { "host": "localhost", "port": 5432 } }

## Version 2

    { "database": { "host": "db.internal", "port": 6543, "ssl": true } }

In both versions `loadSettings` returns the internal shape:

    { "database": { "host": "db.internal", "port": 6543, "ssl": true } }

`ssl` defaults to `false` when omitted. Version 1 has no `ssl` field, so a
version 1 file that contains one is rejected rather than upgraded.

## Rejected input

`loadSettings` throws a `TypeError` when a file:

- contains both `db` and `database` (ambiguous format),
- contains an unknown top-level key,
- puts `ssl` in a version 1 `db` block,
- has a malformed shape (non-object blocks, non-string `host`, non-boolean `ssl`).

A `port` outside 1..65535 throws a `RangeError`.
