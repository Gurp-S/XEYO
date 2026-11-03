import { readdir } from 'node:fs/promises';
import path from 'node:path';

// Source discovery. Paths are workspace-relative and always use forward
// slashes, so a manifest written on one platform reads back on another.

export async function scanSources(srcDir, exclude = []) {
  const excluded = new Set(exclude.map((entry) => path.resolve(entry)));
  const files = [];

  async function walk(dir) {
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch (error) {
      if (error && error.code === 'ENOENT') return;
      throw error;
    }
    entries.sort((left, right) => (left.name < right.name ? -1 : left.name > right.name ? 1 : 0));
    for (const entry of entries) {
      const abs = path.join(dir, entry.name);
      if (excluded.has(abs)) continue;
      if (entry.isDirectory()) {
        await walk(abs);
      } else if (entry.isFile()) {
        files.push(path.relative(srcDir, abs).split(path.sep).join('/'));
      }
    }
  }

  await walk(srcDir);
  return files.sort();
}
