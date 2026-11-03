import { runScenarios } from './scenarios.mjs';
import * as next from '../lib/build.js';
import * as legacy from './legacy/lib/build.js';

const pad = (text, width) => text + ' '.repeat(Math.max(0, width - text.length));

const [a, b] = await Promise.all([runScenarios(legacy.build), runScenarios(next.build)]);
const width = Math.max(...a.map((r) => r.name.length));

process.stdout.write(`${pad('scenario', width)}  legacy  next\n`);
for (let i = 0; i < a.length; i += 1) {
  const left = a[i].pass ? 'pass' : 'FAIL';
  const right = b[i].pass ? 'pass' : 'FAIL';
  process.stdout.write(`${pad(a[i].name, width)}  ${pad(left, 6)}  ${right}\n`);
}

const count = (rows) => rows.filter((r) => r.pass).length;
process.stdout.write(`\nlegacy ${count(a)}/${a.length}, next ${count(b)}/${b.length}\n`);

const broken = b.filter((r) => !r.pass);
for (const row of broken) {
  process.stdout.write(`next failure: ${row.name}${row.detail ? ` (${row.detail})` : ''}\n`);
}
process.exitCode = broken.length === 0 ? 0 : 1;
