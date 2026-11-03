# csv-lite

Tiny CSV reader, zero dependencies.

`parseCsv(text)` returns rows as arrays of strings. Fields may be quoted with `"`,
a quoted field may contain the separator, and `""` inside quotes is one literal quote.
Both `\n` and `\r\n` end a row.

CLI: `node bin/csv.js <file>` prints a JSON array of objects keyed by the first row.
