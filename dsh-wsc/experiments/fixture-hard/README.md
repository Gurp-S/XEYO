# ledger-cli

Zero-dependency accounting CLI. Reads transactions from CSV, aggregates them,
prints a report.

    node bin/ledger.js transactions.csv
    node bin/ledger.js transactions.csv --json
    node bin/ledger.js transactions.csv --by-category
    node bin/ledger.js transactions.csv --dry-run

Amounts are integers in cents everywhere. `src/config.json` holds the runtime
settings (currency, retention window).
