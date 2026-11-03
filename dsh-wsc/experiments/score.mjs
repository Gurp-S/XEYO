import { cp, mkdtemp, rm } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { applyScorePolicy } from './tools/score-policy.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const arg = process.argv[2];
if (!arg) {
  process.stderr.write('usage: node score.mjs <candidate-repo-dir>\n');
  process.exit(2);
}

const work = await mkdtemp(path.join(tmpdir(), 'mini-build-score-'));
const repo = path.join(work, 'repo');
await cp(path.resolve(arg), repo, {
  recursive: true,
  filter: (src) =>
    !/[\\/](out|node_modules|\.git)([\\/]|$)/.test(src) && !src.endsWith('build-manifest.json'),
});

const tests = [];
let tail = '';
const child = spawn(
  process.execPath,
  ['--test', '--test-reporter=tap', (process.argv[3] ?? path.join(here, 'hidden', 'build.test.mjs'))],
  { env: { ...process.env, MINI_BUILD_ROOT: repo }, stdio: ['ignore', 'pipe', 'inherit'] },
);
child.stdout.setEncoding('utf8');
child.stdout.on('data', (chunk) => {
  tail += chunk;
  const lines = tail.split('\n');
  tail = lines.pop() ?? '';
  for (const line of lines) {
    const match = /^(ok|not ok) \d+ - (.*)$/.exec(line);
    if (match) tests.push({ name: match[2].trim(), ok: match[1] === 'ok' });
  }
});
const code = await new Promise((resolve) => child.once('exit', resolve));
await rm(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });

const passed = tests.filter((entry) => entry.ok).length;
const report = applyScorePolicy({
  score: tests.length ? Number((passed / tests.length).toFixed(4)) : 0,
  passed,
  total: tests.length,
  exitCode: code,
  tests,
});
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
