#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseCsv } from '../src/parse.js';

const file = process.argv[2];
if (!file) {
  process.stderr.write('usage: csv-lite <file>\n');
  process.exit(2);
}
const rows = parseCsv(readFileSync(file, 'utf8'));
const [header, ...body] = rows;
const out = body.map((cells) => Object.fromEntries(header.map((name, index) => [name, cells[index] ?? ''])));
process.stdout.write(`${JSON.stringify(out, null, 2)}\n`);
