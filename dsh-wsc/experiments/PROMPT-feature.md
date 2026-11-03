Work in this repository. `csv-lite` is a zero-dependency CSV reader; `README.md` documents the contract.

Requested feature: the CLI must accept two options, in any position relative to the file argument.

- `--delimiter <char>` — use that character as the field separator for both the parser and the CLI.
  `parseCsv` must accept it as `{ delimiter }`; the default stays `,`.
- `--no-header` — print the raw rows as arrays instead of objects keyed by the first row.

Everything that works today must keep working: the default delimiter, quoted fields containing the
separator, `""` as a literal quote, `\r\n` line endings, the JSON object output when no flag is given,
and the `usage:` error with exit code 2 when the file argument is missing.

Run `node --test tests/visible/basic.test.mjs` when you are done, and check the CLI by hand on
`sample.csv`. Report what you changed.
