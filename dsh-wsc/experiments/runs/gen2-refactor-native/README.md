# app-kit

Small service bootstrap used by the deploy scripts.

- `lib/loader.js` exports `loadConfig(raw)` — validates and normalises the config object.
- `lib/app.js` exports `createApp(raw)` — builds the runtime descriptor.
- `bin/run.js` prints the descriptor as JSON.
