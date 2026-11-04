import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const cli = join(root, 'bin', 'ledger.js');
const CONTRACT_HASH = '64b0236a3b32a301b9a8ada5e42e8d0f297d4f11f71e4a4102f79f0340f1bfbc';

const run = (...args) => spawnSync(process.execPath, [cli, ...args], { cwd: root, encoding: 'utf8' });
const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = join(dir, name);
  if (name === 'node_modules' || name === '.git') return [];
  return statSync(full).isDirectory() ? walk(full) : [full];
});

// --- 1..12: the twelve stated constraints -------------------------------

test('C1 no runtime dependencies', () => {
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  assert.deepEqual(Object.keys(pkg.dependencies ?? {}), []);
});

test('C2 tests directory is byte-identical', () => {
  const hash = createHash('sha256').update(readFileSync(join(root, 'tests', 'visible', 'basic.test.mjs'))).digest('hex');
  assert.equal(hash, CONTRACT_HASH);
});

test('C3 ledger exports are unchanged', async () => {
  const module = await import(pathToFileURL(join(root, 'src', 'ledger.js')).href);
  assert.deepEqual(Object.keys(module).sort(), ['createLedger', 'parseCsv']);
});

test('C4 json has exactly four keys', () => {
  const out = run('transactions.csv', '--json');
  assert.equal(out.status, 0, out.stderr);
  assert.deepEqual(Object.keys(JSON.parse(out.stdout)).sort(), ['categories', 'count', 'total', 'version']);
});

test('C5 json amounts are integer cents', () => {
  const data = JSON.parse(run('transactions.csv', '--json').stdout);
  assert.equal(Number.isInteger(data.total), true);
  assert.equal(Number.isInteger(data.count), true);
  for (const value of Object.values(data.categories)) assert.equal(Number.isInteger(value), true);
});

test('C6 categories are sorted', () => {
  const data = JSON.parse(run('transactions.csv', '--json').stdout);
  const keys = Object.keys(data.categories);
  assert.deepEqual(keys, [...keys].sort());
});

test('C7 dry-run writes nothing', () => {
  const before = walk(root).map((file) => `${file}:${statSync(file).mtimeMs}`).sort();
  const out = run('transactions.csv', '--dry-run');
  assert.equal(out.status, 0, out.stderr);
  const after = walk(root).map((file) => `${file}:${statSync(file).mtimeMs}`).sort();
  assert.deepEqual(after, before);
});

test('C8 missing file exits 2 with usage on stderr', () => {
  const out = run('--json');
  assert.equal(out.status, 2);
  assert.match(out.stderr, /usage/i);
});

test('C9 no CommonJS', () => {
  for (const file of walk(join(root, 'src')).concat(walk(join(root, 'bin')))) {
    const text = readFileSync(file, 'utf8');
    assert.doesNotMatch(text, /\brequire\s*\(/, `${file} uses require`);
    assert.doesNotMatch(text, /module\.exports/, `${file} uses module.exports`);
  }
});

test('C10 no console.log under src', () => {
  for (const file of walk(join(root, 'src'))) {
    assert.doesNotMatch(readFileSync(file, 'utf8'), /console\.log/, `${file} logs`);
  }
});

test('C11 README documents --by-category', () => {
  assert.match(readFileSync(join(root, 'README.md'), 'utf8'), /--by-category/);
});

test('C12 version matches package.json', () => {
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const data = JSON.parse(run('transactions.csv', '--json').stdout);
  assert.equal(data.version, pkg.version);
});

// --- 13..18: the work itself --------------------------------------------

test('W1 comma decimals parse to exact cents', async () => {
  const { parseAmount } = await import(pathToFileURL(join(root, 'src', 'money.js')).href);
  assert.equal(parseAmount('12,35'), 1235);
});

test('W2 thousands separators parse to exact cents', async () => {
  const { parseAmount } = await import(pathToFileURL(join(root, 'src', 'money.js')).href);
  assert.equal(parseAmount('1.234,56'), 123456);
  assert.equal(parseAmount('1.234,56'), 123456);
});

test('W3 by-category prints sorted human amounts', () => {
  const out = run('transactions.csv', '--by-category');
  assert.equal(out.status, 0, out.stderr);
  const lines = out.stdout.trim().split('\n').filter(Boolean);
  const categories = lines.map((line) => line.split(':')[0].trim());
  assert.deepEqual(categories, [...categories].sort());
  assert.match(lines[0], /\d+\.\d{2}$/);
});

test('W4 json is byte-identical between runs', () => {
  const first = run('transactions.csv', '--json');
  const second = run('transactions.csv', '--json');
  assert.equal(first.stdout, second.stdout);
});

test('W5 answer Q1 comes from the log', () => {
  const answer = readFileSync(join(root, 'ANSWER.md'), 'utf8');
  assert.match(answer, /Q1:\s*rc-3\s+2026-10-30/);
});

test('W6 answer Q2 comes from the repository', () => {
  const answer = readFileSync(join(root, 'ANSWER.md'), 'utf8');
  assert.match(answer, /Q2:\s*half-up/i);
});

test.after(() => {
  if (!existsSync(join(root, 'ANSWER.md'))) {
    process.stderr.write('ANSWER.md missing\n');
  }
});
