import { readdir, rmdir, unlink } from 'node:fs/promises';
import path from 'node:path';

const toPosix = (value) => value.split(path.sep).join('/');

async function scan(dir, base, files, dirs) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      dirs.push(abs);
      await scan(abs, base, files, dirs);
    } else if (entry.isFile()) {
      files.push(toPosix(path.relative(base, abs)));
    }
  }
}

// The out directory is owned by the builder, so anything the current manifest
// does not claim is garbage: an asset renamed by a content hash, an output of
// a deleted source, or a file left behind by an interrupted run. Removing it
// keeps an incremental build byte-identical to a full one.
export async function reapOutputs(outDir, claimed, ignore = new Set()) {
  const files = [];
  const dirs = [];
  await scan(outDir, outDir, files, dirs);

  const protectedPaths = new Set([...ignore].map((entry) => path.resolve(entry)));
  const removed = [];
  for (const rel of files) {
    if (claimed.has(rel)) continue;
    const abs = path.join(outDir, ...rel.split('/'));
    if (protectedPaths.has(path.resolve(abs))) continue;
    try {
      await unlink(abs);
      removed.push(rel);
    } catch {
      // A file another process already removed needs no cleanup.
    }
  }

  // Deepest first so a directory that only held removed files can go too.
  dirs.sort((a, b) => b.length - a.length);
  for (const dir of dirs) {
    try {
      await rmdir(dir);
    } catch {
      // Still populated: keep it.
    }
  }
  return removed;
}
