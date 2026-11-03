# settings-kit

`loadSettings(raw)` normalises a settings object for the runtime.

The current file format is version 1:

    { "db": { "host": "localhost", "port": 5432 } }

and `loadSettings` returns the internal shape:

    { "database": { "host": "localhost", "port": 5432, "ssl": false } }
