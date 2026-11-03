import { createHash } from 'node:crypto';
import { readdir } from 'node:fs/promises';
import path from 'node:path';

export function cacheKey(bytes) {
  return `sha1:${createHash('sha1').update(bytes).digest('hex')}`;
}

export async function walkFiles(dir, base = dir) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walkFiles(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}
