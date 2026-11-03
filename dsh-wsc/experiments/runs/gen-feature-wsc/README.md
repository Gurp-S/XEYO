# csv-lite

Tiny CSV reader, zero dependencies.

`parseCsv(text, { delimiter })` returns rows as arrays of strings. Fields may be quoted with `"`,
a quoted field may contain the separator, and `""` inside quotes is one literal quote.
Both `\n` and `\r\n` end a row. `delimiter` is a single character and defaults to `,`.

CLI: `node bin/csv.js [--delimiter <char>] [--no-header] <file>` prints a JSON array of objects
keyed by the first row. Options may appear before or after the file argument. `--delimiter <char>`
uses that character as the field separator, and `--no-header` prints the raw rows as arrays.
