import { readdir } from 'node:fs/promises';
import path from 'node:path';

export function toPosix(rel) {
  return rel.split(path.sep).join('/');
}

export async function walk(dir, base = dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(toPosix(path.relative(base, abs)));
  }
  return files.sort();
}

export async function walkDirs(dir) {
  const dirs = [dir];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) dirs.push(...(await walkDirs(path.join(dir, entry.name))));
  }
  return dirs;
}
