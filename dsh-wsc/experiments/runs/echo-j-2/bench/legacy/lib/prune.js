import { access, readdir, rmdir, unlink } from 'node:fs/promises';
import path from 'node:path';

export async function exists(abs) {
  try {
    await access(abs);
    return true;
  } catch {
    return false;
  }
}

// True when any output a manifest entry claims is gone from the output tree.
// Such an entry must be rebuilt instead of skipped.
export async function missingOutputs(outDir, outs) {
  for (const rel of outs) {
    if (!(await exists(path.join(outDir, rel)))) return true;
  }
  return false;
}

export async function removeOutputs(outDir, rels) {
  const removed = [];
  for (const rel of rels) {
    try {
      await unlink(path.join(outDir, rel));
      removed.push(rel);
    } catch (error) {
      if (error && error.code === 'ENOENT') continue;
      throw error;
    }
  }
  await pruneEmptyDirs(outDir, true);
  return removed;
}

async function pruneEmptyDirs(dir, root) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return false;
  }
  let empty = true;
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      empty = false;
      continue;
    }
    if (await pruneEmptyDirs(path.join(dir, entry.name), false)) {
      await rmdir(path.join(dir, entry.name)).catch(() => {});
    } else {
      empty = false;
    }
  }
  return empty && !root;
}
