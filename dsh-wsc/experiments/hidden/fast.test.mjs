import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';

const root = process.env.MINI_BUILD_ROOT;
if (!root) throw new Error('MINI_BUILD_ROOT is not set');

const load = (relative) => import(pathToFileURL(path.join(root, relative)).href);

test('tokenize folds case and drops punctuation', async () => {
  const { tokenize } = await load('lib/tokenize.js');
  assert.deepEqual(tokenize('Hello, world! Hello.'), ['hello', 'world', 'hello']);
  assert.deepEqual(tokenize('  ...  '), []);
});

test("tokenize keeps an apostrophe inside a word", async () => {
  const { tokenize } = await load('lib/tokenize.js');
  assert.deepEqual(tokenize("Don't stop, don't"), ["don't", 'stop', "don't"]);
});

test('top sorts by count then by word, and respects the limit', async () => {
  const { count, top } = await load('lib/count.js');
  assert.deepEqual(top(count('b a b a c')), [
    ['a', 2],
    ['b', 2],
    ['c', 1],
  ]);
  assert.deepEqual(top(count('z y x w'), 2), [
    ['w', 1],
    ['x', 1],
  ]);
});

test('the cli prints word and count, tab separated', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'mini-count-'));
  const file = path.join(dir, 'text.txt');
  writeFileSync(file, 'red blue red', 'utf8');
  const out = execFileSync(process.execPath, [path.join(root, 'bin/cli.js'), file], {
    encoding: 'utf8',
  });
  assert.equal(out.trim().split('\n').join('|'), 'red\t2|blue\t1');
});
