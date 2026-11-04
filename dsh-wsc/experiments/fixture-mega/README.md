# ledger-cli

Zero-dependency accounting CLI with a pricing helper and a small user-service surface.

- `bin/ledger.js <file.csv> [--json] [--by-category] [--dry-run]` — accounting report.
- `src/pricing.js` — tiered discount helper used by checkout.
- `src/api.js` — public user module; `src/service.js` and `bin/run.js` are internal callers.

Amounts are integers in cents everywhere. `src/config.json` holds the runtime settings.
