Work in this repository. `settings-kit` normalises a settings file; `README.md` documents the current
version 1 format.

Requested change: accept version 2 of the file format, and keep version 1 working.

Version 2 is the internal shape written back by the runtime:

    { "database": { "host": "db.internal", "port": 6543, "ssl": true } }

Rules:

1. `{ db: ... }` (version 1) still normalises to `{ database: { host, port, ssl: false } }`.
   Version 1 cannot express `ssl`, so a version 1 file that carries `ssl` must be rejected with a
   `TypeError` instead of being silently upgraded.
2. `{ database: ... }` (version 2) is accepted as-is, with `ssl` defaulting to `false`.
3. A file that carries both `db` and `database` is ambiguous and must throw a `TypeError`.
4. Unknown top-level keys are rejected with a `TypeError`.
5. The existing validation rules and error types (`TypeError` for shape, `RangeError` for the port
   range) still apply to both versions.

`settings.json` and `node --test tests/visible/basic.test.mjs` must keep working. Report what you changed.
