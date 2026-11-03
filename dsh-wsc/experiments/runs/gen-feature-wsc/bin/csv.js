#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseCsv } from '../src/parse.js';
import { parseArgs, UsageError } from '../src/args.js';

let options;
try {
  options = parseArgs(process.argv.slice(2));
} catch (error) {
  if (!(error instanceof UsageError)) throw error;
  process.stderr.write('usage: csv-lite <file>\n');
  process.exit(2);
}

const rows = parseCsv(readFileSync(options.file, 'utf8'), { delimiter: options.delimiter });
let out = rows;
if (options.header) {
  const [header, ...body] = rows;
  out = body.map((cells) => Object.fromEntries(header.map((name, index) => [name, cells[index] ?? ''])));
}
process.stdout.write(`${JSON.stringify(out, null, 2)}\n`);
