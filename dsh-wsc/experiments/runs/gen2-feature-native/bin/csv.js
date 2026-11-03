#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseCsv } from '../src/parse.js';
import { parseCliArgs, USAGE } from '../src/args.js';

const { file, delimiter, header, errors } = parseCliArgs(process.argv.slice(2));
if (errors.length > 0 || !file) {
  process.stderr.write(USAGE);
  process.exit(2);
}
const rows = parseCsv(readFileSync(file, 'utf8'), { delimiter });
const out = header
  ? rows.slice(1).map((cells) => Object.fromEntries(rows[0].map((name, index) => [name, cells[index] ?? ''])))
  : rows;
process.stdout.write(`${JSON.stringify(out, null, 2)}\n`);
