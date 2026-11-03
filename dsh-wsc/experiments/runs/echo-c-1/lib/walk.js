import { readdir } from 'node:fs/promises';
import path from 'node:path';

// Symlinks are neither files nor directories here: they are skipped, which is
// the semantics the builder has always had.
export async function walk(dir, base) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(abs, base)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}
