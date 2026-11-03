#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { createApp } from '../lib/app.js';

const file = process.argv[2];
if (!file) {
  process.stderr.write('usage: app-kit <config.json>\n');
  process.exit(2);
}
process.stdout.write(`${JSON.stringify(createApp(JSON.parse(readFileSync(file, 'utf8'))), null, 2)}\n`);
