#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseCsv } from '../src/parse.js';
import { CliError, USAGE, parseArgs } from '../src/cli-args.js';

function fail(error) {
  process.stderr.write(error instanceof CliError ? `${error.message}\n${USAGE}` : USAGE);
  process.exit(2);
}

let options;
try {
  options = parseArgs(process.argv.slice(2));
} catch (error) {
  fail(error);
}
if (!options.file) fail();

const rows = parseCsv(readFileSync(options.file, 'utf8'), { delimiter: options.delimiter });
const [header, ...body] = rows;
const out = options.header
  ? body.map((cells) => Object.fromEntries(header.map((name, index) => [name, cells[index] ?? ''])))
  : rows;
process.stdout.write(`${JSON.stringify(out, null, 2)}\n`);
