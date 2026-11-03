import { rm, unlink } from 'node:fs/promises';
import path from 'node:path';

function inside(root, target) {
  const rel = path.relative(root, target);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

async function prune(dirs) {
  const deepest = [...dirs].sort((a, b) => b.length - a.length);
  for (const dir of deepest) {
    try {
      await rm(dir);
    } catch {
      // Not empty or already gone: an ancestor prune will stop there too.
    }
  }
}

// Drop outputs that the next manifest no longer claims (deleted sources, a
// hashed asset whose bytes changed) and the directories they leave empty.
export async function removeOutputs(outDir, names) {
  const removed = [];
  const dirs = new Set();
  for (const name of names) {
    const abs = path.resolve(outDir, name);
    if (!inside(outDir, abs)) continue;
    try {
      await unlink(abs);
      removed.push(name);
      dirs.add(path.dirname(abs));
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
  if (removed.length > 0) await prune(dirs);
  return removed;
}
