# csv-lite

Tiny CSV reader, zero dependencies.

`parseCsv(text)` returns rows as arrays of strings. Fields may be quoted with `"`,
a quoted field may contain the separator, and `""` inside quotes is one literal quote.
Both `\n` and `\r\n` end a row.

`parseCsv(text, { delimiter })` uses `delimiter` (a single character, default `,`)
as the field separator.

CLI: `node bin/csv.js [options] <file>` prints a JSON array of objects keyed by the
first row. Options may appear before or after the file argument:

- `--delimiter <char>` — field separator to use (default `,`).
- `--no-header` — print the raw rows as arrays instead of objects.
