import test from 'node:test';
import assert from 'node:assert/strict';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';

const root = process.env.MINI_BUILD_ROOT ?? process.cwd();
const { parseCsv } = await import(pathToFileURL(join(root, 'src', 'parse.js')).href);
const cli = join(root, 'bin', 'csv.js');
const work = mkdtempSync(join(tmpdir(), 'csv-lite-'));
const file = join(work, 'data.csv');
writeFileSync(file, 'name;score\nada;9\nalan;7\n');

const run = (...args) => {
  const out = spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
  assert.equal(out.status, 0, out.stderr);
  return JSON.parse(out.stdout);
};

test('parser accepts a custom delimiter', () => {
  assert.deepEqual(parseCsv('a;b\n1;2', { delimiter: ';' }), [['a', 'b'], ['1', '2']]);
});

test('custom delimiter keeps quoted fields intact', () => {
  assert.deepEqual(parseCsv('a;b\n"x;y";z', { delimiter: ';' }), [['a', 'b'], ['x;y', 'z']]);
});

test('default delimiter still works', () => {
  assert.deepEqual(parseCsv('a,b\n1,2'), [['a', 'b'], ['1', '2']]);
});

test('cli --delimiter reads semicolon files', () => {
  assert.deepEqual(run('--delimiter', ';', file), [{ name: 'ada', score: '9' }, { name: 'alan', score: '7' }]);
});

test('cli --no-header returns raw rows', () => {
  assert.deepEqual(run('--delimiter', ';', '--no-header', file), [
    ['name', 'score'], ['ada', '9'], ['alan', '7'],
  ]);
});

test('cli keeps the default object output', () => {
  const plain = join(work, 'plain.csv');
  writeFileSync(plain, 'a,b\n1,2\n');
  assert.deepEqual(run(plain), [{ a: '1', b: '2' }]);
});

test.after(() => rmSync(work, { recursive: true, force: true }));
