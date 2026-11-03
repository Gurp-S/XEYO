import { mkdir, readdir, rename, rmdir, stat, unlink, writeFile } from 'node:fs/promises';
import path from 'node:path';

const TMP_PREFIX = '.mini-build-tmp-';
let tmpCounter = 0;

// Runs `fn` over `items` with at most `limit` calls in flight. Results keep the
// input order so callers stay deterministic regardless of completion order.
export async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  const size = Math.max(1, Math.min(limit, items.length));
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      results[index] = await fn(items[index], index);
    }
  };
  await Promise.all(Array.from({ length: size }, worker));
  return results;
}

// Write to a sibling temp file and rename over the target, so a build that is
// interrupted mid-write never leaves a truncated output or manifest behind.
export async function writeFileAtomic(file, data, { stableTmp = false } = {}) {
  const dir = path.dirname(file);
  await mkdir(dir, { recursive: true });
  const tmp = stableTmp
    ? path.join(dir, `${TMP_PREFIX}${path.basename(file)}`)
    : path.join(dir, `${TMP_PREFIX}${process.pid}-${(tmpCounter += 1)}-${path.basename(file)}`);
  try {
    await writeFile(tmp, data);
    await rename(tmp, file);
  } catch (error) {
    await unlink(tmp).catch(() => {});
    throw error;
  }
}

export async function pathExists(file) {
  try {
    await stat(file);
    return true;
  } catch {
    return false;
  }
}

export async function removeOrphanTemps(root) {
  let entries;
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const abs = path.join(root, entry.name);
    if (entry.isDirectory()) await removeOrphanTemps(abs);
    else if (entry.isFile() && entry.name.startsWith(TMP_PREFIX)) await unlink(abs).catch(() => {});
  }
}

export async function pruneEmptyDirs(root, dirs) {
  for (const dir of dirs) {
    let current = dir;
    while (current !== root && current.startsWith(root + path.sep)) {
      try {
        await rmdir(current);
      } catch {
        break;
      }
      current = path.dirname(current);
    }
  }
}
