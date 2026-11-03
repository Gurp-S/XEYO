import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { cacheKey } from './cache.js';
import { mapLimit } from './pool.js';

// Sorted relative POSIX paths of every regular file under `dir`. Symlinks are
// neither files nor directories here, so they are skipped.
export async function walk(dir, base = dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}

// Contents of every source file, keyed by relative path and in sorted order.
export async function readTree(dir, { concurrency = 1 } = {}) {
  const rels = await walk(dir, dir);
  const loaded = await mapLimit(rels, concurrency, (rel) => readFile(path.join(dir, rel)));
  const bytes = new Map();
  for (let index = 0; index < rels.length; index += 1) bytes.set(rels[index], loaded[index]);
  return bytes;
}

// Content fingerprint of every source file; equal snapshots mean no change.
export async function snapshot(dir, options) {
  const bytes = await readTree(dir, options);
  const keys = new Map();
  for (const [rel, content] of bytes) keys.set(rel, cacheKey(content));
  return keys;
}
