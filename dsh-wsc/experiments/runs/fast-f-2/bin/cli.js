#!/usr/bin/env node
import { readFileSync } from 'node:fs';

import { count, top } from '../lib/count.js';

const [file] = process.argv.slice(2);
if (file === undefined) {
  console.error('usage: node bin/cli.js <file>');
  process.exit(2);
}

const counts = count(readFileSync(file, 'utf8'));
for (const [word, hits] of top(counts)) {
  console.log(`${word}\t${hits}`);
}
