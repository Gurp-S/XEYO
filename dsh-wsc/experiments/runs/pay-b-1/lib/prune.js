import { rm } from 'node:fs/promises';
import path from 'node:path';

/**
 * Delete the given output paths (relative to `outDir`) and any directory that
 * becomes empty because of it, so a removed source leaves no trace behind.
 */
export async function pruneOutputs(outDir, rels) {
  for (const rel of rels) {
    const abs = path.join(outDir, rel);
    await rm(abs, { force: true });
    await pruneEmptyDirs(outDir, path.dirname(abs));
  }
}

async function pruneEmptyDirs(outDir, dir) {
  const { readdir, rmdir } = await import('node:fs/promises');
  let current = dir;
  while (current.startsWith(outDir) && current !== outDir) {
    try {
      const entries = await readdir(current);
      if (entries.length > 0) return;
      await rmdir(current);
    } catch {
      return;
    }
    current = path.dirname(current);
  }
}
