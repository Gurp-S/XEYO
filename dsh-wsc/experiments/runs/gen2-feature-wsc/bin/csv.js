#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseCsv } from '../src/parse.js';
import { parseArgs, renderRows, USAGE } from '../src/cli.js';

const options = parseArgs(process.argv.slice(2));
if (options === null) {
  process.stderr.write(USAGE);
  process.exit(2);
}
const rows = parseCsv(readFileSync(options.file, 'utf8'), { delimiter: options.delimiter });
process.stdout.write(`${JSON.stringify(renderRows(rows, options), null, 2)}\n`);
