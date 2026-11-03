import test from 'node:test';
import assert from 'node:assert/strict';
import { parseCsv } from '../../src/parse.js';
import { CliError, parseArgs } from '../../src/cli-args.js';

test('splits rows and cells', () => {
  assert.deepEqual(parseCsv('a,b\n1,2'), [['a', 'b'], ['1', '2']]);
});

test('quoted cell keeps the separator', () => {
  assert.deepEqual(parseCsv('a,b\n"x,y",z'), [['a', 'b'], ['x,y', 'z']]);
});

test('custom delimiter separates fields', () => {
  assert.deepEqual(parseCsv('a;b\n1;2', { delimiter: ';' }), [['a', 'b'], ['1', '2']]);
});

test('custom delimiter keeps quoted separators, escaped quotes and CRLF', () => {
  assert.deepEqual(parseCsv('a;b\r\n"x;y";"a""b"\r\n', { delimiter: ';' }), [['a', 'b'], ['x;y', 'a"b']]);
});

test('delimiter defaults to comma', () => {
  assert.deepEqual(parseCsv('a,b\n1,2', {}), parseCsv('a,b\n1,2'));
  assert.deepEqual(parseCsv('a;b'), [['a;b']]);
});

test('cli options are accepted before and after the file', () => {
  const before = parseArgs(['--delimiter', ';', '--no-header', 'sample.csv']);
  const after = parseArgs(['sample.csv', '--no-header', '--delimiter', ';']);
  const expected = { delimiter: ';', header: false, file: 'sample.csv' };
  assert.deepEqual(before, expected);
  assert.deepEqual(after, expected);
});

test('cli defaults to comma delimiter with header row', () => {
  assert.deepEqual(parseArgs(['sample.csv']), { delimiter: ',', header: true, file: 'sample.csv' });
  assert.equal(parseArgs([]).file, undefined);
});

test('cli rejects a delimiter that is not one character', () => {
  assert.throws(() => parseArgs(['--delimiter']), CliError);
  assert.throws(() => parseArgs(['--delimiter', ';;', 'sample.csv']), CliError);
  assert.throws(() => parseArgs(['--delimiter', '']), CliError);
});
