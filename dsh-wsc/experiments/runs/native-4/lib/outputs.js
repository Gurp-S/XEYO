import { readdir, rm } from 'node:fs/promises';
import path from 'node:path';
import { mapLimit } from './pool.js';

// Relative POSIX paths of every regular file currently under `dir`, so the
// builder can tell which manifest entries point at outputs that are gone and
// which files in the output tree no source claims any more.
export async function listOutputs(dir) {
  const files = new Set();
  async function visit(abs, rel) {
    let entries;
    try {
      entries = await readdir(abs, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const childAbs = path.join(abs, entry.name);
      const childRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) await visit(childAbs, childRel);
      else if (entry.isFile()) files.add(childRel);
    }
  }
  await visit(dir, '');
  return files;
}

// Outputs that exist on disk but that no source claims any more.
export function staleOutputs(present, claimed) {
  const stale = [];
  for (const rel of present) if (!claimed.has(rel)) stale.push(rel);
  return stale.sort();
}

// Deletes the given outputs, refusing paths that would escape the output tree.
export async function removeOutputs(dir, rels, { concurrency = 1 } = {}) {
  const targets = [...new Set(rels)].filter(
    (rel) => typeof rel === 'string' && rel !== '' && !rel.startsWith('../') && !path.isAbsolute(rel),
  );
  await mapLimit(targets, concurrency, (rel) => rm(path.join(dir, rel), { force: true }));
  return targets.length;
}
