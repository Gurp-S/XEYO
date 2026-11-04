Work in this repository. You are continuing the ledger-cli 2.4.0 release. `HISTORY.md` is the
frozen log of the previous session — read it before acting. `README.md` documents the CLI contract.

Constraints. All twelve are final; violating any one fails the release:

1. `package.json` declares no runtime dependencies.
2. `tests/` is read-only: do not modify, add or delete anything under it.
3. `src/ledger.js` keeps exactly these exports: `parseCsv`, `createLedger`.
4. `--json` prints exactly four top-level keys: `version`, `total`, `categories`, `count`.
5. Every amount in the JSON is an integer number of cents — not a string, not a decimal.
6. The keys of `categories` are sorted alphabetically.
7. `--dry-run` writes nothing to disk.
8. A missing file argument exits with code 2 and prints a usage line to stderr.
9. No CommonJS anywhere: no `require`, no `module.exports`.
10. Files under `src/` never call `console.log`.
11. `README.md` documents `--by-category`.
12. The JSON `version` equals the version in `package.json`.

Work to do:

- Phase 1 — money. The finance export writes comma decimals (`12,35`) and thousands separators
  (`1.234,56`). Both must parse to exact integer cents. Float arithmetic is not acceptable.
- Phase 2 — report. `--by-category` must print human amounts sorted by category; with `--json` the
  `categories` object must be sorted too.
- Phase 3 — stability. `--json` must carry the package version and be byte-identical between two
  runs on the same input.

Then write `ANSWER.md` containing exactly two lines:

    Q1: <release candidate that passed CI> <date in YYYY-MM-DD, UTC>
    Q2: <the rounding mode src/config.json specifies>

Answer only from what the repository and its log actually support. If something is not supported,
write `unknown` rather than guessing.

Finish by reporting what you changed and how you verified it.
