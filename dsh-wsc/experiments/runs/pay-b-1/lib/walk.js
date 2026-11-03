import { readdir } from 'node:fs/promises';
import path from 'node:path';

/**
 * List every file under `dir` as posix paths relative to `base`, sorted.
 * `skip` is an optional predicate over absolute paths; a skipped directory is
 * not descended into (used to keep the output directory out of the source scan).
 */
export async function walk(dir, base = dir, skip = null) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (skip && skip(abs)) continue;
    if (entry.isDirectory()) files.push(...(await walk(abs, base, skip)));
    else if (entry.isFile()) files.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return files.sort();
}
