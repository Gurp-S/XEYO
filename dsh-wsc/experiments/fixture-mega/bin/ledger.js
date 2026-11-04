#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { parseCsv, createLedger } from '../src/ledger.js';
import { formatReport } from '../src/report.js';

const args = process.argv.slice(2);
const file = args.find((arg) => !arg.startsWith('--'));
const json = args.includes('--json');
const byCategory = args.includes('--by-category');
const dryRun = args.includes('--dry-run');

if (!file) {
  process.stderr.write('usage: ledger <file.csv> [--json] [--by-category] [--dry-run]\n');
  process.exit(2);
}

const ledger = createLedger(parseCsv(readFileSync(file, 'utf8')));
if (byCategory && !json) {
  const lines = Object.entries(ledger.categories).map(([name, cents]) => `${name}: ${cents}`);
  process.stdout.write(`${lines.join('\n')}\n`);
} else {
  process.stdout.write(`${formatReport(ledger, { json })}\n`);
}
