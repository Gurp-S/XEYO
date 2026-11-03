Work in this repository. `app-kit` bootstraps a service; `README.md` documents the layout.

Refactor, with no behaviour change:

1. Rename the module `lib/config.js` to `lib/loader.js`.
2. Rename its exported function `parseConfig` to `loadConfig`.
3. Update every importer (`lib/app.js`, `bin/run.js`, tests) to the new path and name.
4. Do not leave a compatibility shim: the old module must not exist and `parseConfig` must not be
   re-exported anywhere. A stale import must fail loudly rather than silently work.

Validation rules, error types (`TypeError` / `RangeError`), the returned shape and the CLI output must
stay exactly as they are. `config.json` and `node bin/run.js config.json` must keep working.

Run `node --test tests/visible/basic.test.mjs` when you are done and report what you changed.
